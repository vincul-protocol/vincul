"""
tests/test_transport.py — VinculNet transport layer test suite (unittest)

Phase 1: envelope, handshake, registry (no networking)
Phase 2: integration tests with VinculPeer over WebSocket
"""
import asyncio
import base64
import unittest


from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from vincul.identity import KeyPair
from vincul.hashing import domain_hash
from vincul.transport.envelope import (
    MessageEnvelope,
    sign_envelope,
    verify_envelope,
    ENVELOPE_DOMAIN_TAG,
)
from vincul.transport.handshake import (
    HelloMessage,
    sign_hello,
    verify_hello,
    b64_to_pubkey,
)
from vincul.transport.registry import PeerRegistry


# ── Test helpers ─────────────────────────────────────────────

def _keypair(principal_id: str = "principal:alice") -> KeyPair:
    return KeyPair.generate(principal_id)


# ── TestEnvelope ─────────────────────────────────────────────

class TestEnvelope(unittest.TestCase):
    """Tests for MessageEnvelope sign/verify."""

    def setUp(self):
        self.alice = _keypair("principal:alice")
        self.bob = _keypair("principal:bob")
        self.payload = {"action": "propose", "item": "flight", "cost": 450}

    def test_sign_verify_roundtrip(self):
        """A signed envelope verifies with the correct public key."""
        env = sign_envelope(
            self.payload, self.alice.principal_id,
            self.alice, self.bob.principal_id,
        )
        self.assertTrue(verify_envelope(env, self.alice.public_key))

    def test_envelope_fields_populated(self):
        """All envelope fields are set after signing."""
        env = sign_envelope(
            self.payload, self.alice.principal_id,
            self.alice, self.bob.principal_id,
        )
        self.assertEqual(env.sender_id, "principal:alice")
        self.assertEqual(env.recipient_id, "principal:bob")
        self.assertEqual(env.envelope_version, "1.0")
        self.assertIsInstance(env.payload, bytes)
        self.assertEqual(len(env.payload_hash), 64)  # SHA-256 hex
        self.assertIn("T", env.timestamp)
        self.assertIn("-", env.message_id)  # UUID format
        self.assertIsInstance(env.signature, str)

    def test_verify_fails_with_wrong_pubkey(self):
        """Verification fails if we use the wrong public key."""
        env = sign_envelope(
            self.payload, self.alice.principal_id,
            self.alice, self.bob.principal_id,
        )
        self.assertFalse(verify_envelope(env, self.bob.public_key))

    def test_verify_fails_on_payload_tampering(self):
        """Modifying the payload invalidates the envelope."""
        env = sign_envelope(
            self.payload, self.alice.principal_id,
            self.alice, self.bob.principal_id,
        )
        # Tamper with payload bytes
        tampered = MessageEnvelope(
            envelope_version=env.envelope_version,
            sender_id=env.sender_id,
            recipient_id=env.recipient_id,
            payload=b'{"action":"TAMPERED"}',
            payload_hash=env.payload_hash,  # hash no longer matches
            timestamp=env.timestamp,
            message_id=env.message_id,
            signature=env.signature,
        )
        self.assertFalse(verify_envelope(tampered, self.alice.public_key))

    def test_verify_fails_on_sender_id_spoofing(self):
        """Changing sender_id after signing invalidates the envelope."""
        env = sign_envelope(
            self.payload, self.alice.principal_id,
            self.alice, self.bob.principal_id,
        )
        spoofed = MessageEnvelope(
            envelope_version=env.envelope_version,
            sender_id="principal:eve",  # spoofed
            recipient_id=env.recipient_id,
            payload=env.payload,
            payload_hash=env.payload_hash,
            timestamp=env.timestamp,
            message_id=env.message_id,
            signature=env.signature,
        )
        self.assertFalse(verify_envelope(spoofed, self.alice.public_key))

    def test_verify_fails_on_signature_tampering(self):
        """Corrupting the signature invalidates the envelope."""
        env = sign_envelope(
            self.payload, self.alice.principal_id,
            self.alice, self.bob.principal_id,
        )
        # Flip a byte in the signature
        sig_bytes = base64.urlsafe_b64decode(env.signature)
        tampered_sig = bytes([sig_bytes[0] ^ 0xFF]) + sig_bytes[1:]
        tampered = MessageEnvelope(
            envelope_version=env.envelope_version,
            sender_id=env.sender_id,
            recipient_id=env.recipient_id,
            payload=env.payload,
            payload_hash=env.payload_hash,
            timestamp=env.timestamp,
            message_id=env.message_id,
            signature=base64.urlsafe_b64encode(tampered_sig).decode("ascii"),
        )
        self.assertFalse(verify_envelope(tampered, self.alice.public_key))

    def test_to_dict_from_dict_roundtrip(self):
        """Envelope survives serialization/deserialization."""
        env = sign_envelope(
            self.payload, self.alice.principal_id,
            self.alice, self.bob.principal_id,
        )
        d = env.to_dict()
        restored = MessageEnvelope.from_dict(d)
        self.assertTrue(verify_envelope(restored, self.alice.public_key))
        self.assertEqual(env.sender_id, restored.sender_id)
        self.assertEqual(env.payload, restored.payload)
        self.assertEqual(env.payload_hash, restored.payload_hash)

    def test_different_payloads_different_hashes(self):
        """Different payloads produce different hashes."""
        env1 = sign_envelope(
            {"a": 1}, self.alice.principal_id,
            self.alice, self.bob.principal_id,
        )
        env2 = sign_envelope(
            {"a": 2}, self.alice.principal_id,
            self.alice, self.bob.principal_id,
        )
        self.assertNotEqual(env1.payload_hash, env2.payload_hash)

    def test_domain_hash_deterministic(self):
        """Same input produces same hash."""
        h1 = domain_hash(ENVELOPE_DOMAIN_TAG, b"test")
        h2 = domain_hash(ENVELOPE_DOMAIN_TAG, b"test")
        self.assertEqual(h1, h2)
        self.assertEqual(len(h1), 64)

    def test_domain_hash_domain_separation(self):
        """Different tags produce different hashes for same data."""
        h1 = domain_hash(b"TAG_A\x00", b"test")
        h2 = domain_hash(b"TAG_B\x00", b"test")
        self.assertNotEqual(h1, h2)


# ── TestHandshake ────────────────────────────────────────────

class TestHandshake(unittest.TestCase):
    """Tests for HelloMessage sign/verify."""

    def setUp(self):
        self.alice = _keypair("principal:alice")
        self.bob = _keypair("principal:bob")

    def test_sign_verify_roundtrip(self):
        """A signed hello verifies successfully."""
        hello = sign_hello(self.alice.principal_id, self.alice)
        self.assertTrue(verify_hello(hello))

    def test_hello_fields_populated(self):
        """All hello fields are set after signing."""
        hello = sign_hello(self.alice.principal_id, self.alice)
        self.assertEqual(hello.sender_id, "principal:alice")
        self.assertIsInstance(hello.sender_pubkey, str)
        self.assertIn("T", hello.timestamp)
        self.assertIsInstance(hello.signature, str)

    def test_pubkey_matches_private_key(self):
        """The pubkey in the hello matches the signing key."""
        hello = sign_hello(self.alice.principal_id, self.alice)
        recovered = b64_to_pubkey(hello.sender_pubkey)
        # Compare raw bytes
        expected = self.alice.public_key_bytes()
        actual = recovered.public_bytes(Encoding.Raw, PublicFormat.Raw)
        self.assertEqual(expected, actual)

    def test_verify_fails_on_signature_tampering(self):
        """Corrupting the signature invalidates the hello."""
        hello = sign_hello(self.alice.principal_id, self.alice)
        sig_bytes = base64.urlsafe_b64decode(hello.signature)
        tampered_sig = bytes([sig_bytes[0] ^ 0xFF]) + sig_bytes[1:]
        tampered = HelloMessage(
            sender_id=hello.sender_id,
            sender_pubkey=hello.sender_pubkey,
            timestamp=hello.timestamp,
            signature=base64.urlsafe_b64encode(tampered_sig).decode("ascii"),
        )
        self.assertFalse(verify_hello(tampered))

    def test_verify_fails_on_sender_id_tampering(self):
        """Changing sender_id after signing invalidates the hello."""
        hello = sign_hello(self.alice.principal_id, self.alice)
        tampered = HelloMessage(
            sender_id="principal:eve",  # tampered
            sender_pubkey=hello.sender_pubkey,
            timestamp=hello.timestamp,
            signature=hello.signature,
        )
        self.assertFalse(verify_hello(tampered))

    def test_verify_fails_on_pubkey_mismatch(self):
        """Swapping pubkey invalidates the hello (signature won't verify)."""
        hello = sign_hello(self.alice.principal_id, self.alice)
        tampered = HelloMessage(
            sender_id=hello.sender_id,
            sender_pubkey=self.bob.public_key_b64(),  # wrong pubkey
            timestamp=hello.timestamp,
            signature=hello.signature,
        )
        self.assertFalse(verify_hello(tampered))

    def test_to_dict_from_dict_roundtrip(self):
        """Hello survives serialization/deserialization."""
        hello = sign_hello(self.alice.principal_id, self.alice)
        d = hello.to_dict()
        self.assertEqual(d["type"], "hello")
        restored = HelloMessage.from_dict(d)
        self.assertTrue(verify_hello(restored))

    def test_mutual_handshake(self):
        """Both sides can sign and verify each other's hello."""
        hello_a = sign_hello(self.alice.principal_id, self.alice)
        hello_b = sign_hello(self.bob.principal_id, self.bob)
        self.assertTrue(verify_hello(hello_a))
        self.assertTrue(verify_hello(hello_b))
        self.assertNotEqual(hello_a.sender_id, hello_b.sender_id)


# ── TestPeerRegistry ─────────────────────────────────────────

class TestPeerRegistry(unittest.TestCase):
    """Tests for PeerRegistry."""

    def setUp(self):
        self.registry = PeerRegistry()
        self.alice = _keypair("principal:alice")
        self.bob = _keypair("principal:bob")

    def test_register_and_get_pubkey(self):
        """Registered peer's pubkey is retrievable."""
        self.registry.register("principal:alice", self.alice.public_key)
        self.assertEqual(
            self.registry.get_pubkey("principal:alice"),
            self.alice.public_key,
        )

    def test_get_pubkey_unknown_returns_none(self):
        """Unknown peer returns None."""
        self.assertIsNone(self.registry.get_pubkey("principal:unknown"))

    def test_register_with_connection(self):
        """Connection is stored and retrievable."""
        mock_ws = object()
        self.registry.register("principal:alice", self.alice.public_key, mock_ws)
        self.assertIs(self.registry.get_connection("principal:alice"), mock_ws)

    def test_get_connection_unknown_returns_none(self):
        """Unknown peer's connection returns None."""
        self.assertIsNone(self.registry.get_connection("principal:unknown"))

    def test_is_known(self):
        """is_known returns True for registered peers."""
        self.assertFalse(self.registry.is_known("principal:alice"))
        self.registry.register("principal:alice", self.alice.public_key)
        self.assertTrue(self.registry.is_known("principal:alice"))

    def test_remove(self):
        """Removed peer is no longer known."""
        self.registry.register("principal:alice", self.alice.public_key)
        self.assertTrue(self.registry.remove("principal:alice"))
        self.assertFalse(self.registry.is_known("principal:alice"))

    def test_remove_unknown_returns_false(self):
        """Removing unknown peer returns False."""
        self.assertFalse(self.registry.remove("principal:unknown"))

    def test_all_peers(self):
        """all_peers returns all registered principal_ids."""
        self.assertEqual(self.registry.all_peers(), [])
        self.registry.register("principal:alice", self.alice.public_key)
        self.registry.register("principal:bob", self.bob.public_key)
        self.assertCountEqual(
            self.registry.all_peers(),
            ["principal:alice", "principal:bob"],
        )

    def test_rejects_pubkey_change(self):
        """Re-registering with a different pubkey is rejected."""
        mock_ws1 = object()
        mock_ws2 = object()
        self.assertTrue(self.registry.register("principal:alice", self.alice.public_key, mock_ws1))
        self.assertFalse(self.registry.register("principal:alice", self.bob.public_key, mock_ws2))
        # Original pubkey and connection are unchanged
        self.assertEqual(self.registry.get_pubkey("principal:alice"), self.alice.public_key)
        self.assertIs(self.registry.get_connection("principal:alice"), mock_ws1)

    def test_allows_reconnection_same_pubkey(self):
        """Re-registering with the same pubkey but new connection is allowed."""
        mock_ws1 = object()
        mock_ws2 = object()
        self.assertTrue(self.registry.register("principal:alice", self.alice.public_key, mock_ws1))
        self.assertTrue(self.registry.register("principal:alice", self.alice.public_key, mock_ws2))
        # Connection updated, pubkey unchanged
        self.assertEqual(self.registry.get_pubkey("principal:alice"), self.alice.public_key)
        self.assertIs(self.registry.get_connection("principal:alice"), mock_ws2)


# ── TestKeyPersistence ───────────────────────────────────────

class TestKeyPersistence(unittest.TestCase):
    """Tests for key persistence (load_or_create_keypair)."""

    def setUp(self):
        import tempfile
        self.tmpdir = tempfile.mkdtemp()
        self.key_dir = __import__("pathlib").Path(self.tmpdir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir)

    def test_creates_new_keypair(self):
        """First call generates a new keypair and saves it."""
        from vincul.transport.keys import load_or_create_keypair
        kp = load_or_create_keypair("principal:test", key_dir=self.key_dir)
        self.assertEqual(kp.principal_id, "principal:test")
        self.assertTrue((self.key_dir / "principal:test.key").exists())

    def test_loads_existing_keypair(self):
        """Second call loads the same keypair."""
        from vincul.transport.keys import load_or_create_keypair
        kp1 = load_or_create_keypair("principal:test", key_dir=self.key_dir)
        kp2 = load_or_create_keypair("principal:test", key_dir=self.key_dir)
        self.assertEqual(kp1.public_key_bytes(), kp2.public_key_bytes())

    def test_different_principals_different_keys(self):
        """Different principals get different keypairs."""
        from vincul.transport.keys import load_or_create_keypair
        kp1 = load_or_create_keypair("principal:alice", key_dir=self.key_dir)
        kp2 = load_or_create_keypair("principal:bob", key_dir=self.key_dir)
        self.assertNotEqual(kp1.public_key_bytes(), kp2.public_key_bytes())

    def test_key_file_permissions(self):
        """Key file has restricted permissions (owner-only)."""
        import os, stat
        from vincul.transport.keys import load_or_create_keypair
        load_or_create_keypair("principal:test", key_dir=self.key_dir)
        key_path = self.key_dir / "principal:test.key"
        mode = os.stat(key_path).st_mode
        # Owner read/write only (0o600)
        self.assertEqual(stat.S_IMODE(mode), 0o600)


# ── TestVinculPeerIntegration ────────────────────────────────

class TestVinculPeerIntegration(unittest.IsolatedAsyncioTestCase):
    """Integration tests: two VinculPeer instances over real WebSocket."""

    def setUp(self):
        self.alice = _keypair("principal:alice")
        self.bob = _keypair("principal:bob")

    async def test_handshake_and_message_roundtrip(self):
        """Two peers can handshake and exchange a signed message."""
        from vincul.transport.peer import VinculPeer

        peer_a = VinculPeer("principal:alice", self.alice)
        peer_b = VinculPeer("principal:bob", self.bob)

        received = []
        peer_a.on_message(lambda sender, payload: received.append(("a_got", sender, payload)))
        peer_b.on_message(lambda sender, payload: received.append(("b_got", sender, payload)))

        # Start server
        await peer_a.listen("localhost", 18765)

        try:
            # Connect
            peer_id = await peer_b.connect("ws://localhost:18765")
            self.assertEqual(peer_id, "principal:alice")

            # Wait for handshake to settle
            await asyncio.sleep(0.1)

            # Bob sends to Alice
            sent = await peer_b.send("principal:alice", {"msg": "hello from bob"})
            self.assertTrue(sent)

            await asyncio.sleep(0.1)
            self.assertEqual(len(received), 1)
            self.assertEqual(received[0], ("a_got", "principal:bob", {"msg": "hello from bob"}))

            # Alice sends to Bob
            sent = await peer_a.send("principal:bob", {"msg": "hello from alice"})
            self.assertTrue(sent)

            await asyncio.sleep(0.1)
            self.assertEqual(len(received), 2)
            self.assertEqual(received[1], ("b_got", "principal:alice", {"msg": "hello from alice"}))
        finally:
            await peer_a.stop()

    async def test_send_to_unknown_peer_fails(self):
        """Sending to an unregistered peer returns False."""
        from vincul.transport.peer import VinculPeer

        peer_a = VinculPeer("principal:alice", self.alice)
        result = await peer_a.send("principal:unknown", {"msg": "test"})
        self.assertFalse(result)

    async def test_mutual_registry_after_handshake(self):
        """After handshake, both peers know each other."""
        from vincul.transport.peer import VinculPeer

        peer_a = VinculPeer("principal:alice", self.alice)
        peer_b = VinculPeer("principal:bob", self.bob)

        await peer_a.listen("localhost", 18766)

        try:
            await peer_b.connect("ws://localhost:18766")
            await asyncio.sleep(0.1)

            # Both peers should know each other
            self.assertTrue(peer_b.registry.is_known("principal:alice"))
            self.assertTrue(peer_a.registry.is_known("principal:bob"))
        finally:
            await peer_a.stop()


    async def test_tampered_message_rejected_over_websocket(self):
        """A tampered message sent over WebSocket is silently dropped."""
        import json
        from vincul.transport.peer import VinculPeer
        from vincul.transport.envelope import sign_envelope

        peer_a = VinculPeer("principal:alice", self.alice)
        peer_b = VinculPeer("principal:bob", self.bob)

        received = []
        peer_a.on_message(lambda sender, payload: received.append(payload))

        await peer_a.listen("localhost", 18767)

        try:
            peer_id = await peer_b.connect("ws://localhost:18767")
            await asyncio.sleep(0.1)

            # Bob creates a valid envelope, then tampers with it
            envelope = sign_envelope(
                {"msg": "legit"}, "principal:bob",
                self.bob, "principal:alice",
            )
            d = envelope.to_dict()
            # Tamper: change the payload content (hash won't match)
            import base64 as b64mod
            d["payload"] = b64mod.urlsafe_b64encode(b'{"msg":"TAMPERED"}').decode("ascii")

            # Send raw tampered JSON over Bob's connection to Alice
            ws = peer_b.registry.get_connection("principal:alice")
            await ws.send(json.dumps(d))

            await asyncio.sleep(0.1)
            # Alice should NOT have received it
            self.assertEqual(len(received), 0)
        finally:
            await peer_a.stop()

    async def test_spoofed_sender_rejected_over_websocket(self):
        """A message with mismatched sender_id is rejected over WebSocket."""
        import json
        from vincul.transport.peer import VinculPeer
        from vincul.transport.envelope import sign_envelope

        eve = _keypair("principal:eve")

        peer_a = VinculPeer("principal:alice", self.alice)
        peer_b = VinculPeer("principal:bob", self.bob)

        received = []
        peer_a.on_message(lambda sender, payload: received.append(payload))

        await peer_a.listen("localhost", 18768)

        try:
            peer_id = await peer_b.connect("ws://localhost:18768")
            await asyncio.sleep(0.1)

            # Eve signs a message but Bob sends it (sender_id = "principal:eve")
            envelope = sign_envelope(
                {"msg": "spoofed"}, "principal:eve",
                eve, "principal:alice",
            )
            d = envelope.to_dict()

            # Send over Bob's connection (Alice expects sender_id="principal:bob")
            ws = peer_b.registry.get_connection("principal:alice")
            await ws.send(json.dumps(d))

            await asyncio.sleep(0.1)
            # Alice should reject (sender_id mismatch with session)
            self.assertEqual(len(received), 0)
        finally:
            await peer_a.stop()


    async def test_symmetric_both_peers_listen_on_different_ports(self):
        """Both peers listen on their own port and connect to each other."""
        from vincul.transport.peer import VinculPeer

        peer_a = VinculPeer("principal:alice", self.alice)
        peer_b = VinculPeer("principal:bob", self.bob)

        received = []
        peer_a.on_message(lambda sender, payload: received.append(("a_got", sender, payload)))
        peer_b.on_message(lambda sender, payload: received.append(("b_got", sender, payload)))

        # Both peers listen on different ports
        await peer_a.listen("localhost", 18769)
        await peer_b.listen("localhost", 18770)

        try:
            # Each connects to the other
            a_peer = await peer_a.connect("ws://localhost:18770")
            b_peer = await peer_b.connect("ws://localhost:18769")
            await asyncio.sleep(0.1)

            self.assertEqual(a_peer, "principal:bob")
            self.assertEqual(b_peer, "principal:alice")

            # Both should know each other
            self.assertTrue(peer_a.registry.is_known("principal:bob"))
            self.assertTrue(peer_b.registry.is_known("principal:alice"))

            # Alice sends to Bob (over Alice's outbound connection)
            sent = await peer_a.send("principal:bob", {"msg": "from alice"})
            self.assertTrue(sent)

            await asyncio.sleep(0.1)
            self.assertEqual(len(received), 1)
            self.assertEqual(received[0], ("b_got", "principal:alice", {"msg": "from alice"}))

            # Bob sends to Alice (over Bob's outbound connection)
            sent = await peer_b.send("principal:alice", {"msg": "from bob"})
            self.assertTrue(sent)

            await asyncio.sleep(0.1)
            self.assertEqual(len(received), 2)
            self.assertEqual(received[1], ("a_got", "principal:bob", {"msg": "from bob"}))
        finally:
            await peer_a.stop()
            await peer_b.stop()


if __name__ == "__main__":
    unittest.main()
