# Vincul SDK — Boundary Document
`SDK_BOUNDARY.md` · v0.2

---

## 1. Purpose

This document defines what is **normative interop** (must be implemented by any conformant SDK) versus **reference implementation** (provided for convenience, replaceable). Third-party implementations use this document to determine compatibility requirements.

---

## 2. The SDK Is Artifact-First

The center of gravity of the Vincul SDK is its **artifacts** — the immutable, hashable, verifiable data structures that flow between participants. These artifacts are the protocol. Everything else is plumbing.

### 2.1 Normative Artifacts

A conformant Vincul SDK **MUST** be able to produce, consume, hash, and verify the following artifacts:

| Artifact | Spec Reference | Domain Tag |
|---|---|---|
| **Coalition Contract** | `spec/contract/COALITION.md` | `PACT_CONTRACT_V1\x00` |
| **Scope** | `spec/scope/SCHEMA.md` | `PACT_SCOPE_V1\x00` |
| **Receipt** (all 8 kinds) | `spec/receipts/RECEIPT.md` | `PACT_RECEIPT_V1\x00` |
| **Constraint Expression** | `spec/dsl/CONSTRAINT.md` | `PACT_CONSTRAINT_V1\x00` |
| **Compliance Profile** | `spec/implementation/COMPLIANCE_PROFILES.md` | `PACT_PROFILE_V1\x00` |

Grants and attestations are Receipt kinds (`delegation` and `attestation` respectively), not separate artifact types.

### 2.2 Normative Operations on Artifacts

| Operation | Requirement |
|---|---|
| **JCS Canonicalization** (RFC 8785) | MUST produce identical bytes for identical logical objects |
| **Domain-prefixed SHA-256 hashing** | MUST match `spec/crypto/HASHING.md` test vectors (13 vectors, CI-gated) |
| **Ed25519 signing and verification** | MUST use the sign/verify procedure from the spec |
| **Seal** | Every artifact MUST be hashable and its `descriptor_hash` deterministic |
| **7-step validation pipeline** | MUST enforce steps in order per `spec/scope/SCHEMA.md` and `spec/receipts/FAILURE_CODES.md` semantics; first failure wins |
| **Revocation cascade** | MUST propagate revocation to all DAG descendants; fail-closed |

### 2.3 Normative Invariants (Non-Negotiable)

These invariants define protocol conformance. Violating any one makes an implementation non-Vincul:

1. **Contract is the root of authority** — identity carries no authority outside a contract boundary
2. **Fail-closed** — missing, expired, revoked, or unresolvable state MUST deny access
3. **Receipt symmetry** — all parties see the same receipt for the same action
4. **Append-only audit** — receipts are immutable once issued; the log is append-only
5. **Explicit delegation** — `delegate=false` is the default; delegation is never implied
6. **Contiguous type sets** — operation types must form a prefix of `(OBSERVE, PROPOSE, COMMIT)`
7. **Revocation cascades** — revoking a parent revokes all descendants
8. **Domain-separated hashing** — each artifact type uses a distinct domain prefix
9. **Validation order is locked** — the 7-step pipeline executes in fixed order

---

## 3. Transport Is Pluggable

### 3.1 What Is Normative About Transport

Only the **wire format of artifacts** is normative:

| Normative | Non-Normative |
|---|---|
| `MessageEnvelope` schema (sender, recipient, payload, payload_hash, signature) | WebSocket as the carrier protocol |
| `HelloMessage` handshake schema | Connection management, reconnection |
| JCS serialization of payloads | Peer discovery mechanism |
| Ed25519 envelope signing/verification | NAT traversal, TLS configuration |
| Domain-tagged payload hashing (`VINCULNET_ENVELOPE_V1\x00`) | Session state, keepalives |

### 3.2 What This Means for Implementors

A conformant transport implementation MUST:
- Serialize payloads as JCS bytes
- Sign envelopes per `spec/transport/VINCULNET.md` signing procedure
- Verify envelope signatures before processing; reject on failure (fail-closed)
- Complete the `HelloMessage` handshake before exchanging envelopes

A conformant transport implementation MAY:
- Use any carrier protocol (WebSocket, gRPC, QUIC, libp2p, HTTP long-poll, Unix socket)
- Implement any peer discovery mechanism (static config, mDNS, DHT, registry service)
- Use any trust model beyond TOFU (PKI, DID resolution, web-of-trust)
- Add encryption layers (TLS, Noise protocol) as long as the envelope format is preserved

### 3.3 Reference Implementation

`vincul.transport` (VinculNet Stage 1) is the reference transport. It provides:
- `VinculPeer` — symmetric async WebSocket peer
- `PeerRegistry` — in-memory principal-to-key mapping
- `MessageEnvelope` — sign/verify helpers
- `HelloMessage` — handshake helpers

This implementation is **not normative**. Third parties may replace it entirely.

---

## 4. Runtime and Framework Integration Is Non-Normative

### 4.1 What `VinculRuntime` Is

`VinculRuntime` is a **composition root** — it wires together the five protocol components (ContractStore, ScopeStore, ReceiptLog, ConstraintEvaluator, BudgetLedger) and provides convenience methods (`delegate`, `commit`, `revoke`). It is a reference implementation of how to orchestrate the normative artifacts and validation logic.

### 4.2 What `vincul.sdk` Is

`vincul.sdk` is a **high-level convenience layer** built on top of `VinculRuntime`. It reduces onboarding boilerplate for agent and tool authors through decorators and context managers. It is entirely non-normative.

| Construct | Module | Purpose |
|---|---|---|
| `VinculContext` | `vincul.sdk.context` | One-stop coalition setup: principal registration, contract creation/activation, scope chain construction |
| `@vincul_tool` | `vincul.sdk.decorators` | Class decorator for tool providers: sets namespace/tool metadata, auto-generates tool manifest |
| `@vincul_tool_action` | `vincul.sdk.decorators` | Method decorator: wraps business logic with 7-step enforcement pipeline + receipt emission + attested result signing |
| `@vincul_agent` | `vincul.sdk.agent` | Class decorator for agents: binds agent identity to contract + scope, injects `invoke()` method |
| `@vincul_agent_action` | `vincul.sdk.agent` | Method decorator: auto-routes to a `@vincul_tool_action` on a tool with authority parameter injection |
| `ToolResult` | `vincul.sdk.decorators` | Unified return type: `.success`, `.receipt`, `.payload`, `.attested_result`, `.failure_code` |

**Relationship to normative constructs:**

```
  vincul.sdk (non-normative, convenience)
       │
       │ uses
       ▼
  VinculRuntime (non-normative, composition root)
       │
       │ orchestrates
       ▼
  ┌─────────────────────────────────────────────────────┐
  │ Normative constructs                                │
  │  CoalitionContract · Scope · Receipt · Validator    │
  │  DelegationValidator · ScopeStore · ReceiptLog      │
  │  ConstraintEvaluator · BudgetLedger · vincul_hash   │
  └─────────────────────────────────────────────────────┘
```

The decorator layer does not alter validation semantics. Every `@vincul_tool_action` call passes through the same 7-step pipeline. Every receipt is sealed with the same domain-prefixed hash. The SDK layer is syntactic sugar — it can be removed without affecting protocol conformance.

### 4.3 What Is NOT Required

Third-party SDKs are **not required** to:

- Use Python or match the reference implementation's class hierarchy
- Expose a `VinculRuntime` object or equivalent composition root
- Implement `vincul.sdk` decorators or the `VinculContext` convenience layer
- Use in-memory stores (implementations may use databases, event stores, etc.)
- Match the reference implementation's method signatures
- Use the demo application (`apps/`) patterns
- Replicate the reference demo connectors or tool implementations

### 4.4 What IS Required

Third-party SDKs **must** implement the five protocol interfaces (or their equivalent):

| Interface | Purpose | Key Method |
|---|---|---|
| `ContractStoreProtocol` | Contract state | `get`, `is_active`, `activate`, `dissolve` |
| `ScopeStoreProtocol` | Scope DAG + revocation | `get`, `validate_scope`, `revoke`, `ancestors_of` |
| `ReceiptLogProtocol` | Append-only audit | `append`, `get`, `for_contract`, `for_scope` |
| `ConstraintEvaluatorProtocol` | Predicate/ceiling evaluation | `evaluate` |
| `BudgetLedgerProtocol` | Consumption tracking | `check_available`, `record_delta` |

These are structural typing contracts. Implementations need not inherit from or reference the Python Protocol classes — they need only satisfy the same behavioral contract.

---

## 5. Golden Flows

The following three flows define the primary interaction patterns the SDK must support. They are the acceptance test for any conformant implementation.

---

### 5.1 Flow 1: Agent-Tool Execution with Authority Proof and Attested Result

**Scenario:** Agent A holds a delegated scope to invoke Tool T. Agent A requests execution, Tool T validates authority, executes, and returns an attested result.

```
  Agent A                    SDK (Validator)                Tool T
    |                             |                           |
    |  1. commit(action,          |                           |
    |     scope_id,               |                           |
    |     contract_id)            |                           |
    |─────────────────────────────>                           |
    |                             |                           |
    |                  2. 7-step validation                   |
    |                     a. check_contract()                 |
    |                     b. check_scope()                    |
    |                     c. check_type()                     |
    |                     d. check_namespace()                |
    |                     e. check_predicate()                |
    |                     f. check_ceiling()                  |
    |                     g. check_budget()                   |
    |                             |                           |
    |              ┌──────────────┤                           |
    |              │ IF ANY STEP  │                           |
    |              │ FAILS:       │                           |
    |              │              │                           |
    |   <──────────┤ failure_receipt(                         |
    |              │   failure_code,                          |
    |              │   failed_step)                           |
    |              └──────────────┘                           |
    |                             |                           |
    |                  3. All steps pass                      |
    |                     Record budget delta                 |
    |                     (if action type is COMMIT)          |
    |                             |                           |
    |                  4. Seal commitment_receipt             |
    |                     (Intent + Authority + Result)       |
    |                     Append to ReceiptLog                |
    |                             |                           |
    |   <─────────────────────────|                           |
    |  5. Return commitment_receipt                           |
    |     (scope_hash + contract_hash                         |
    |      included as authority proof)                       |
    |                             |                           |
    |  ── SDK BOUNDARY ──────────────────────────────────── ──
    |  Steps 6-9 below are CALLER responsibility,            |
    |  not SDK. The SDK validates and emits receipts.         |
    |  Tool invocation is application-level.                  |
    |  ──────────────────────────────────────────────────── ──
    |                             |                           |
    |  6. Agent A invokes Tool T  |                           |
    |     passing scope_hash +    |                           |
    |     contract_hash as        |                           |
    |     authority proof         |                           |
    |─────────────────────────────────────────────────────────>
    |                             |                           |
    |                             |           7. Tool executes
    |                             |              within bounds
    |                             |                           |
    |  8. Tool returns result     |                           |
    |     + optional              |                           |
    |     attestation_receipt(    |                           |
    |       response_hash,        |                           |
    |       attestation_sig)      |                           |
    |<─────────────────────────────────────────────────────────
    |                             |                           |
    |  9. Agent A appends         |                           |
    |     attestation_receipt     |                           |
    |     to ReceiptLog           |                           |
    |     (if tool attested)      |                           |
    |─────────────────────────────>                           |
    |                             |                           |
```

**Normative requirements for this flow:**
- Steps 2a-2g execute in fixed order; first failure short-circuits
- Failure produces a `failure_receipt` with the specific `FailureCode`
- The commitment receipt contains the scope_hash and contract_hash at time of validation
- Budget delta is recorded only on successful COMMIT action type
- Tool invocation (steps 6-9) is outside SDK scope — the SDK validates and emits receipts; the caller is responsible for tool execution
- Tool attestation is optional; if present it is a separate `attestation_receipt` appended by the caller

---

### 5.2 Flow 2: Agent-Agent Contract Negotiation, Scope Delegation, and Activation

**Scenario:** Agent A and Agent B form a coalition, activate the contract with threshold approval, and Agent A delegates a sub-scope to Agent B.

```
  Agent A                    SDK                         Agent B
    |                         |                              |
    |  1. register_contract(  |                              |
    |     CoalitionContract { |                              |
    |       principals: [A,B],|                              |
    |       governance: {     |                              |
    |         decision_rule:  |                              |
    |           UNANIMOUS },  |                              |
    |       budget_policy,    |                              |
    |       purpose })        |                              |
    |─────────────────────────>                              |
    |                         |                              |
    |                  2. Validate structure                  |
    |                     Seal contract                       |
    |                     (descriptor_hash)                   |
    |                     Store in ContractStore              |
    |                         |                              |
    |   <─────────────────────| 3. Return sealed contract    |
    |                         |                              |
    |  4. Send contract to B  |                              |
    |     [via transport]     |                              |
    |───────────────────────────────────────────────────────────>
    |                         |                              |
    |                         |     5. B verifies            |
    |                         |        descriptor_hash       |
    |                         |        Reviews terms         |
    |                         |                              |
    |                         |     6. B signs approval      |
    |   <───────────────────────────────────────────────────────
    |                         |                              |
    |  7. activate_contract(  |                              |
    |     contract_id,        |                              |
    |     signatures: [A, B]) |                              |
    |─────────────────────────>                              |
    |                         |                              |
    |                  8. Verify signature count              |
    |                     >= governance threshold             |
    |                     Transition: draft -> active         |
    |                     Return (before, after)              |
    |                         |                              |
    |  9. Create root scope   |                              |
    |     Scope {             |                              |
    |       issued_by: A,     |                              |
    |       domain: Domain(   |                              |
    |         namespace=      |                              |
    |           "travel",     |                              |
    |         types=[OBSERVE, |                              |
    |           PROPOSE,      |                              |
    |           COMMIT]),     |                              |
    |       delegate: true,   |                              |
    |       predicate: "TOP", |                              |
    |       ceiling: "TOP" }  |                              |
    |─────────────────────────>                              |
    |                         |                              |
    |                 10. Add to ScopeStore                   |
    |                     Seal (descriptor_hash)              |
    |                         |                              |
    | 11. delegate(           |                              |
    |     parent=root_scope,  |                              |
    |     child=Scope {       |                              |
    |       delegate: false,  |                              |
    |       domain: Domain(   |                              |
    |         namespace=      |                              |
    |           "travel.      |                              |
    |            flights",    |                              |
    |         types=          |                              |
    |           [OBSERVE]),   |                              |
    |       ceiling:           |                              |
    |         "amount<=500",  |                              |
    |       predicate:        |                              |
    |         "amount<=100",  |                              |
    |       issued_by: A })   |                              |
    |─────────────────────────>                              |
    |                         |                              |
    |                 12. DelegationValidator:                |
    |                     a. parent ACTIVE?                   |
    |                     b. types subset?                    |
    |                     c. namespace subset?                |
    |                     d. ceiling subset?                  |
    |                     e. predicate within ceiling?        |
    |                     f. delegate gate?                   |
    |                     g. revoke gate?                     |
    |                         |                              |
    |                 13. Add child to ScopeStore             |
    |                     Emit delegation_receipt             |
    |                     Append to ReceiptLog                |
    |                         |                              |
    |   <─────────────────────| 14. Return delegation_receipt|
    |                         |                              |
    | 15. Send scope + receipt|                              |
    |     to B [via transport]|                              |
    |───────────────────────────────────────────────────────────>
    |                         |                              |
    |                         |    16. B verifies            |
    |                         |        scope_hash            |
    |                         |        receipt_hash          |
    |                         |        B can now act         |
    |                         |        within delegated      |
    |                         |        scope                 |
    |                         |                              |
```

**Normative requirements for this flow:**
- Contract must be sealed (hashed) before activation
- Activation requires signatures meeting the governance `decision_rule` / `threshold`
- Delegation validation checks all 7 containment rules; any failure produces `failure_receipt`
- Child scope types must be a contiguous subset of parent types
- `delegate=false` on child prevents further sub-delegation
- `delegation_receipt` links parent and child scope hashes

---

### 5.3 Flow 3: Revocation with Cascade and Fail-Closed Enforcement

**Scenario:** Agent A revokes a mid-level scope. Revocation cascades to all descendants. Subsequent actions by Agent B (who held a descendant scope) fail closed.

```
  Agent A                    SDK                         Agent B
    |                         |                              |
    |                         |  [Pre-existing state]        |
    |                         |  root_scope (A)              |
    |                         |    └─ mid_scope (A, del=T)   |
    |                         |        └─ leaf_scope (B)     |
    |                         |                              |
    |  1. revoke(             |                              |
    |     scope_id=mid_scope, |                              |
    |     contract_id,        |                              |
    |     initiated_by=A,     |                              |
    |     authority_type=     |                              |
    |       "principal")      |                              |
    |─────────────────────────>                              |
    |                         |                              |
    |                  2. Verify revocation authority         |
    |                     (A is scope issuer OR               |
    |                      A has coalition revoke right)      |
    |                         |                              |
    |                  3. Cascade revocation:                 |
    |                     BFS subtree_of(mid_scope)          |
    |                         |                              |
    |                     mid_scope:  ACTIVE -> REVOKED      |
    |                     leaf_scope: ACTIVE -> REVOKED      |
    |                         |                              |
    |                  4. Build RevocationResult {            |
    |                       root_scope_id: mid_scope,        |
    |                       revoked_ids: [mid, leaf],        |
    |                       pending_ids: [],                 |
    |                       effective_at: now,               |
    |                       initiated_by: A }                |
    |                         |                              |
    |                  5. Seal revocation_receipt             |
    |                     (Intent: revoke mid_scope           |
    |                      Authority: A's principal right     |
    |                      Result: 2 scopes revoked)         |
    |                         |                              |
    |                  6. Append to ReceiptLog                |
    |                         |                              |
    |   <─────────────────────| 7. Return (revocation_receipt,
    |                         |     RevocationResult)        |
    |                         |                              |
    | 8. Notify B of          |                              |
    |    revocation            |                              |
    |    [via transport]       |                              |
    |───────────────────────────────────────────────────────────>
    |                         |                              |
    |                         |     9. B receives            |
    |                         |        revocation notice     |
    |                         |                              |
    |                         |                              |
    |                         |    10. B attempts action:    |
    |                         |        commit(action,        |
    |                         |          scope_id=leaf_scope,|
    |                         |          contract_id)        |
    |                         |<────────────────────────────────
    |                         |                              |
    |                 11. 7-step validation:                  |
    |                     Step 1: check_contract() -> OK     |
    |                     Step 2: check_scope()              |
    |                       └─ validate_scope(leaf_scope)    |
    |                          └─ status == REVOKED          |
    |                          └─ DENY (SCOPE_REVOKED)       |
    |                         |                              |
    |                 12. Seal failure_receipt {              |
    |                       failure_code: SCOPE_REVOKED,     |
    |                       scope_id: leaf_scope,            |
    |                       failed_step: 2 }                 |
    |                         |                              |
    |                 13. Append to ReceiptLog                |
    |                         |                              |
    |                         |────────────────────────────────>
    |                         |    14. Return failure_receipt |
    |                         |        B knows: scope revoked|
    |                         |        action denied          |
    |                         |                              |
    |                         |                              |
    |  === FAIL-CLOSED GUARANTEE (by deployment topology) === |
    |                         |                              |
    |  SHARED STORE (single runtime or shared DB):           |
    |  - Revocation is a state mutation, not a message       |
    |  - Validator reads from the same store A mutated       |
    |  - Step 11 denies regardless of step 8 delivery        |
    |  - Guarantee: immediate, unconditional                 |
    |                         |                              |
    |  DISTRIBUTED (each SDK has own store):                 |
    |  - B's local store may still show ACTIVE               |
    |  - Guarantee depends on state synchronization          |
    |  - revocation_resolution_deadline_ms (Compliance       |
    |    Profile) bounds maximum staleness                   |
    |  - If deadline expires and state is unresolvable:      |
    |    DENY (fail-closed fallback)                         |
    |  - v0.2 does not specify the sync protocol;            |
    |    scope leases are a candidate for v0.3               |
    |                         |                              |
```

**Normative requirements for this flow:**
- Revocation cascades to **all** descendants via BFS traversal of the scope DAG
- Cascade is atomic — either all descendants are revoked or none are
- `RevocationResult` enumerates every affected scope
- Post-revocation, validation fails at step 2 with `SCOPE_REVOKED`
- **Shared-store deployments**: fail-closed is structural — validation reads the same store that was mutated by revocation; denial is immediate and unconditional
- **Distributed deployments**: fail-closed depends on state synchronization; `revocation_resolution_deadline_ms` (Compliance Profile) bounds maximum staleness; if the deadline expires and revocation state is unresolvable, the validator MUST deny
- Notification to affected parties is transport-level (non-normative) — in shared-store topologies, denial does not depend on notification delivery
- Pending revocation (with `effective_at` in the future): actions are **allowed** during the pending window (`t < effective_at`); only delegation from the pending scope is blocked. Once `effective_at` passes, the scope transitions to `REVOKED` and all actions are denied (`SCOPE_REVOKED`). If `effective_at` is missing on a `PENDING_REVOCATION` scope, the validator treats it as revoked (fail-closed)

---

## 6. Compatibility Checklist for Third-Party Implementations

A third-party SDK is **Vincul-compatible** if and only if:

### MUST (Normative)

- [ ] Produces and consumes all 5 artifact types with correct JCS serialization
- [ ] Passes all 13 hash test vectors from `spec/crypto/HASHING.md`
- [ ] Implements the 7-step validation pipeline in locked order
- [ ] Implements revocation cascade (parent revocation -> all descendants revoked)
- [ ] Enforces fail-closed semantics (missing/invalid state -> deny)
- [ ] Produces all 8 receipt kinds with correct `Intent + Authority + Result` structure
- [ ] Seals all artifacts with domain-prefixed SHA-256 hashes
- [ ] Signs and verifies Ed25519 signatures per spec
- [ ] Implements the DelegationValidator containment checks (7 rules)
- [ ] Publishes a Compliance Profile declaring its operational bounds

### MAY (Non-Normative)

- [ ] Use any transport protocol (WebSocket, gRPC, QUIC, etc.)
- [ ] Use any storage backend (in-memory, SQL, event-sourced, etc.)
- [ ] Use any programming language
- [ ] Provide framework integrations (FastAPI, Express, Spring, etc.)
- [ ] Provide decorator/annotation layers equivalent to `vincul.sdk`
- [ ] Extend the Compliance Profile with vendor-specific fields
- [ ] Implement peer discovery in any manner
- [ ] Add encryption layers beyond what the spec requires

### MUST NOT

- [ ] Skip or reorder validation pipeline steps
- [ ] Allow delegation when `delegate=false` on the parent scope
- [ ] Allow actions on revoked or expired scopes
- [ ] Produce receipts with non-deterministic hashes
- [ ] Modify receipts after they are sealed
- [ ] Use domain tags other than those specified

---

## 7. Out of Scope for v0.2

The following are explicitly deferred and not part of the normative SDK boundary:

- **Governance voting protocol** — how votes are collected and tallied is application-level
- **Key management / DID resolution** — identity infrastructure is pluggable
- **Persistent storage schema** — no normative database schema
- **REST/GraphQL API shape** — no normative HTTP API
- **Multi-runtime federation** — cross-implementation coalition mechanics (reserved for v0.3)
- **Scope leases** — a `lease_ttl` on scopes would give distributed deployments a bounded staleness window for revocation propagation, replacing reliance on transport notification with a re-validation deadline; the existing `revocation_resolution_deadline_ms` in Compliance Profiles defines the bound but v0.2 provides no enforcement mechanism — leases are the natural candidate (reserved for v0.3)
- **Distributed state synchronization protocol** — how revocation state propagates between independent SDK instances is not specified; required for the distributed fail-closed guarantee (reserved for v0.3)
- **`required_profile_bounds` in contracts** — reserved for v0.3

---

`CC0 1.0 Universal — No rights reserved.`
`This specification is dedicated to the public domain.`
