# CLAUDE.md — Pact Protocol

## What is this project?

Pact is a local-first bounded authority coordination protocol. It lets multiple principals (people, agents, services) coordinate actions under shared constraints — with cryptographic receipts proving every decision.

The core library is in Python. The demo is a FastAPI backend + React frontend showing an 8-friends-trip scenario.

## Repository layout

```
src/pact/              Core library (11 modules)
  types.py             Enums, Domain, ValidationResult — pure data, no logic
  hashing.py           JCS serialization, pact_hash(), normalize_contract()
  identity.py          Ed25519 sign/verify
  interfaces.py        5 Protocols (structural typing, @runtime_checkable)
  receipts.py          Receipt dataclass, 5 builders, ReceiptLog
  scopes.py            Scope DAG, DelegationValidator, RevocationResult
  contract.py          CoalitionContract, ContractStore, governance checks
  constraints.py       Constraint DSL parser/evaluator (TOP|BOTTOM|AND atoms)
  budget.py            BudgetLedger (Decimal arithmetic, per-scope per-dimension)
  validator.py         7-step enforcement pipeline (imports only interfaces)
  runtime.py           PactRuntime composition root (only file importing concrete classes)

tests/                 425 tests across 8 files
ci/check_vectors.py    13-vector CI gate (hash correctness)
pact-spec/             Protocol specification (12 spec documents)

connectors/            Stub connectors for demo (flights, hotels)
apps/server/           FastAPI backend (demo state, routes, WebSocket)
apps/web/              React + TypeScript + Tailwind frontend (Vite)
```

## Quick start

```bash
# Python setup
python3 -m venv .venv && source .venv/bin/activate
pip install setuptools wheel && pip install -e ".[server]" --no-build-isolation

# Run tests
python3 -m unittest discover -s tests -p "test_*.py"    # 425 tests
python3 ci/check_vectors.py                              # 13 vectors

# Run demo (production mode — single process)
cd apps/web && npm install && npm run build && cd ../..
uvicorn apps.server.main:app                             # http://localhost:8000

# Run demo (dev mode — two terminals)
uvicorn apps.server.main:app --reload                    # Terminal 1: backend :8000
cd apps/web && npm run dev                               # Terminal 2: frontend :5173
```

## Architecture

### Two-store model
- **ContractStore** owns contract state (draft → active → dissolved)
- **ReceiptLog** owns the audit trail (append-only, hash-verified)
- Stores are independent; receipt emission is the runtime's job

### Dependency firewall
- `validator.py` imports only `interfaces.py` (Protocols), never concrete classes
- `runtime.py` is the sole composition root — only module that imports all concrete stores
- All interfaces use `Protocol` (structural typing), not ABC

### 7-step enforcement pipeline (locked order)
1. Contract valid (active, not expired, not dissolved)
2. Scope exists and valid (not revoked, not expired, ancestors valid)
3. Operation type authorized (action type in scope's domain types)
4. Namespace containment (action namespace within scope namespace)
5. Predicate evaluation (action satisfies scope predicate)
6. Ceiling check (action within scope ceiling)
7. Budget check (COMMIT only; consumed + requested ≤ ceiling)

### Precedence rules
- §3.2: Dissolution over expiry (if both apply, report dissolved)
- §3.3: Contract failure over scope failure (if contract is dissolved/expired, report that first)
- Fail closed on any uncertainty

## Key gotchas

- **Scope hashes change on status mutation** — capture `descriptor_hash` BEFORE calling `revoke()` or any status change
- **Contract hashes change on activate/dissolve** — lifecycle methods return `(before, after)` tuples
- **`failure_receipt()` accepts `**extra_detail`** — filter out keys that collide with its explicit params using `_extra_detail()` in runtime.py
- **Deep copy for before-snapshots** — use `json.loads(json.dumps(...))` to break shared mutable dict references
- **Constraint DSL v0.2** — only supports `TOP | BOTTOM | conjunction of atoms`. Atoms use `field_path operator value` format (e.g., `action.params.cost <= 1500`), not function call syntax
- **Principals sorted by principal_id** before contract hashing (normalization)

## Testing

```bash
# All tests
python3 -m unittest discover -s tests -p "test_*.py"

# Single module
python3 -m unittest tests.test_validator

# CI gate (hash correctness — must always pass)
python3 ci/check_vectors.py
```

Tests use `unittest`. No pytest fixtures or conftest — each test file is self-contained.

## Demo

The demo proves 4 assertions:
1. **Delegation is bounded** — scopes have limited types, namespaces, ceilings
2. **Commitment requires correct scope** — wrong scope → TYPE_ESCALATION
3. **Revocation is real** — dissolve → all scopes revoked, actions fail
4. **Receipts are verifiable** — every action produces a hash-sealed receipt

### Backend endpoints
```
POST /contract/setup          Set up 8-friends-trip contract
POST /contract/dissolve       Dissolve contract + revoke all scopes
POST /action                  Execute action through enforcement pipeline
POST /vote/open               Open governance vote
POST /vote/cast               Cast vote (auto-resolves at threshold)
POST /demo/reset              Reset to clean state
GET  /demo/status             Current state summary
WS   /ws                      Real-time receipt/event broadcast
```

### Fixed demo identifiers
- Contract: `c0000000-0000-0000-0000-000000000001`
- Root scope: `s0000000-0000-0000-0000-000000000001`
- Raanan flights: `s0000000-0000-0000-0000-000000000002`
- Yaki accommodation: `s0000000-0000-0000-0000-000000000003`
- 8 principals: raanan, yaki, coordinator, alice, bob, carol, dan, eve

## Environment

- Python 3.13.9, venv at `.venv`
- Node 22+, dependencies in `apps/web/node_modules`
- No external runtime dependencies beyond `cryptography` (core) and `fastapi`/`uvicorn`/`websockets` (server)
