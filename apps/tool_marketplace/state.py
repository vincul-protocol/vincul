"""
apps.tool_marketplace.state — MarketplaceState for cross-vendor tool marketplace demo.

Wraps VinculContext + SDK decorators (@vincul_tool, @vincul_agent) to drive
the 6-step marketplace scenario through the webapp.
"""

from __future__ import annotations

from typing import Any

from vincul.identity import verify
from vincul.sdk import VinculContext, ToolResult
from vincul.types import OperationType, ReceiptKind, ScopeStatus

from .vendor_a_agent import VendorABuyerAgent, VENDOR_A_ID, VENDOR_B_ID, VENDOR_C_ID, AGENT_ID
from .vendor_b_tool import VendorBToolProvider, TOOL_NAMESPACE


class MarketplaceState:
    """
    State for the cross-vendor tool marketplace demo.
    Each step is a method that advances the scenario and returns a result dict.
    """

    def __init__(self) -> None:
        self.ctx: VinculContext | None = None
        self.tool: VendorBToolProvider | None = None
        self.agent: VendorABuyerAgent | None = None
        self.contract = None
        self.scopes: list = []
        self._setup_complete = False
        self._contract_complete = False
        self._scope_complete = False
        self._revoked = False
        self._post_revoke_invoked = False

    def reset(self) -> dict:
        self.__init__()
        return {"status": "reset"}

    # ── Step 1: Setup vendors ────────────────────────────────

    def setup_vendors(self) -> dict:
        if self._setup_complete:
            return {"status": "already_setup"}

        self.ctx = VinculContext()
        key_a = self.ctx.add_principal(VENDOR_A_ID, role="agent_host", permissions=["delegate", "commit"])
        key_b = self.ctx.add_principal(VENDOR_B_ID, role="tool_provider", permissions=["delegate", "commit", "revoke"])
        key_c = self.ctx.add_principal(VENDOR_C_ID, role="data_provider", permissions=["commit"])

        self.tool = VendorBToolProvider(key_pair=key_b, runtime=self.ctx.runtime)
        self._setup_complete = True

        return {
            "status": "setup_complete",
            "vendors": [
                {"id": VENDOR_A_ID, "role": "agent_host", "pubkey": key_a.public_key_b64()[:32] + "..."},
                {"id": VENDOR_B_ID, "role": "tool_provider", "pubkey": key_b.public_key_b64()[:32] + "..."},
                {"id": VENDOR_C_ID, "role": "data_provider", "pubkey": key_c.public_key_b64()[:32] + "..."},
            ],
            "tool_manifest": self.tool.tool_manifest,
        }

    # ── Step 2: Create contract ──────────────────────────────

    def create_contract(self) -> dict:
        if not self._setup_complete:
            raise ValueError("Run setup first")
        if self._contract_complete:
            return {
                "status": "already_created",
                "contract_id": self.contract.contract_id,
                "descriptor_hash": self.contract.descriptor_hash,
                "principals": self.contract.principal_ids(),
                "governance": self.contract.governance,
                "purpose": self.contract.purpose,
                "hash_valid": self.contract.verify_hash(),
            }

        self.contract = self.ctx.create_contract(
            purpose_title="Cross-vendor tool marketplace",
            purpose_description="VendorA agents invoke VendorB tools under scoped delegation",
        )
        self._contract_complete = True

        return {
            "status": "contract_active",
            "contract_id": self.contract.contract_id,
            "descriptor_hash": self.contract.descriptor_hash,
            "principals": self.contract.principal_ids(),
            "governance": self.contract.governance,
            "purpose": self.contract.purpose,
            "hash_valid": self.contract.verify_hash(),
        }

    # ── Step 3: Create scope DAG ─────────────────────────────

    def create_scopes(self) -> dict:
        if not self._contract_complete:
            raise ValueError("Run contract first")
        if self._scope_complete:
            labels = ["root", "mid", "leaf"]
            deleg_receipts = [
                r for r in self.ctx.receipts.timeline()
                if r.receipt_kind == ReceiptKind.DELEGATION
            ]
            return {
                "status": "already_created",
                "scopes": [
                    {
                        "label": labels[i],
                        "id": s.id,
                        "namespace": s.domain.namespace,
                        "types": [t.value for t in s.domain.types],
                        "ceiling": s.ceiling,
                        "predicate": s.predicate,
                        "delegate": s.delegate,
                        "status": self.ctx.scopes.get(s.id).status.value,
                        "parent_scope_id": s.issued_by_scope_id,
                        "descriptor_hash": s.descriptor_hash,
                    }
                    for i, s in enumerate(self.scopes)
                ],
                "delegation_receipts": [
                    {
                        "receipt_hash": r.receipt_hash,
                        "child_scope_id": r.detail["child_scope_id"],
                        "parent_scope_id": r.detail["parent_scope_id"],
                    }
                    for r in deleg_receipts
                ],
            }

        self.scopes = self.ctx.create_scope_chain(
            contract_id=self.contract.contract_id,
            issued_by=VENDOR_B_ID,
            namespace=TOOL_NAMESPACE,
            chain=[
                {"ceiling": "TOP", "ttl_hours": 2},
                {"ceiling": "params.quantity <= 10", "ttl_hours": 1.5},
                {"ceiling": "params.quantity <= 5", "delegate": False, "ttl_hours": 1},
            ],
        )

        self.agent = VendorABuyerAgent(contract=self.contract, scopes=[self.scopes[-1]])
        self._scope_complete = True

        # Collect delegation receipts
        deleg_receipts = [
            r for r in self.ctx.receipts.timeline()
            if r.receipt_kind == ReceiptKind.DELEGATION
        ]

        labels = ["root", "mid", "leaf"]
        return {
            "status": "scopes_created",
            "scopes": [
                {
                    "label": labels[i],
                    "id": s.id,
                    "namespace": s.domain.namespace,
                    "types": [t.value for t in s.domain.types],
                    "ceiling": s.ceiling,
                    "predicate": s.predicate,
                    "delegate": s.delegate,
                    "status": s.status.value,
                    "parent_scope_id": s.issued_by_scope_id,
                    "descriptor_hash": s.descriptor_hash,
                }
                for i, s in enumerate(self.scopes)
            ],
            "delegation_receipts": [
                {
                    "receipt_hash": r.receipt_hash,
                    "child_scope_id": r.detail["child_scope_id"],
                    "parent_scope_id": r.detail["parent_scope_id"],
                }
                for r in deleg_receipts
            ],
        }

    # ── Step 4: Invoke tool ──────────────────────────────────

    def invoke(self, *, item_id: str, quantity: int, shipping_zip: str = "10001") -> dict:
        if not self._scope_complete:
            raise ValueError("Run scope creation first")

        # After revocation: first invoke demonstrates fail-closed (uses revoked scope),
        # subsequent invokes re-create scopes (for constraint violation testing)
        if self._revoked and self._post_revoke_invoked and not self._scope_recreated():
            self._recreate_scopes()
        if self._revoked:
            self._post_revoke_invoked = True

        result = self.agent.buy(
            self.tool,
            item_id=item_id,
            quantity=quantity,
            shipping_zip=shipping_zip,
        )

        response: dict[str, Any] = {
            "success": result.success,
            "receipt_kind": result.receipt.receipt_kind.value,
            "receipt_hash": result.receipt.receipt_hash,
            "outcome": result.receipt.outcome,
        }

        if result.success:
            response["payload"] = result.payload
            response["attested_result"] = {
                "status": result.attested_result["status"],
                "tool_id": result.attested_result["tool_id"],
                "contract_hash": result.attested_result["contract_hash"],
                "scope_hash": result.attested_result["scope_hash"],
                "receipt_hash": result.attested_result["receipt_hash"],
                "result_payload": result.attested_result["result_payload"],
                "result_payload_hash": result.attested_result["result_payload_hash"],
                "external_ref": result.attested_result["external_ref"],
                "signature": {
                    "signer_id": result.attested_result["signature"]["signer_id"],
                    "algo": result.attested_result["signature"]["algo"],
                },
            }
            # Verify signature
            key_b = self.ctx.keypair(VENDOR_B_ID)
            sig_valid = verify(
                key_b.public_key,
                result.attested_result["result_payload_hash"].encode("utf-8"),
                result.attested_result["signature"]["sig"],
            )
            response["signature_valid"] = sig_valid
        else:
            response["failure_code"] = result.failure_code
            response["message"] = result.message

        return response

    # ── Step 5: Revoke ───────────────────────────────────────

    def revoke(self) -> dict:
        if not self._scope_complete:
            raise ValueError("Run scope creation first")
        if self._revoked:
            rev_receipts = [
                r for r in self.ctx.receipts.timeline()
                if r.receipt_kind == ReceiptKind.REVOCATION
            ]
            rev_receipt = rev_receipts[-1] if rev_receipts else None
            return {
                "status": "already_revoked",
                "revocation_root": self.scopes[1].id,
                "revoked_scope_ids": [s.id for s in self.scopes[1:] if self.ctx.scopes.get(s.id).status == ScopeStatus.REVOKED],
                "effective_at": rev_receipt.detail["effective_at"] if rev_receipt else None,
                "receipt_hash": rev_receipt.receipt_hash if rev_receipt else None,
                "scope_states": [
                    {
                        "label": label,
                        "id": s.id,
                        "status": self.ctx.scopes.get(s.id).status.value,
                    }
                    for label, s in zip(["root", "mid", "leaf"], self.scopes)
                ],
            }

        mid = self.scopes[1]
        rev_receipt, rev_result = self.ctx.revoke_scope(
            scope_id=mid.id,
            contract_id=self.contract.contract_id,
            initiated_by=VENDOR_B_ID,
        )
        self._revoked = True

        return {
            "status": "revoked",
            "revocation_root": rev_result.root_scope_id,
            "revoked_scope_ids": rev_result.revoked_ids,
            "effective_at": rev_result.effective_at,
            "receipt_hash": rev_receipt.receipt_hash,
            "scope_states": [
                {
                    "label": label,
                    "id": s.id,
                    "status": self.ctx.scopes.get(s.id).status.value,
                }
                for label, s in zip(["root", "mid", "leaf"], self.scopes)
            ],
        }

    # ── Step 6: Audit trail ──────────────────────────────────

    def audit(self) -> dict:
        if self.ctx is None:
            raise ValueError("Run setup first")

        timeline = self.ctx.receipts.timeline()
        return {
            "total_receipts": len(timeline),
            "all_hashes_valid": all(r.verify_hash() for r in timeline),
            "receipts": [
                {
                    "index": i,
                    "receipt_kind": r.receipt_kind.value,
                    "outcome": r.outcome,
                    "initiated_by": r.initiated_by,
                    "receipt_hash": r.receipt_hash,
                    "scope_id": r.scope_id,
                    "description": r.description,
                    "detail": r.detail,
                    "hash_valid": r.verify_hash(),
                }
                for i, r in enumerate(timeline)
            ],
        }

    # ── Internal helpers ─────────────────────────────────────

    def _scope_recreated(self) -> bool:
        """Check if scopes were already recreated after revocation."""
        leaf = self.ctx.scopes.get(self.scopes[-1].id)
        return leaf.status == ScopeStatus.ACTIVE

    def _recreate_scopes(self) -> None:
        """Recreate scope chain after revocation (for constraint violation testing)."""
        self.scopes = self.ctx.create_scope_chain(
            contract_id=self.contract.contract_id,
            issued_by=VENDOR_B_ID,
            namespace=TOOL_NAMESPACE,
            chain=[
                {"ceiling": "TOP", "ttl_hours": 2},
                {"ceiling": "params.quantity <= 10", "ttl_hours": 1.5},
                {"ceiling": "params.quantity <= 5", "delegate": False, "ttl_hours": 1},
            ],
        )
        self.agent = VendorABuyerAgent(contract=self.contract, scopes=[self.scopes[-1]])


# ── Module-level singleton ────────────────────────────────────

marketplace_state = MarketplaceState()
