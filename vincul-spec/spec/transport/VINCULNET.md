# VinculNet — Transport Layer Specification
`spec/transport/VINCULNET.md` · Stage 1

---

## Purpose

VinculNet is the authenticated peer-to-peer transport layer for the Vincul Protocol. It enables agents to discover, authenticate, and communicate over WebSocket with signed, verified messages.

Stage 1 covers: identity binding, mutual handshake, signed message envelopes, and session-bound peer verification.

---

## 1. Message Envelope

### 1.1 Schema

A `MessageEnvelope` carries a signed payload between two peers:

| Field | Type | Description |
|---|---|---|
| `envelope_version` | string | Protocol version (`"1.0"`) |
| `sender_id` | string | Principal ID of the sender |
| `recipient_id` | string | Principal ID of the recipient |
| `payload` | bytes | JCS-serialized payload (base64url on wire) |
| `payload_hash` | string | SHA-256 hex hash of `VINCULNET_ENVELOPE_V1\x00 ‖ payload` |
| `timestamp` | string | ISO 8601 UTC (`"2026-01-01T00:00:00Z"`) |
| `message_id` | string | UUID v4 |
| `signature` | string | Base64url Ed25519 signature |

### 1.2 Signing Procedure

1. Serialize payload dict to bytes via JCS (RFC 8785)
2. Compute `payload_hash = SHA-256(VINCULNET_ENVELOPE_V1\x00 ‖ payload_bytes)`
3. Construct `sign_dict`:
   ```json
   {
     "envelope_version": "1.0",
     "sender_id": "principal:alice",
     "recipient_id": "principal:bob",
     "payload_hash": "<64-char hex>",
     "timestamp": "<ISO 8601>",
     "message_id": "<UUID>"
   }
   ```
4. Compute `sign_bytes = VINCULNET_ENVELOPE_V1\x00 ‖ JCS(sign_dict)`
5. Sign `sign_bytes` with Ed25519 private key
6. Base64url-encode the 64-byte signature

### 1.3 Verification Procedure

1. Recompute `payload_hash` from `envelope.payload`
2. Compare with `envelope.payload_hash` — reject if mismatch
3. Reconstruct `sign_dict` from envelope fields
4. Compute `sign_bytes` as in §1.2
5. Verify signature against session-bound public key — reject if invalid

### 1.4 Security

- `sender_pubkey` is NOT included in the envelope
- Public key binding is established during handshake (§2)
- Envelopes with mismatched `sender_id` are rejected

---

## 2. Handshake (HELLO)

### 2.1 Schema

A `HelloMessage` is exchanged once per connection to establish mutual identity:

| Field | Type | Description |
|---|---|---|
| `type` | string | Always `"hello"` (for message dispatch, see §6) |
| `sender_id` | string | Principal ID |
| `sender_pubkey` | string | Base64url Ed25519 public key (32 bytes) |
| `timestamp` | string | ISO 8601 UTC |
| `signature` | string | Base64url Ed25519 signature |

The `type` field is included in the wire format but excluded from `sign_dict` (not signed).

### 2.2 Signing Procedure

1. Construct `sign_dict`:
   ```json
   {
     "sender_id": "principal:alice",
     "sender_pubkey": "<base64url>",
     "timestamp": "<ISO 8601>"
   }
   ```
2. Compute `sign_bytes = VINCULNET_HELLO_V1\x00 ‖ JCS(sign_dict)`
3. Sign with Ed25519, base64url-encode

### 2.3 Verification

1. Decode `sender_pubkey` from base64url
2. Reconstruct `sign_dict`
3. Verify signature using the decoded public key

### 2.4 Handshake Flow

```
Initiator (client)              Acceptor (server)
─────────────────              ─────────────────
    ──── HELLO ────►
                               Verify HELLO
                               Store: sender_id → pubkey
    ◄──── HELLO ────
Verify HELLO
Store: sender_id → pubkey
```

Both sides are now authenticated. Subsequent messages use signed envelopes (§1).

### 2.5 Trust Model

Stage 1 uses **TOFU** (trust-on-first-use). The first HELLO from a peer establishes the binding. Public key changes mid-session are rejected.

---

## 3. Peer Registry

In-memory map of authenticated peers:

```
principal_id → { pubkey: Ed25519PublicKey, connection: WebSocket }
```

- Populated after successful handshake
- Consulted for envelope verification (pubkey lookup) and message sending (connection lookup)
- Peer is removed on connection close
- **Reconnection** (same principal_id, same pubkey, new connection) is allowed — the connection is updated
- **Pubkey change** (same principal_id, different pubkey) is rejected — this enforces the "no mid-session key changes" rule (§4.5)

---

## 4. Security Rules

1. **Never sign raw string concatenations.** Always construct a dict, canonicalize, then sign.
2. **Domain separation.** All signing and hashing uses domain tags (`VINCULNET_ENVELOPE_V1\x00`, `VINCULNET_HELLO_V1\x00`).
3. **Fail closed.** Any verification failure results in message rejection.
4. **Session binding.** `sender_id` in envelopes must match the peer authenticated during handshake.
5. **No mid-session key changes.** A new pubkey from an established peer is rejected.

---

## 5. Domain Tags

| Tag | Usage |
|---|---|
| `VINCULNET_ENVELOPE_V1\x00` | Envelope payload hashing and sign_dict signing |
| `VINCULNET_HELLO_V1\x00` | Handshake sign_dict signing |

These tags are separate from protocol-layer tags (`PACT_*`). See `spec/crypto/HASHING.md §4.0.1`.

---

## 6. Payload Convention

The envelope `payload` is opaque bytes at the transport layer. However, all VinculNet payloads SHOULD be JSON objects that include a `"type"` field for dispatch:

```json
{"type": "proposal", "item": "flight", "cost": 450}
```

The `HelloMessage` already uses `"type": "hello"` in its wire format. Stage 2+ will define specific payload types (e.g., `"action"`, `"receipt"`, `"proposal"`). Receivers MAY reject payloads without a `"type"` field.

---

## 7. Constraints (Stage 1)

- No encryption (plaintext transport)
- No PKI or certificate authorities
- No relay or discovery
- No delivery guarantees
- TOFU trust model
- WebSocket transport only

---
`CC0 1.0 Universal — No rights reserved.`
