"""vincul.sdk.decorators — @vincul_tool and @vincul_tool_action decorators.

Wraps tool classes and their operation methods so that all vincul
initialization, validation pipeline, receipt handling, and attestation
are handled automatically. Tool authors write only business logic.
"""

from __future__ import annotations

import functools
from dataclasses import InitVar, dataclass, field
from typing import Any

from vincul.hashing import vincul_hash
from vincul.identity import KeyPair, sign
from vincul.receipts import Receipt, new_uuid, now_utc
from vincul.types import OperationType, ReceiptKind


# ── ToolResult ────────────────────────────────────────────────

@dataclass
class ToolResult:
    """Unified return type from vincul tool operations.

    Auto-attests when ``tool_id`` and ``signer`` are provided.  The attested
    result is built internally using the receipt's authority hashes — callers
    never need to call ``_build_attested_result`` directly.

    Usage::

        result = ToolResult(
            success=True,
            receipt=receipt,
            payload={"order_id": "ord-001"},
            tool_id="agentic_demo:propose_terms",
            signer=keypair,
        )
        assert result.attested_result is not None  # auto-built
    """

    success: bool
    receipt: Receipt
    payload: dict[str, Any] | None = None
    attested_result: dict[str, Any] | None = field(default=None, init=False)

    # InitVar — consumed by __post_init__, not stored as fields
    tool_id: InitVar[str | None] = None
    tool_version: InitVar[str] = "0.1.0"
    signer: InitVar[KeyPair | None] = None
    external_ref: InitVar[str] = ""

    def __post_init__(self, tool_id, tool_version, signer, external_ref):
        if tool_id is not None and signer is not None:
            if self.success:
                result_payload = self.payload or {}
            else:
                result_payload = {
                    "failure_code": self.receipt.detail.get("error_code", "UNKNOWN"),
                    "message": self.receipt.detail.get("message", ""),
                }
            self.attested_result = _build_attested_result(
                tool_id=tool_id,
                tool_version=tool_version,
                contract_hash=self.receipt.contract_hash or "",
                scope_hash=self.receipt.scope_hash or "",
                receipt_hash=self.receipt.receipt_hash,
                status="success" if self.success else "failure",
                result_payload=result_payload,
                external_ref=external_ref,
                signer=signer,
            )

    @property
    def failure_code(self) -> str | None:
        if not self.success and self.receipt:
            return self.receipt.detail.get("error_code")
        return None

    @property
    def message(self) -> str | None:
        if not self.success and self.receipt:
            return self.receipt.detail.get("message")
        return None


# ── Attested result builder ───────────────────────────────────

def _build_attested_result(
    *,
    tool_id: str,
    tool_version: str,
    contract_hash: str,
    scope_hash: str,
    receipt_hash: str,
    status: str,
    result_payload: dict,
    external_ref: str = "",
    signer: KeyPair,
) -> dict[str, Any]:
    """Build a signed Attested Result (VMIP wire-format overlay)."""
    result_payload_hash = vincul_hash("receipt", result_payload)
    result: dict[str, Any] = {
        "result_version": "vmip-0.1",
        "result_id": new_uuid(),
        "tool_id": tool_id,
        "tool_version": tool_version,
        "contract_hash": contract_hash,
        "scope_hash": scope_hash,
        "receipt_hash": receipt_hash,
        "status": status,
        "result_payload": result_payload,
        "result_payload_hash": result_payload_hash,
        "timestamp": now_utc(),
        "external_ref": external_ref,
    }
    result["signature"] = {
        "signer_id": signer.principal_id,
        "algo": "Ed25519",
        "sig": sign(signer, result_payload_hash.encode("utf-8")),
    }
    return result


# ── @vincul_tool class decorator ──────────────────────────────

def vincul_tool(
    *,
    namespace: str,
    tool_id: str,
    tool_version: str = "0.1.0",
):
    """Class decorator for vincul tool providers.

    The decorated class must set ``key_pair`` and ``runtime`` in __init__.

    Adds:
      - ``_vincul_namespace``, ``_vincul_tool_id``, ``_vincul_tool_version``
      - Auto-generated ``tool_manifest`` attribute (set after __init__)

    Example::

        @vincul_tool(namespace="marketplace.orders", tool_id="tool:VendorB:order-tool")
        class OrderTool:
            def __init__(self, key_pair, runtime):
                self.key_pair = key_pair
                self.runtime = runtime

            @vincul_tool_action(action_type=OperationType.COMMIT, resource_key="item_id")
            def place_order(self, *, item_id, quantity, shipping_zip):
                return {"order_id": "ord-001", "charged": quantity * 12.34}
    """

    def decorator(cls):
        cls._vincul_namespace = namespace
        cls._vincul_tool_id = tool_id
        cls._vincul_tool_version = tool_version

        orig_init = cls.__init__

        @functools.wraps(orig_init)
        def wrapped_init(self, *args, **kwargs):
            orig_init(self, *args, **kwargs)
            # Collect @vincul_tool_action methods and build manifest
            ops = []
            for name in dir(type(self)):
                attr = getattr(type(self), name, None)
                if hasattr(attr, "_vincul_op_meta"):
                    meta = attr._vincul_op_meta
                    ops.append({
                        "name": meta["name"],
                        "description": meta.get("description", ""),
                        "action_type": meta["action_type"].value,
                        "side_effecting": meta.get("side_effecting", True),
                    })
            vendor_id = ""
            if hasattr(self, "key_pair") and self.key_pair:
                vendor_id = self.key_pair.principal_id
            self.tool_manifest = {
                "tool_manifest_version": "vmip-0.1",
                "tool_id": tool_id,
                "vendor_id": vendor_id,
                "tool_version": tool_version,
                "protocol": "mcp",
                "namespace": namespace,
                "operations": ops,
                "attestation_policy": {
                    "result_signature_required": True,
                    "external_ref_required": True,
                },
            }

        cls.__init__ = wrapped_init
        return cls

    return decorator


# ── @vincul_tool_action method decorator ──────────────────────────

def vincul_tool_action(
    *,
    action_type: OperationType = OperationType.COMMIT,
    resource_key: str | None = None,
    side_effecting: bool = True,
    description: str = "",
):
    """Method decorator for vincul tool operations.

    Wraps a business-logic method to automatically:
      1. Build the action dict from business params
      2. Run the 7-step enforcement pipeline (``runtime.commit``)
      3. On failure: return ``ToolResult`` with failure receipt + attested result
      4. On success: call business logic, attest result, return ``ToolResult``

    The decorated method should accept only business keyword args and
    return a dict payload. Authority params (``scope_id``, ``contract_id``,
    ``initiated_by``) are passed by the caller alongside business params.

    Example::

        @vincul_tool_action(action_type=OperationType.COMMIT, resource_key="item_id")
        def place_order(self, *, item_id: str, quantity: int) -> dict:
            return {"order_id": "ord-001"}

        # Caller:
        result = tool.place_order(
            scope_id=leaf.id, contract_id=c.contract_id,
            initiated_by="agent:A:buyer",
            item_id="book-1", quantity=2,
        )
    """

    def decorator(fn):
        fn._vincul_op_meta = {
            "name": fn.__name__,
            "action_type": action_type,
            "side_effecting": side_effecting,
            "description": description or fn.__doc__ or "",
        }

        @functools.wraps(fn)
        def wrapper(self, **kwargs):
            # Separate authority params from business params
            scope_id = kwargs.pop("scope_id")
            contract_id = kwargs.pop("contract_id")
            initiated_by = kwargs.pop("initiated_by")
            budget_amounts = kwargs.pop("budget_amounts", None)
            business_params = kwargs

            # Build resource path
            resource = fn.__name__
            if resource_key and resource_key in business_params:
                resource = f"{fn.__name__}/{business_params[resource_key]}"

            # Build action dict
            action = {
                "type": action_type.value,
                "namespace": self._vincul_namespace,
                "resource": resource,
                "params": business_params,
            }

            # Run 7-step enforcement pipeline
            receipt = self.runtime.commit(
                action=action,
                scope_id=scope_id,
                contract_id=contract_id,
                initiated_by=initiated_by,
                reversible=False,
                budget_amounts=budget_amounts,
            )

            if receipt.receipt_kind == ReceiptKind.FAILURE:
                return ToolResult(
                    success=False,
                    receipt=receipt,
                    tool_id=self._vincul_tool_id,
                    tool_version=self._vincul_tool_version,
                    signer=self.key_pair,
                )

            # Call business logic
            result_payload = fn(self, **business_params)

            # Auto-detect external_ref from common payload keys
            external_ref = ""
            if isinstance(result_payload, dict):
                for key in ("order_id", "id", "ref", "external_ref"):
                    if key in result_payload:
                        external_ref = str(result_payload[key])
                        break

            return ToolResult(
                success=True,
                receipt=receipt,
                payload=result_payload,
                tool_id=self._vincul_tool_id,
                tool_version=self._vincul_tool_version,
                signer=self.key_pair,
                external_ref=external_ref,
            )

        return wrapper

    return decorator
