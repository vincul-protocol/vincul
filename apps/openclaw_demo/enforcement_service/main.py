"""
Vincul Enforcement Service for the OpenClaw demo.

FastAPI app that receives tool call enforcement requests from the
OpenClaw interceptor and validates them against the Vincul runtime.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel

from apps.openclaw_demo.enforcement_service.scenario import (
    AGENT_SCOPES,
    CONTRACT_ID,
    setup_scenario,
)
from vincul.types import OperationType

logger = logging.getLogger("vincul.enforce")

app = FastAPI(title="Vincul Enforcement Service", version="0.1.0")

# Initialize the Vincul runtime with the demo scenario
runtime = setup_scenario()


class EnforceRequest(BaseModel):
    """Request from the OpenClaw interceptor's tool.before hook."""
    agent: str           # e.g. "alice-agent"
    tool: str            # e.g. "message", "sessions_send"
    action: str          # e.g. "send", "list"
    target: str | None = None   # e.g. "bob" (for message send)
    params: dict[str, Any] = {}


class EnforceResponse(BaseModel):
    """Response to the interceptor."""
    allowed: bool
    failure_code: str | None = None
    message: str | None = None
    receipt_hash: str | None = None
    pipeline_step: str | None = None


# Mapping from OpenClaw tool calls to Vincul namespace + operation type
TOOL_TO_VINCUL: dict[str, dict[str, Any]] = {
    "message:send": {
        "op_type": OperationType.COMMIT,
        "namespace_fn": lambda req: f"gateway.messaging.{req.target or 'unknown'}",
    },
    "message:list": {
        "op_type": OperationType.OBSERVE,
        "namespace_fn": lambda req: f"gateway.messaging.{req.agent.split('-')[0]}",
    },
    "sessions_send": {
        "op_type": OperationType.COMMIT,
        "namespace_fn": lambda _: "gateway.a2a",
    },
    "sessions_list": {
        "op_type": OperationType.OBSERVE,
        "namespace_fn": lambda _: "gateway.a2a",
    },
    "sessions_history": {
        "op_type": OperationType.OBSERVE,
        "namespace_fn": lambda _: "gateway.a2a",
    },
}


def _resolve_tool_key(req: EnforceRequest) -> str:
    """Map request to a tool lookup key."""
    if req.tool == "message":
        return f"message:{req.action}"
    return req.tool


def _find_best_scope(agent: str, namespace: str, op_type: OperationType) -> str | None:
    """Find the most specific scope that could authorize this action."""
    scope_ids = AGENT_SCOPES.get(agent, [])
    for scope_id in scope_ids:
        scope = runtime.scopes.get(scope_id)
        if scope and scope.domain.contains_namespace(namespace):
            return scope_id
    # Fallback: return first scope (will fail validation but produce receipt)
    return scope_ids[0] if scope_ids else None


@app.get("/health")
async def health():
    return {"status": "ok", "scenario": "openclaw_demo"}


@app.post("/enforce", response_model=EnforceResponse)
async def enforce(req: EnforceRequest):
    """
    Enforce a tool call through the Vincul 7-step pipeline.

    Called by the OpenClaw tool.before interceptor before each tool execution.
    """
    tool_key = _resolve_tool_key(req)
    mapping = TOOL_TO_VINCUL.get(tool_key)

    if not mapping:
        # Unknown tool — deny by default (fail-closed)
        return EnforceResponse(
            allowed=False,
            failure_code="UNKNOWN_TOOL",
            message=f"Tool '{req.tool}:{req.action}' not mapped to Vincul namespace",
        )

    op_type: OperationType = mapping["op_type"]
    namespace: str = mapping["namespace_fn"](req)

    # Build the action dict for the validator
    action = {
        "type": op_type.value,
        "namespace": namespace,
        "resource": f"{req.tool}:{req.action}",
        "params": req.params,
    }

    # Find the best scope for this agent + namespace
    scope_id = _find_best_scope(req.agent, namespace, op_type)
    if not scope_id:
        return EnforceResponse(
            allowed=False,
            failure_code="NO_SCOPE",
            message=f"No scope found for agent '{req.agent}'",
        )

    # Run through the 7-step pipeline via runtime.commit()
    receipt = runtime.commit(
        action=action,
        scope_id=scope_id,
        contract_id=CONTRACT_ID,
        initiated_by=req.agent,
    )

    allowed = receipt.receipt_kind.value != "failure"

    resp = EnforceResponse(
        allowed=allowed,
        receipt_hash=receipt.receipt_hash,
    )

    if not allowed:
        resp.failure_code = receipt.detail.get("error_code", "UNKNOWN")
        resp.message = receipt.detail.get("message", "")
        # Determine pipeline step from failure code
        resp.pipeline_step = _failure_code_to_step(resp.failure_code)
        logger.warning(
            "DENIED: agent=%s tool=%s namespace=%s code=%s step=%s",
            req.agent, tool_key, namespace, resp.failure_code, resp.pipeline_step,
        )
    else:
        logger.info(
            "ALLOWED: agent=%s tool=%s namespace=%s",
            req.agent, tool_key, namespace,
        )

    return resp


def _failure_code_to_step(code: str) -> str:
    """Map failure code to the pipeline step name for display."""
    step_map = {
        "CONTRACT_NOT_ACTIVE": "Step 1: contract validity",
        "CONTRACT_EXPIRED": "Step 1: contract validity",
        "CONTRACT_DISSOLVED": "Step 1: contract validity",
        "SCOPE_REVOKED": "Step 2: scope validity",
        "SCOPE_EXPIRED": "Step 2: scope validity",
        "ANCESTOR_INVALID": "Step 2: scope validity",
        "TYPE_ESCALATION": "Step 3: operation type",
        "SCOPE_EXCEEDED": "Step 4: namespace containment",
        "SCOPE_INVALID": "Step 5: predicate evaluation",
        "CEILING_VIOLATED": "Step 6: ceiling check",
        "BUDGET_EXCEEDED": "Step 7: budget check",
    }
    return step_map.get(code, f"Unknown ({code})")


@app.get("/receipts")
async def list_receipts():
    """Return all receipts for demo inspection."""
    receipts = [
        runtime.receipts._by_hash[h]
        for h in runtime.receipts._ordered
    ]
    return {
        "count": len(receipts),
        "receipts": [
            {
                "receipt_hash": r.receipt_hash,
                "kind": r.receipt_kind.value,
                "detail": r.detail,
            }
            for r in receipts
        ],
    }


@app.post("/revoke/{scope_id}")
async def revoke_scope(scope_id: str, initiated_by: str = "alice"):
    """Revoke a scope (for Act 3 cascade demonstration)."""
    receipt, result = runtime.revoke(
        scope_id=scope_id,
        contract_id=CONTRACT_ID,
        initiated_by=initiated_by,
    )
    return {
        "receipt_hash": receipt.receipt_hash,
        "revoked_count": len(result.revoked_ids),
        "revoked_ids": list(result.revoked_ids),
    }
