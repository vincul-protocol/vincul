Here is a **high-impact "agentic world" use case** where Vincul's combination of **contracts + scoped delegation + receipts + revocation + attestations + compliance profiles** gives you something you don't get from typical tool-calling or API keys.

---

## Cross-vendor tool marketplace with portable, verifiable authorization

**Scenario:** An agent from Vendor A wants to use tools hosted by Vendor B (payments, ticketing, CRM, cloud ops), possibly pulling data from Vendor C. No one wants to mint long-lived API keys for unknown agents.

**Why existing approaches break:**

* OAuth/API keys are **identity-first** and often **long-lived**, brittle to revoke, and not "portable" to arbitrary third-party tools.
* Tool vendors are forced to trust the caller's claims ("the user authorized this") because they can't verify the full decision context.
* Auditing becomes fragmented across vendors (no shared artifact trail).

**What Vincul enables:**

* A **CoalitionContract** binds all parties (Vendor A, B, C) with verifiable governance and lifecycle.
* Vendor B issues a **Scope chain** (root → mid → leaf) to Vendor A's agent via the SDK's DelegationValidator (7 containment checks).
* The agent invokes tools through the SDK's **7-step enforcement pipeline** (Validator), which produces a **commitment receipt** bound to contract_hash + scope_hash.
* Tool results are wrapped as **Attested Results** (signed outputs bound to the authority context).
* Revocation uses **ScopeStore.revoke()** with BFS cascade — revoking a mid-level scope automatically revokes all descendants. Fail-closed: revoked scopes are denied immediately.

**Concrete wins:**

* Tool vendors get **zero-trust execution**: the SDK validates contract, scope, types, namespace, predicate, ceiling, and budget before the tool runs.
* Agent vendors can integrate tools without per-tool bespoke auth, while still enforcing least privilege via scope ceilings.
* Everyone gets an interoperable audit trail via the **ReceiptLog** (append-only, hash-verified).

**Where Vincul is uniquely strong:**
Portable authority + verifiable results across vendors without centralizing the trust decision.

---

# Implementation — SDK Alignment

**Status:** Implemented
**Location:** `samples/cross_vendor_tool_marketplace/`
**SDK Version:** vincul 0.2
**SDK Layer:** `src/vincul/sdk/`
**Install:** `pip install -e ".[samples]"`

This demo is built on the **vincul SDK high-level layer** (`vincul.sdk`), which wraps the core vincul constructs behind decorators and context managers. No parallel crypto, hashing, or data models.

---

## SDK High-Level Constructs (vincul.sdk)

| SDK Module | Construct | Used For |
|---|---|---|
| `vincul.sdk` | `VinculContext` | One-stop coalition setup: principals, contract, scope chain |
| `vincul.sdk` | `@vincul_tool` | Class decorator: auto-generates tool manifest, sets namespace/tool metadata |
| `vincul.sdk` | `@tool_operation` | Method decorator: wraps business logic with 7-step pipeline + receipts + attestation |
| `vincul.sdk` | `VinculAgent` | Base class for agents: binds identity + contract + scope, provides `invoke()` |
| `vincul.sdk` | `ToolResult` | Unified return type: success/failure, receipt, payload, attested result |

## Core Constructs (used internally by vincul.sdk)

| SDK Module | Construct | Used For |
|---|---|---|
| `vincul.identity` | `KeyPair`, `PrincipalRegistry`, `sign`, `verify` | Ed25519 key generation, signature creation and verification |
| `vincul.contract` | `CoalitionContract`, `ContractStore` | Multi-party contract with governance (unanimous decision rule) |
| `vincul.scopes` | `Scope`, `ScopeStore`, `DelegationValidator` | Scope DAG (root→mid→leaf), 7-check delegation validation, BFS revocation cascade |
| `vincul.validator` | `Validator` | 7-step enforcement pipeline (contract→scope→type→namespace→predicate→ceiling→budget) |
| `vincul.receipts` | `Receipt`, `ReceiptLog`, receipt builders | delegation, commitment, failure, revocation receipts — append-only audit |
| `vincul.runtime` | `VinculRuntime` | Composition root wiring all stores + validator |
| `vincul.hashing` | `vincul_hash`, `jcs_serialize` | Domain-prefixed SHA-256 hashing (JCS canonicalization) |
| `vincul.constraints` | `ConstraintEvaluator` | Predicate and ceiling evaluation (`params.quantity <= 5`) |
| `vincul.types` | `Domain`, `OperationType`, `ScopeStatus`, `FailureCode`, etc. | Shared domain types |

---

## Data Model Alignment

All artifacts use **vincul SDK dataclasses** directly:

### Contract
Uses `CoalitionContract` with:
- `principals` — list of `{principal_id, role, permissions}` dicts
- `governance` — `{decision_rule: "unanimous", threshold: null}`
- `activation` — lifecycle state machine: `draft → active`
- `descriptor_hash` — domain-prefixed SHA-256 (`PACT_CONTRACT_V1\x00` + JCS payload)

### Scopes
Uses `Scope` with:
- `domain` — `Domain(namespace="marketplace.orders", types=(OBSERVE, PROPOSE, COMMIT))`
- `ceiling` — constraint DSL expression, e.g. `"params.quantity <= 10"`
- `predicate` — constraint DSL expression, e.g. `"params.quantity <= 5"`
- `delegate` — `True` for root/mid, `False` for leaf (explicit, never implied)
- `status` — `ScopeStatus.ACTIVE` or `ScopeStatus.REVOKED`
- `descriptor_hash` — domain-prefixed SHA-256 (`PACT_SCOPE_V1\x00` + JCS payload)

### Receipts
Uses SDK `Receipt` with structured Intent/Authority/Result:
- **Intent**: `{action, description, initiated_by}`
- **Authority**: `{scope_id, scope_hash, contract_id, contract_hash, signatories}`
- **Result**: `{outcome, detail}`
- `receipt_hash` — domain-prefixed SHA-256 (`PACT_RECEIPT_V1\x00` + JCS payload)

Receipt kinds emitted: `delegation`, `commitment`, `revocation`, `failure`.

---

## Validation Pipeline

The tool uses the SDK's **7-step enforcement pipeline** (locked order, first failure wins):

| Step | Check | SDK Method |
|------|-------|-----------|
| 1 | Contract valid (active, not expired, not dissolved) | `Validator._check_contract()` |
| 2 | Scope valid (not revoked, not expired, ancestors valid via DAG) | `ScopeStore.validate_scope()` |
| 3 | Operation type authorized (`COMMIT` in scope domain types) | `Validator._check_type()` |
| 4 | Namespace containment (`marketplace.orders` within scope namespace) | `Validator._check_namespace()` |
| 5 | Predicate evaluation (action params satisfy scope predicate) | `ConstraintEvaluator.evaluate()` |
| 6 | Ceiling check (action params within scope ceiling) | `ConstraintEvaluator.evaluate()` |
| 7 | Budget check (if budget_policy is enabled) | `BudgetLedger.check_available()` |

---

## Revocation

Uses `ScopeStore.revoke()` with BFS cascade:
- Revoking mid scope automatically revokes leaf scope
- Root scope is unaffected
- Post-revocation invocations fail with `SCOPE_REVOKED` at validation step 2
- Fail-closed: no notification needed — scope status is checked directly

---

## Wire-Format Overlays

Two thin JSON envelopes sit above the SDK for cross-vendor tool discovery and attested outputs:

### Tool Manifest
A tool advertisement artifact (not a vincul core artifact):
```json
{
  "tool_manifest_version": "vmip-0.1",
  "tool_id": "tool:VendorB:order-tool",
  "vendor_id": "vendor:VendorB",
  "tool_version": "0.1.0",
  "namespace": "marketplace.orders",
  "operations": [{"name": "place_order", "action_type": "COMMIT", "side_effecting": true}],
  "attestation_policy": {"result_signature_required": true, "external_ref_required": true}
}
```

### Attested Result
A signed tool output bound to vincul SDK hashes:
```json
{
  "result_version": "vmip-0.1",
  "result_id": "<uuid>",
  "tool_id": "tool:VendorB:order-tool",
  "contract_hash": "<vincul domain-prefixed hex hash>",
  "scope_hash": "<vincul domain-prefixed hex hash>",
  "receipt_hash": "<vincul domain-prefixed hex hash>",
  "status": "success",
  "result_payload": {"order_id": "order-demo-0001", "charged_amount_usd": 12.34},
  "result_payload_hash": "<vincul domain-prefixed hex hash>",
  "signature": {"signer_id": "vendor:VendorB", "algo": "Ed25519", "sig": "<b64url>"}
}
```

All hashes in Attested Results are vincul SDK `descriptor_hash` / `receipt_hash` values (domain-prefixed SHA-256, lowercase hex).

---

## Demo Flow

The demo (`demo.py`) runs 9 steps:

1. **Vendor Setup** — `VinculContext.add_principal()` for Vendors A, B, C (one call each)
2. **Contract** — `VinculContext.create_contract()` (single call: creates, registers, activates)
3. **Scope Chain** — `VinculContext.create_scope_chain()` with a config list (single call)
4. **Successful Invocation** — `VinculAgent.invoke()` → `@tool_operation` → 7-step pipeline → `ToolResult`
5. **Second Invocation** — quantity=2, also succeeds
6. **Revocation** — `VinculContext.revoke_scope()` on mid scope → BFS cascade to leaf
7. **Post-Revocation** — invocation fails with `SCOPE_REVOKED` (fail-closed)
8. **Receipt Audit** — full ReceiptLog timeline with hash verification
9. **Constraint Violation** — quantity=999 exceeds `params.quantity <= 5` ceiling → `SCOPE_EXCEEDED`

See [README.md](../../README.md#with-samples) for installation and running instructions.

---

## File Structure

```
src/vincul/sdk/                                     # Reusable SDK layer (inside vincul package)
├── __init__.py             # Public API: VinculContext, vincul_tool, tool_operation, vincul_agent, agent_action, ToolResult
├── context.py              # VinculContext — one-stop coalition setup
├── decorators.py           # @vincul_tool, @tool_operation, ToolResult, attested result builder
└── agent.py                # @vincul_agent, @agent_action — agent decorators with invoke()

samples/cross_vendor_tool_marketplace/               # Separate package (pip install vincul[samples])
├── __init__.py
├── spec.md                 # This file
├── vendor_a_agent.py       # Buyer agent — @vincul_agent + @agent_action (5 lines of logic)
├── vendor_b_tool.py        # Order tool — @vincul_tool + @tool_operation (7 lines of logic)
└── demo.py                 # End-to-end demo runner (9 steps)
```

---

## Key Design Decisions

1. **No parallel crypto** — all hashing uses `vincul.hashing` (domain-prefixed SHA-256); all signing uses `vincul.identity.KeyPair` (Ed25519)
2. **No parallel data models** — contracts are `CoalitionContract`, scopes are `Scope`, receipts are `Receipt`
3. **No custom validation** — tool invocation goes through the SDK's `VinculRuntime.commit()` which runs the full 7-step `Validator` pipeline
4. **No custom revocation** — uses `ScopeStore.revoke()` with automatic BFS cascade
5. **Hashes match** — `descriptor_hash` on contracts/scopes and `receipt_hash` on receipts are the canonical vincul domain-prefixed hashes used everywhere
6. **Wire overlays are minimal** — Tool Manifest and Attested Result are thin JSON envelopes that carry SDK hashes, not alternatives to them
7. **Decorator-driven tool definition** — `@vincul_tool` + `@tool_operation` eliminate boilerplate: tool authors write only business logic; validation, receipts, and attestation are automatic
8. **Easy onboarding** — new tools require ~10 lines (class + one decorated method); new agents require ~5 lines (subclass VinculAgent + domain method); coalition setup is a single `VinculContext` with 3 calls
