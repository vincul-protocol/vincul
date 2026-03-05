"""
vincul.transport.protocol_peer — ProtocolPeer: Vincul protocol over VinculNet

Composes VinculPeer (authenticated transport) with VinculRuntime (protocol
enforcement). An agent can commit actions, validate locally, and broadcast
success receipts to connected peers.

Security model:
  - Each peer validates actions against its own local VinculRuntime
  - Only success receipts are broadcast (failures stay local)
  - Receiving peer verifies receipt hash + cross-checks scope/contract hashes
  - Receipts with mismatched hashes are silently rejected

Depends on: vincul.transport.peer, vincul.runtime, vincul.receipts, vincul.contract, vincul.scopes
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from vincul.contract import CoalitionContract
from vincul.identity import KeyPair
from vincul.receipts import Receipt
from vincul.runtime import VinculRuntime
from vincul.scopes import Scope
from vincul.transport.peer import VinculPeer

logger = logging.getLogger("vincul.transport.protocol_peer")


class ProtocolPeer:
    """
    Vincul protocol peer: VinculPeer + VinculRuntime.

    Each ProtocolPeer runs a local VinculRuntime for validation and
    enforcement. Success receipts are broadcast to all connected peers.
    Receiving peers verify receipt integrity and cross-check against
    their own local state before storing.
    """

    def __init__(self, principal_id: str, keypair: KeyPair) -> None:
        self.principal_id = principal_id
        self.peer = VinculPeer(principal_id, keypair)
        self.runtime = VinculRuntime()
        self._receipt_handlers: list[Callable[[str, Receipt], None]] = []

        # Wire transport messages to protocol dispatch
        self.peer.on_message(self._dispatch)

    # ── Network (delegates to VinculPeer) ─────────────────────

    async def listen(self, host: str = "localhost", port: int = 8765) -> None:
        await self.peer.listen(host, port)

    async def connect(self, uri: str) -> str | None:
        return await self.peer.connect(uri)

    async def stop(self) -> None:
        await self.peer.stop()

    # ── State bootstrap ───────────────────────────────────────

    def load_contract(self, contract: CoalitionContract) -> None:
        """Register and activate a contract in the local runtime."""
        self.runtime.register_contract(contract)
        principal_ids = contract.principal_ids()
        self.runtime.activate_contract(
            contract.contract_id,
            contract.activation.get("activated_at", contract.purpose.get("created_at", "2025-01-01T00:00:00Z")),
            principal_ids,
        )

    def load_scope(self, scope: Scope) -> None:
        """Add a scope to the local runtime's scope store."""
        self.runtime.scopes.add(scope)

    def set_budget_ceiling(self, scope_id: str, dimension: str, amount: str) -> None:
        """Set a budget ceiling for a scope dimension."""
        self.runtime.budget.set_ceiling(scope_id, dimension, amount)

    # ── Protocol operations ───────────────────────────────────

    async def commit_action(
        self,
        scope_id: str,
        contract_id: str,
        action: dict[str, Any],
        *,
        budget_amounts: dict[str, str] | None = None,
    ) -> Receipt:
        """
        Execute a COMMIT action through the local enforcement pipeline.

        On success: broadcast receipt to all connected peers.
        On failure: return failure receipt (not broadcast).
        """
        receipt = self.runtime.commit(
            action=action,
            scope_id=scope_id,
            contract_id=contract_id,
            initiated_by=self.principal_id,
            budget_amounts=budget_amounts,
        )

        # Broadcast success receipts to all connected peers
        if receipt.outcome == "success":
            payload = {"type": "receipt", "receipt": receipt.to_dict()}
            for peer_id in self.peer.registry.all_peers():
                await self.peer.send(peer_id, payload)

        return receipt

    # ── Callbacks ─────────────────────────────────────────────

    def on_receipt(self, handler: Callable[[str, Receipt], None]) -> None:
        """Register a callback for verified incoming receipts.

        handler(sender_id: str, receipt: Receipt) -> None
        """
        self._receipt_handlers.append(handler)

    # ── Internal dispatch ─────────────────────────────────────

    def _dispatch(self, sender_id: str, payload: dict) -> None:
        """Route incoming messages by type."""
        msg_type = payload.get("type")
        if msg_type == "receipt":
            self._handle_receipt(sender_id, payload)
        else:
            logger.warning(
                f"[{self.principal_id}] Unknown message type: {msg_type}"
            )

    def _handle_receipt(self, sender_id: str, payload: dict) -> None:
        """Verify and store an incoming receipt."""
        try:
            receipt = Receipt.from_dict(payload["receipt"])
        except (KeyError, ValueError) as e:
            logger.warning(
                f"[{self.principal_id}] Invalid receipt from {sender_id}: {e}"
            )
            return

        # 1. Verify receipt's own hash (not tampered in transit)
        if not receipt.verify_hash():
            logger.warning(
                f"[{self.principal_id}] Receipt hash verification failed "
                f"from {sender_id}"
            )
            return

        # 2. Cross-check scope_hash against local state
        if receipt.scope_id:
            local_scope = self.runtime.scopes.get(receipt.scope_id)
            if local_scope and local_scope.descriptor_hash != receipt.scope_hash:
                logger.warning(
                    f"[{self.principal_id}] Scope hash mismatch from {sender_id}: "
                    f"local={local_scope.descriptor_hash}, "
                    f"receipt={receipt.scope_hash}"
                )
                return

        # 3. Cross-check contract_hash against local state
        local_contract = self.runtime.contracts.get(receipt.contract_id)
        if local_contract and local_contract.descriptor_hash != receipt.contract_hash:
            logger.warning(
                f"[{self.principal_id}] Contract hash mismatch from {sender_id}: "
                f"local={local_contract.descriptor_hash}, "
                f"receipt={receipt.contract_hash}"
            )
            return

        # 4. Store in local receipt log (idempotent on duplicate)
        try:
            self.runtime.receipts.append(receipt)
        except ValueError:
            pass  # duplicate receipt — idempotent

        # 5. Notify handlers
        for handler in self._receipt_handlers:
            handler(sender_id, receipt)
