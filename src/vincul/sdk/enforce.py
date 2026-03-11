"""vincul.sdk.enforce — @vincul_enforce decorator and VinculAgentContext.

Provides a function decorator that composes with Strands @tool to add
Vincul enforcement to LLM agent tools.  The decorator handles scope
lookup, 7-step pipeline execution, ToolResult wrapping, and attestation.

Usage::

    @tool(name="place_order")
    @vincul_enforce(
        action_type=OperationType.COMMIT,
        tool_id="marketplace:place_order",
        agent=lambda: current_agent,
        namespace="marketplace.orders",
        action_params="order",  # kwargs["order"] becomes action["params"]
    )
    def place_order(order: dict) -> dict:
        \"\"\"Place an order — only runs if Vincul enforcement passes.\"\"\"
        return {"order_id": "ord-001"}
"""

from __future__ import annotations

import functools
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Callable

from vincul.runtime import VinculRuntime
from vincul.scopes import Scope
from vincul.types import FailureCode, OperationType

from vincul.sdk.decorators import ToolResult

logger = logging.getLogger("vincul.sdk.enforce")


@dataclass
class VinculAgentContext:
    """Pre-built authority bundle for one agent.

    Bundles a principal's identity, runtime, scopes, and optional
    callbacks into a single object that ``@vincul_enforce`` resolves
    at call time.

    Callbacks:
        on_commit:  ``(Receipt) -> None`` — fired on successful commit
                    (e.g. broadcast receipt over VinculNet).
        on_result:  ``(ToolResult, OperationType, dict) -> dict | None``
                    — fired after every enforcement attempt.  Return an
                    optional dict to merge into the JSON response.
    """

    principal_id: str
    contract_id: str
    signer: Any  # KeyPair
    runtime: VinculRuntime
    _scopes: list[Scope] = field(default_factory=list)
    on_commit: Callable | None = None
    on_result: Callable | None = None

    def find_scope(self, namespace: str, action_type: str) -> Scope | None:
        """Find a scope authorizing *action_type* on *namespace*."""
        op = OperationType(action_type)
        for scope in self._scopes:
            if op in scope.domain.types and scope.domain.contains_namespace(namespace):
                return scope
        return None


def vincul_enforce(
    *,
    action_type: OperationType,
    tool_id: str,
    agent: Callable[[], VinculAgentContext],
    namespace: str | Callable[..., str],
    action_params: str | Callable[..., dict] | None = None,
    tool_version: str = "0.1.0",
    pre_check: Callable[..., str | None] | None = None,
):
    """Function decorator — runs Vincul enforcement before business logic.

    Composable with Strands ``@tool``::

        @tool(name="...")         # outer: LLM interface
        @vincul_enforce(...)      # inner: authority enforcement
        def my_action(...):       # business logic (only runs if allowed)

    Args:
        action_type: OperationType (OBSERVE, PROPOSE, COMMIT).
        tool_id: Identifier for attestation (e.g. ``"demo:propose"``).
        agent: Callable returning the current VinculAgentContext.
        namespace: Static string or ``callable(**tool_kwargs) -> str``.
        action_params: Selects which tool kwargs become ``action["params"]``.
                       ``str`` — use that kwarg's value as the params dict.
                       ``callable(**tool_kwargs) -> dict`` — full control.
                       ``None`` (default) — all tool kwargs are used as action params.
        tool_version: Version string for attestation (default ``"0.1.0"``).
        pre_check: Optional ``callable(**tool_kwargs) -> denial_message | None``.
                   Return a string to deny before enforcement runs.
    """

    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(**kwargs):
            # ── Pre-check (optional application-level guard) ────
            if pre_check is not None:
                denial = pre_check(**kwargs)
                if denial is not None:
                    return json.dumps({"status": "denied", "message": denial})

            ctx = agent()
            ns = namespace(**kwargs) if callable(namespace) else namespace

            # ── Scope lookup ────────────────────────────────────
            scope = ctx.find_scope(ns, action_type.value)
            if scope is None:
                return json.dumps({
                    "status": "denied",
                    "failure_code": FailureCode.SCOPE_INVALID.value,
                    "message": f"No authority to {action_type.value} on {ns}",
                })

            # ── Build action + run 7-step pipeline ──────────────
            if action_params is None:
                params = kwargs
            elif isinstance(action_params, str):
                params = kwargs[action_params]
            else:
                params = action_params(**kwargs)
            action = {
                "type": action_type.value,
                "namespace": ns,
                "resource": fn.__name__,
                "params": params,
            }
            receipt = ctx.runtime.commit(
                action=action,
                scope_id=scope.id,
                contract_id=ctx.contract_id,
                initiated_by=ctx.principal_id,
            )

            # ── Wrap in ToolResult (auto-attests) ───────────────
            tool_result = ToolResult(
                success=receipt.outcome == "success",
                receipt=receipt,
                payload=kwargs,
                tool_id=tool_id,
                tool_version=tool_version,
                signer=ctx.signer,
            )

            # ── Fire on_result callback ─────────────────────────
            extra = {}
            if ctx.on_result:
                extra = ctx.on_result(tool_result, action_type, kwargs) or {}

            # ── Failure path ────────────────────────────────────
            if not tool_result.success:
                return json.dumps({
                    "status": "denied",
                    "failure_code": tool_result.failure_code,
                    "message": tool_result.message,
                    "hint": "Your proposed values violate scope constraints. Try different values.",
                    **extra,
                })

            # ── Success: broadcast receipt ──────────────────────
            if ctx.on_commit:
                ctx.on_commit(receipt)

            # ── Success: call business logic ────────────────────
            payload = fn(**kwargs)

            response = {
                "status": "success",
                "action_type": action_type.value,
                "receipt_hash": receipt.receipt_hash[:32],
            }
            if isinstance(payload, dict):
                response.update(payload)
            response.update(extra)
            return json.dumps(response)

        return wrapper

    return decorator
