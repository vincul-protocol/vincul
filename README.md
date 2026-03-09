# Vincul Protocol

**Bounded collective authority as infrastructure.**

Vincul is a multi-principal coordination protocol with explicit boundaries, cryptographic receipts, and fail-closed enforcement. It enables people, agents, and services to act together under shared constraints — where every decision is scoped, every action is auditable, and every receipt is verifiable.

Vincul’s core innovation is structural:
it places the **Coalition Contract at the root of authority**, not identity.
Authority does not flow from who you are — it flows from what the coalition explicitly bounded and consented to.
This makes bounded collective authority a first-class protocol primitive rather than a policy layered on top of identity.

> *Coordination fails not because people are untrustworthy, but because the tools for establishing shared boundaries have been too expensive, too slow, or too opaque.* — [PHILOSOPHY.md](vincul-spec/PHILOSOPHY.md)

---

## What does Vincul guarantee?

| Guarantee | How |
|---|---|
| **Authority is explicit** | Every action requires a valid scope with declared types, namespace, and ceiling |
| **Actions are attributable** | Every commit produces a hash-sealed receipt linking intent → authority → result |
| **Boundaries are inspectable** | Scopes form a DAG — parent constraints always contain child constraints |
| **Revocation is real** | Revoking a scope cascades to all descendants; post-revocation actions fail closed |

---

## Project Structure

```
src/vincul/                        Core protocol library (11 modules)
│
├── types.py                     Enums, Domain, ValidationResult — pure data
├── hashing.py                   JCS canonicalization, vincul_hash(), normalization
├── identity.py                  Ed25519 sign/verify
├── interfaces.py                5 Protocol definitions (structural typing)
│
├── contract.py                  CoalitionContract, ContractStore, governance
├── scopes.py                    Scope DAG, DelegationValidator, revocation cascade
├── constraints.py               Constraint DSL parser/evaluator
├── receipts.py                  Receipt dataclass, 5 builders, ReceiptLog
├── budget.py                    BudgetLedger — Decimal arithmetic, per-scope ceilings
│
├── validator.py                 7-step enforcement pipeline (imports only interfaces)
├── runtime.py                   VinculRuntime — composition root
├── transport/                   VinculNet peer-to-peer transport
│   ├── envelope.py              Signed message envelopes (Ed25519 + JCS)
│   ├── handshake.py             HELLO handshake for identity binding
│   ├── registry.py              In-memory peer registry
│   ├── peer.py                  VinculPeer — symmetric async WebSocket peer
│   ├── keys.py                  Key persistence (~/.vincul/keys/)
│   └── protocol_peer.py         ProtocolPeer — VinculPeer + VinculRuntime
│
└── sdk/                         High-level SDK for building agents & tools
    ├── context.py               VinculContext — one-stop coalition setup
    ├── decorators.py            @vincul_tool, @tool_operation, ToolResult
    └── agent.py                 @vincul_agent, @agent_action

tests/                           467 unit tests across 10 files
ci/check_vectors.py              13-vector CI gate (hash correctness)

vincul-spec/                       Protocol specification
├── PHILOSOPHY.md                Protocol constitution
├── GLOSSARY.md                  Canonical vocabulary
└── spec/                        12 normative spec documents

connectors/                      Stub connectors for demo (flights, hotels)

apps/
├── server/                      FastAPI backend — demo state, routes, WebSocket
│   ├── main.py                  App entry point, static file serving
│   ├── demo_state.py            8-friends-trip scenario fixtures
│   ├── websocket.py             ConnectionManager, real-time broadcast
│   └── routes/                  REST endpoints (contract, actions, votes, demo)
│
└── web/                         React + TypeScript + Tailwind frontend (Vite)
    └── src/
        ├── api/                 Typed API client
        ├── hooks/               WebSocket + status polling hooks
        └── components/          Dashboard UI — 5 flow cards + timeline
```

---

## Architecture

### Two-store model

Vincul separates state from audit:

- **ContractStore** — source of truth for contract state (draft → active → dissolved)
- **ReceiptLog** — append-only audit trail (hash-verified, immutable once appended)

Stores are independent. Receipt emission is the runtime's responsibility.

### Dependency firewall

```
validator.py  ──imports──▶  interfaces.py (Protocols only)
runtime.py    ──imports──▶  all concrete classes (sole composition root)
```

The validator never sees concrete implementations. All interfaces use `Protocol` (structural typing), not ABC.

### 7-step enforcement pipeline

Every action passes through these checks in locked order. First failure wins.

```
1. Contract valid          active, not expired, not dissolved
2. Scope exists & valid    not revoked, not expired, ancestors valid
3. Operation type          action type ∈ scope's domain types
4. Namespace containment   action namespace ⊆ scope namespace
5. Predicate evaluation    action satisfies scope predicate
6. Ceiling check           action within scope ceiling
7. Budget check            COMMIT only: consumed + requested ≤ ceiling
```

---

## Installation

### Core library only

Install just the Vincul Protocol core library (no server dependencies):

```bash
git clone https://github.com/vincul-protocol/vincul.git && cd vincul
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
```

This installs the `vincul` package with its only dependency (`cryptography`).

### With samples

Install the core library plus sample agents and tools:

```bash
git clone https://github.com/vincul-protocol/vincul.git && cd vincul
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[samples]"
```

Run the cross-vendor tool marketplace demo:

```bash
python -m samples.cross_vendor_tool_marketplace.demo
```

### With demo server

To run the interactive demo, install with the `server` extra and build the frontend:

```bash
git clone https://github.com/vincul-protocol/vincul.git && cd vincul
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[server]"

# Build the frontend
cd apps/web && npm install && npm run build && cd ../..
```

### All extras

```bash
pip install -e ".[samples,server,dev]"
```

### Verify installation

```bash
source .venv/bin/activate
python3 -m unittest discover -s tests -p "test_*.py"    # 425 tests
python3 ci/check_vectors.py                              # 13 vectors
```

---

## Usage

### Creating a runtime

`VinculRuntime` is the main entry point. It wires all stores, validators, and evaluators together:

```python
from vincul.runtime import VinculRuntime
from vincul.contract import CoalitionContract
from vincul.scopes import Scope
from vincul.types import Domain, OperationType

runtime = VinculRuntime()
```

---

## The Demo

The interactive demo proves four assertions through an **8-friends-trip to Italy** scenario.

### Running the demo

After [installing with server dependencies](#with-demo-server):

```bash
source .venv/bin/activate
PYTHONPATH=. uvicorn apps.server.main:app --port 8000
```

Open http://localhost:8000 in your browser. The demo UI shows stakeholder cards, scope popovers, receipt timeline, and animated agent message flows.

Click through the 5 flows in order — each flow demonstrates a different protocol guarantee:

| # | Flow | What happens | Assertion proved |
|---|---|---|---|
| 1 | **Contract Setup** | 8 principals form a coalition with 3 scoped delegations | Delegation is bounded |
| 2 | **Person1 Personal Agent Books Flight** | COMMIT on `travel.flights` with valid scope → success | Receipts are verifiable |
| 3 | **Person2 Personal Agent Tries Hotel Booking** | COMMIT on OBSERVE+PROPOSE scope → `TYPE_ESCALATION` | Scope enforcement works |
| 4 | **All gents Vote to Widen Scope + Rebook** | 5/8 governance vote grants COMMIT → Yaki rebooks | Bounded delegation via governance |
| 5 | **Dissolve Coalition** | Contract dissolved, all scopes revoked, actions fail | Revocation is real |

### Development mode (two terminals)

For frontend hot-reload during development:

```bash
# Terminal 1 — backend
source .venv/bin/activate
PYTHONPATH=. uvicorn apps.server.main:app --reload       # API + WebSocket on :8000

# Terminal 2 — frontend
cd apps/web && npm run dev                               # Vite dev server on :5173
```

### API Endpoints

```
POST /contract/setup          Initialize the 8-friends-trip scenario
POST /contract/dissolve       Dissolve contract + cascade revocation
POST /action                  Execute action through enforcement pipeline
POST /vote/open               Open a governance vote
POST /vote/cast               Cast vote (auto-resolves at threshold)
POST /demo/reset              Reset to clean state
GET  /demo/status             Current state summary
GET  /demo/state              Enriched state (principals, scopes, governance, budget)
WS   /ws                      Real-time event broadcast
```

---

## Specification

The full protocol specification lives in [`vincul-spec/`](vincul-spec/spec/README.md). Start with:

1. [`PHILOSOPHY.md`](vincul-spec/PHILOSOPHY.md) — the protocol constitution
2. [`GLOSSARY.md`](vincul-spec/GLOSSARY.md) — canonical vocabulary
3. [`spec/scope/SCHEMA.md`](vincul-spec/spec/scope/SCHEMA.md) — scope structure and validity
4. [`spec/receipts/RECEIPT.md`](vincul-spec/spec/receipts/RECEIPT.md) — receipt envelope
5. [`spec/crypto/HASHING.md`](vincul-spec/spec/crypto/HASHING.md) — JCS canonicalization + 13 test vectors

**Protocol version: v0.2** — complete geometry, no open gaps.

---

## Requirements

- **Python** 3.11+ (tested on 3.13.9)
- **Node.js** 18+ (for frontend, tested on 22.x)
- No external runtime dependencies beyond `cryptography` (core) and `fastapi`/`uvicorn`/`websockets` (server)

---

## Testing

```bash
# Full test suite (425 tests)
python3 -m unittest discover -s tests -p "test_*.py"

# Single module
python3 -m unittest tests.test_validator

# CI gate — hash correctness (must always pass)
python3 ci/check_vectors.py
```

All tests use `unittest`. Each test file is self-contained — no shared fixtures or conftest.

---

## Implementation Status

The Vincul protocol specification (v0.2) is complete and fully test-vector verified.

VinculNet Stage 1 (authenticated peer transport) and Stage 2 (protocol over the wire) are implemented.

- **Stage 1:** Two `VinculPeer` instances can perform mutual HELLO handshake over WebSocket, exchange signed message envelopes, and reject tampered or spoofed messages.
- **Stage 2:** `ProtocolPeer` composes `VinculPeer` + `VinculRuntime`. Agents can commit actions locally, validate through the 7-step enforcement pipeline, and broadcast success receipts to peers. Receiving peers verify receipt integrity and cross-check scope/contract hashes against their own local state.

See `vincul-spec/spec/transport/VINCULNET.md` for the transport specification and `src/vincul/transport/` for the implementation.

---

## License

This project is dedicated to the **public domain** under [CC0 1.0 Universal](LICENSE.md).

You can copy, modify, distribute, and perform the work — even for commercial purposes — all without asking permission. No attribution required.

---

Generated on 2026-03-01 — @smazor project
