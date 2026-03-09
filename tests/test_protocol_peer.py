"""
tests.test_protocol_peer — Integration tests for ProtocolPeer

Two-agent Italy trip scenario: Raanan (flights, COMMIT) and Yaki
(accommodation, OBSERVE+PROPOSE only). Both share identical contract
and scope state. Tests verify receipt exchange, budget enforcement,
and tamper rejection over real WebSocket connections.
"""

import asyncio
import json
import unittest
import uuid

from vincul.contract import CoalitionContract
from vincul.identity import KeyPair
from vincul.receipts import Receipt
from vincul.scopes import Scope
from vincul.transport.protocol_peer import ProtocolPeer
from vincul.types import Domain, OperationType


# ── Fixture constants ─────────────────────────────────────────

CONTRACT_ID = str(uuid.uuid4())
ROOT_SCOPE_ID = str(uuid.uuid4())
FLIGHT_SCOPE_ID = str(uuid.uuid4())
HOTEL_SCOPE_ID = str(uuid.uuid4())


def _keypair(principal_id: str) -> KeyPair:
    return KeyPair.generate(principal_id)


def _make_contract() -> CoalitionContract:
    return CoalitionContract(
        contract_id=CONTRACT_ID,
        version="0.2",
        purpose={
            "title": "Italy Trip Coalition",
            "description": "Raanan and Yaki plan a trip to Italy",
            "created_at": "2025-01-01T00:00:00Z",
            "expires_at": None,
        },
        principals=[
            {"principal_id": "principal:raanan", "role": "owner", "revoke_right": True},
            {"principal_id": "principal:yaki", "role": "member", "revoke_right": True},
        ],
        governance={
            "decision_rule": "unanimous",
            "threshold": None,
            "signatory_policy": {},
        },
        budget_policy={
            "allowed": True,
            "dimensions": [{"name": "EUR", "unit": "currency", "precision": 2}],
            "per_principal_limit": None,
        },
        activation={
            "status": "draft",
            "activated_at": None,
            "dissolved_at": None,
        },
    )


def _make_root_scope() -> Scope:
    return Scope(
        id=ROOT_SCOPE_ID,
        issued_by_scope_id=None,
        issued_by=CONTRACT_ID,
        issued_at="2025-01-01T00:00:00Z",
        expires_at=None,
        domain=Domain(
            namespace="travel",
            types=(OperationType.OBSERVE, OperationType.PROPOSE, OperationType.COMMIT),
        ),
        predicate="TOP",
        ceiling="TOP",
        delegate=True,
        revoke="principal_only",
    )


def _make_flight_scope() -> Scope:
    """Raanan's scope: flights, OBSERVE+PROPOSE+COMMIT, €1500 ceiling."""
    return Scope(
        id=FLIGHT_SCOPE_ID,
        issued_by_scope_id=ROOT_SCOPE_ID,
        issued_by="principal:raanan",
        issued_at="2025-01-01T00:00:00Z",
        expires_at=None,
        domain=Domain(
            namespace="travel.flights",
            types=(OperationType.OBSERVE, OperationType.PROPOSE, OperationType.COMMIT),
        ),
        predicate="TOP",
        ceiling="TOP",
        delegate=False,
        revoke="principal_only",
    )


def _make_hotel_scope() -> Scope:
    """Yaki's scope: accommodation, OBSERVE+PROPOSE only (no COMMIT)."""
    return Scope(
        id=HOTEL_SCOPE_ID,
        issued_by_scope_id=ROOT_SCOPE_ID,
        issued_by="principal:yaki",
        issued_at="2025-01-01T00:00:00Z",
        expires_at=None,
        domain=Domain(
            namespace="travel.accommodation",
            types=(OperationType.OBSERVE, OperationType.PROPOSE),
        ),
        predicate="TOP",
        ceiling="TOP",
        delegate=False,
        revoke="principal_only",
    )


def _setup_peer(peer: ProtocolPeer) -> None:
    """Load identical Italy trip state into a ProtocolPeer."""
    contract = _make_contract()
    peer.load_contract(contract)
    peer.load_scope(_make_root_scope())
    peer.load_scope(_make_flight_scope())
    peer.load_scope(_make_hotel_scope())
    peer.set_budget_ceiling(FLIGHT_SCOPE_ID, "EUR", "1500.00")
    peer.set_budget_ceiling(HOTEL_SCOPE_ID, "EUR", "1500.00")


# ── Tests ─────────────────────────────────────────────────────

class TestProtocolPeer(unittest.IsolatedAsyncioTestCase):
    """Integration tests: two ProtocolPeers over localhost WebSocket."""

    def setUp(self):
        self.raanan_kp = _keypair("principal:raanan")
        self.yaki_kp = _keypair("principal:yaki")
        self.raanan = ProtocolPeer("principal:raanan", self.raanan_kp)
        self.yaki = ProtocolPeer("principal:yaki", self.yaki_kp)
        _setup_peer(self.raanan)
        _setup_peer(self.yaki)

    async def _connect_peers(self, port: int) -> None:
        """Start Raanan listening and Yaki connecting."""
        await self.raanan.listen("localhost", port)
        await self.yaki.connect(f"ws://localhost:{port}")
        await asyncio.sleep(0.15)

    async def _stop_peers(self) -> None:
        await self.raanan.stop()
        await self.yaki.stop()

    # ── Test 1: Commit and receipt exchange ───────────────────

    async def test_commit_and_receipt_exchange(self):
        """
        Raanan commits a flight → success receipt reaches Yaki.
        Yaki tries to commit a hotel → TYPE_ESCALATION failure (local only).
        Raanan receives nothing from Yaki's failure.
        """
        yaki_receipts: list[tuple[str, Receipt]] = []
        raanan_receipts: list[tuple[str, Receipt]] = []
        self.yaki.on_receipt(lambda s, r: yaki_receipts.append((s, r)))
        self.raanan.on_receipt(lambda s, r: raanan_receipts.append((s, r)))

        await self._connect_peers(19001)
        try:
            # Raanan commits a flight (€450)
            flight_action = {
                "type": "COMMIT",
                "namespace": "travel.flights",
                "resource": "flight-naples",
                "params": {"destination": "Naples", "price": "450.00"},
            }
            receipt = await self.raanan.commit_action(
                FLIGHT_SCOPE_ID, CONTRACT_ID, flight_action,
                budget_amounts={"EUR": "450.00"},
            )
            self.assertEqual(receipt.outcome, "success")
            self.assertTrue(receipt.verify_hash())

            await asyncio.sleep(0.2)

            # Yaki should have received the receipt
            self.assertEqual(len(yaki_receipts), 1)
            sender_id, received_receipt = yaki_receipts[0]
            self.assertEqual(sender_id, "principal:raanan")
            self.assertTrue(received_receipt.verify_hash())
            self.assertEqual(received_receipt.receipt_hash, receipt.receipt_hash)

            # Verify it's stored in Yaki's receipt log
            stored = self.yaki.runtime.receipts.get(receipt.receipt_hash)
            self.assertIsNotNone(stored)

            # Yaki tries to commit a hotel (should fail: OBSERVE+PROPOSE only)
            hotel_action = {
                "type": "COMMIT",
                "namespace": "travel.accommodation",
                "resource": "hotel-rome",
                "params": {"city": "Rome", "price": "200.00"},
            }
            fail_receipt = await self.yaki.commit_action(
                HOTEL_SCOPE_ID, CONTRACT_ID, hotel_action,
                budget_amounts={"EUR": "200.00"},
            )
            self.assertEqual(fail_receipt.outcome, "failure")

            await asyncio.sleep(0.1)

            # Raanan should NOT have received anything (failures don't broadcast)
            self.assertEqual(len(raanan_receipts), 0)
        finally:
            await self._stop_peers()

    # ── Test 2: Tampered receipt hash rejected ────────────────

    async def test_receipt_hash_verification_rejects_tampered(self):
        """Manually sending a receipt with corrupted hash → rejected."""
        yaki_receipts: list[tuple[str, Receipt]] = []
        self.yaki.on_receipt(lambda s, r: yaki_receipts.append((s, r)))

        await self._connect_peers(19002)
        try:
            # Raanan commits a valid flight
            flight_action = {
                "type": "COMMIT",
                "namespace": "travel.flights",
                "resource": "flight-naples",
                "params": {"destination": "Naples", "price": "450.00"},
            }
            receipt = await self.raanan.commit_action(
                FLIGHT_SCOPE_ID, CONTRACT_ID, flight_action,
                budget_amounts={"EUR": "450.00"},
            )
            self.assertEqual(receipt.outcome, "success")

            await asyncio.sleep(0.2)
            # Yaki got the valid receipt
            self.assertEqual(len(yaki_receipts), 1)

            # Now manually send a tampered receipt (corrupt the hash)
            receipt_dict = receipt.to_dict()
            receipt_dict["receipt_hash"] = "a" * 64  # corrupted hash
            payload = {"type": "receipt", "receipt": receipt_dict}

            sent = await self.raanan.peer.send("principal:yaki", payload)
            self.assertTrue(sent)

            await asyncio.sleep(0.2)

            # Yaki should still have only 1 receipt (the tampered one was rejected)
            self.assertEqual(len(yaki_receipts), 1)
        finally:
            await self._stop_peers()

    # ── Test 3: Budget enforcement over wire ──────────────────

    async def test_budget_enforcement_over_wire(self):
        """
        Raanan commits flight #1 (€1200) → success receipt reaches Yaki.
        Raanan commits flight #2 (€500) → BUDGET_EXCEEDED failure (local).
        """
        yaki_receipts: list[tuple[str, Receipt]] = []
        self.yaki.on_receipt(lambda s, r: yaki_receipts.append((s, r)))

        await self._connect_peers(19003)
        try:
            # Flight #1: €1200 (within €1500 ceiling)
            action1 = {
                "type": "COMMIT",
                "namespace": "travel.flights",
                "resource": "flight-rome",
                "params": {"destination": "Rome", "price": "1200.00"},
            }
            r1 = await self.raanan.commit_action(
                FLIGHT_SCOPE_ID, CONTRACT_ID, action1,
                budget_amounts={"EUR": "1200.00"},
            )
            self.assertEqual(r1.outcome, "success")

            await asyncio.sleep(0.2)
            self.assertEqual(len(yaki_receipts), 1)

            # Flight #2: €500 (would total €1700, exceeds €1500 ceiling)
            action2 = {
                "type": "COMMIT",
                "namespace": "travel.flights",
                "resource": "flight-naples",
                "params": {"destination": "Naples", "price": "500.00"},
            }
            r2 = await self.raanan.commit_action(
                FLIGHT_SCOPE_ID, CONTRACT_ID, action2,
                budget_amounts={"EUR": "500.00"},
            )
            self.assertEqual(r2.outcome, "failure")

            await asyncio.sleep(0.1)
            # Only the first receipt reached Yaki
            self.assertEqual(len(yaki_receipts), 1)
        finally:
            await self._stop_peers()

    # ── Test 4: Scope hash mismatch rejects receipt ───────────

    async def test_scope_hash_mismatch_rejects_receipt(self):
        """
        Manually send a receipt where scope_hash doesn't match Yaki's
        local scope → Yaki's on_receipt handler is never called.
        """
        yaki_receipts: list[tuple[str, Receipt]] = []
        self.yaki.on_receipt(lambda s, r: yaki_receipts.append((s, r)))

        await self._connect_peers(19004)
        try:
            # Raanan commits a valid flight
            flight_action = {
                "type": "COMMIT",
                "namespace": "travel.flights",
                "resource": "flight-naples",
                "params": {"destination": "Naples", "price": "450.00"},
            }
            receipt = await self.raanan.commit_action(
                FLIGHT_SCOPE_ID, CONTRACT_ID, flight_action,
                budget_amounts={"EUR": "450.00"},
            )
            self.assertEqual(receipt.outcome, "success")

            await asyncio.sleep(0.2)
            # Yaki got the valid receipt
            self.assertEqual(len(yaki_receipts), 1)

            # Now craft a receipt with a mismatched scope_hash.
            # We rebuild a receipt with a fake scope_hash, then seal it
            # so its own receipt_hash is internally consistent — but the
            # scope_hash won't match Yaki's local scope.
            from vincul.receipts import commitment_receipt
            tampered_receipt = commitment_receipt(
                initiated_by="principal:raanan",
                scope_id=FLIGHT_SCOPE_ID,
                scope_hash="b" * 64,  # fake scope hash
                contract_id=CONTRACT_ID,
                contract_hash=receipt.contract_hash,
                namespace="travel.flights",
                resource="flight-milan",
                params={"destination": "Milan", "price": "300.00"},
                reversible=False,
                revert_window=None,
                external_ref=None,
            )

            payload = {"type": "receipt", "receipt": tampered_receipt.to_dict()}
            sent = await self.raanan.peer.send("principal:yaki", payload)
            self.assertTrue(sent)

            await asyncio.sleep(0.2)

            # Yaki should still have only 1 receipt (scope_hash mismatch)
            self.assertEqual(len(yaki_receipts), 1)
        finally:
            await self._stop_peers()


    # ── Test 5: Contract hash mismatch rejects receipt ────────

    async def test_contract_hash_mismatch_rejects_receipt(self):
        """
        Manually send a receipt where contract_hash doesn't match Yaki's
        local contract → Yaki's on_receipt handler is never called.
        """
        yaki_receipts: list[tuple[str, Receipt]] = []
        self.yaki.on_receipt(lambda s, r: yaki_receipts.append((s, r)))

        await self._connect_peers(19005)
        try:
            # Raanan commits a valid flight
            flight_action = {
                "type": "COMMIT",
                "namespace": "travel.flights",
                "resource": "flight-naples",
                "params": {"destination": "Naples", "price": "450.00"},
            }
            receipt = await self.raanan.commit_action(
                FLIGHT_SCOPE_ID, CONTRACT_ID, flight_action,
                budget_amounts={"EUR": "450.00"},
            )
            self.assertEqual(receipt.outcome, "success")

            await asyncio.sleep(0.2)
            self.assertEqual(len(yaki_receipts), 1)

            # Craft a receipt with a mismatched contract_hash
            from vincul.receipts import commitment_receipt
            tampered_receipt = commitment_receipt(
                initiated_by="principal:raanan",
                scope_id=FLIGHT_SCOPE_ID,
                scope_hash=receipt.scope_hash,
                contract_id=CONTRACT_ID,
                contract_hash="c" * 64,  # fake contract hash
                namespace="travel.flights",
                resource="flight-milan",
                params={"destination": "Milan", "price": "300.00"},
                reversible=False,
                revert_window=None,
                external_ref=None,
            )

            payload = {"type": "receipt", "receipt": tampered_receipt.to_dict()}
            sent = await self.raanan.peer.send("principal:yaki", payload)
            self.assertTrue(sent)

            await asyncio.sleep(0.2)

            # Yaki should still have only 1 receipt (contract_hash mismatch)
            self.assertEqual(len(yaki_receipts), 1)
        finally:
            await self._stop_peers()


if __name__ == "__main__":
    unittest.main()
