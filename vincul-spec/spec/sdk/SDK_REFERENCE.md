# Vincul SDK — API Reference
`SDK_REFERENCE.md` · v0.2

---

## Overview

The Vincul SDK (`vincul.sdk`) is a non-normative convenience layer over the Vincul protocol runtime. It provides three decorator patterns for three trust models:

| Pattern | Caller | Enforcer | Scope resolution |
|---|---|---|---|
| `@vincul_tool` + `@vincul_tool_action` | Programmatic code | Tool (self-enforcing) | Caller passes `scope_id` explicitly |
| `@vincul_agent` + `@vincul_agent_action` | Programmatic code | Tool (via agent routing) | Agent auto-injects from bound scopes |
| `@vincul_enforce` + `VinculAgentContext` | LLM (via framework) | Decorator | Auto-resolved from agent context |

All patterns feed into the same 7-step validation pipeline and produce the same normative artifacts (receipts, hashes, attested results).

---

## 1. VinculContext

**Module:** `vincul.sdk.context`

One-stop coalition setup. Wraps `VinculRuntime` with convenience methods for principal registration, contract lifecycle, scope management, budget, and queries.

### Constructor

```python
VinculContext(max_delegation_depth: int = 10)
```

### Principal Management

| Method | Returns | Description |
|---|---|---|
| `add_principal(principal_id, *, role, permissions)` | `KeyPair` | Register principal with fresh Ed25519 keypair |
| `keypair(principal_id)` | `KeyPair` | Retrieve a registered keypair |

`permissions` is a list of `"delegate"`, `"commit"`, `"revoke"`.

### Contract Lifecycle

| Method | Returns | Description |
|---|---|---|
| `create_contract(*, purpose_title, ...)` | `CoalitionContract` | Create, register, and activate a contract |
| `get_contract(contract_id)` | `CoalitionContract \| None` | Look up contract by ID |
| `dissolve_contract(*, contract_id, dissolved_by, signatures)` | `Receipt` | Dissolve a contract |

`create_contract` full signature:

```python
create_contract(
    *,
    purpose_title: str,
    purpose_description: str = "",
    expires_at: str = "2026-12-31T00:00:00Z",
    governance_rule: str = "unanimous",
    governance: dict | None = None,         # overrides governance_rule
    budget_allowed: bool = False,
    budget_dimensions: list[dict] | None = None,
    signatories: list[str] | None = None,   # defaults to all principals
) -> CoalitionContract
```

### Scope Management

| Method | Returns | Description |
|---|---|---|
| `create_scope_chain(*, contract_id, issued_by, namespace, chain, operations=None)` | `list[Scope]` | Build root → ... → leaf chain |
| `add_scope(scope)` | `Scope` | Add a root scope (no parent) |
| `delegate_scope(*, parent_scope_id, child, contract_id, initiated_by)` | `(Receipt, Scope)` | Delegate child from parent |
| `revoke_scope(scope_id, contract_id, initiated_by, authority_type="principal")` | `(Receipt, RevocationResult)` | Revoke with BFS cascade |
| `get_scope(scope_id)` | `Scope \| None` | Look up scope by ID |

`create_scope_chain` `chain` entry format:

| Key | Type | Default | Description |
|---|---|---|---|
| `ceiling` | `str` | `"TOP"` | Constraint expression |
| `predicate` | `str` | = ceiling | Constraint expression |
| `delegate` | `bool` | `True` (except last) | Allow sub-delegation |
| `ttl_hours` | `float` | Decreasing from 2h | Time-to-live |
| `revoke` | `str` | `"principal_only"` | Revocation policy |

### Budget

| Method | Returns | Description |
|---|---|---|
| `set_budget_ceiling(scope_id, dimension, amount)` | `None` | Set budget ceiling |
| `get_budget_balance(scope_id, dimension)` | `Decimal \| None` | Remaining balance |

### Commit (7-Step Pipeline)

```python
commit(
    *,
    action: dict,           # {type, namespace, resource, params}
    scope_id: str,
    contract_id: str,
    initiated_by: str,
    reversible: bool = False,
    revert_window: str | None = None,
    external_ref: str | None = None,
    budget_amounts: dict[str, str] | None = None,
) -> Receipt
```

Returns a commitment receipt on success, failure receipt on denial.

### Receipt Queries

| Method | Returns |
|---|---|
| `get_receipt(receipt_hash)` | `Receipt \| None` |
| `receipts_for_contract(contract_id)` | `list[Receipt]` |
| `receipts_for_scope(scope_id)` | `list[Receipt]` |

### Convenience Properties

| Property | Type |
|---|---|
| `receipts` | `ReceiptLog` |
| `scopes` | `ScopeStore` |
| `contracts` | `ContractStore` |

---

## 2. @vincul_tool

**Module:** `vincul.sdk.decorators`

Class decorator for tool providers. Binds a fixed namespace and tool ID. Auto-generates a VMIP-0.1 tool manifest after `__init__`.

```python
@vincul_tool(*, namespace: str, tool_id: str, tool_version: str = "0.1.0")
```

**Requirements:** The decorated class must set `key_pair: KeyPair` and `runtime: VinculRuntime` in `__init__`.

**Injected class attributes:**

| Attribute | Description |
|---|---|
| `_vincul_namespace` | Namespace string |
| `_vincul_tool_id` | Tool identifier |
| `_vincul_tool_version` | Version string |

**Injected instance attribute:**

| Attribute | Description |
|---|---|
| `tool_manifest` | VMIP-0.1 manifest dict, built from all `@vincul_tool_action` methods |

**Tool manifest structure:**

```python
{
    "tool_manifest_version": "vmip-0.1",
    "tool_id": str,
    "vendor_id": str,          # from key_pair.principal_id
    "tool_version": str,
    "protocol": "mcp",
    "namespace": str,
    "operations": [
        {"name": str, "description": str, "action_type": str, "side_effecting": bool},
    ],
    "attestation_policy": {
        "result_signature_required": True,
        "external_ref_required": True,
    },
}
```

**Example:**

```python
@vincul_tool(namespace="marketplace.orders", tool_id="tool:VendorB:order-tool")
class OrderTool:
    def __init__(self, key_pair: KeyPair, runtime: VinculRuntime):
        self.key_pair = key_pair
        self.runtime = runtime

    @vincul_tool_action(action_type=OperationType.COMMIT, resource_key="item_id")
    def place_order(self, *, item_id: str, quantity: int) -> dict:
        return {"order_id": "ord-001"}
```

---

## 3. @vincul_tool_action

**Module:** `vincul.sdk.decorators`

Method decorator for tool operations. Wraps business logic with action dict construction, 7-step pipeline enforcement, receipt emission, and attested result signing.

```python
@vincul_tool_action(
    *,
    action_type: OperationType = OperationType.COMMIT,
    resource_key: str | None = None,
    side_effecting: bool = True,
    description: str = "",
)
```

| Parameter | Description |
|---|---|
| `action_type` | `OBSERVE`, `PROPOSE`, or `COMMIT` |
| `resource_key` | Kwarg name appended to resource path (e.g. `"item_id"` → `"place_order/book-1"`) |
| `side_effecting` | `False` for read-only operations |
| `description` | Overrides docstring in manifest |

**Calling convention:**

The caller passes authority params alongside business params:

```python
result = tool.place_order(
    scope_id=leaf.id,
    contract_id=contract.contract_id,
    initiated_by="agent:buyer",
    item_id="book-1",
    quantity=2,
    budget_amounts={"EUR": "12.34"},  # optional
)
```

Authority params (`scope_id`, `contract_id`, `initiated_by`, `budget_amounts`) are separated automatically. Business params are forwarded to the method body.

**Execution flow:**

1. Separate authority params from business params
2. Build resource path (with optional `resource_key`)
3. Build action dict `{type, namespace, resource, params}`
4. `runtime.commit()` — 7-step pipeline
5. On failure: return `ToolResult(success=False, receipt=failure_receipt)` with attested result
6. On success: call business logic, auto-detect `external_ref` from common payload keys (`order_id`, `id`, `ref`, `external_ref`), return `ToolResult(success=True, receipt, payload)` with attested result

**Injected on method:** `_vincul_op_meta` dict:

```python
{"name": str, "action_type": OperationType, "side_effecting": bool, "description": str}
```

---

## 4. ToolResult

**Module:** `vincul.sdk.decorators`

Unified return type from all SDK tool operations.

```python
@dataclass
class ToolResult:
    success: bool
    receipt: Receipt
    payload: dict | None = None
    attested_result: dict | None  # auto-built, not settable via init

    # InitVar fields — consumed by __post_init__, not stored
    tool_id: InitVar[str | None] = None
    tool_version: InitVar[str] = "0.1.0"
    signer: InitVar[KeyPair | None] = None
    external_ref: InitVar[str] = ""
```

### Properties

| Property | Type | Description |
|---|---|---|
| `failure_code` | `str \| None` | From `receipt.detail["error_code"]`, `None` on success |
| `message` | `str \| None` | From `receipt.detail["message"]`, `None` on success |

### Auto-Attestation

When both `tool_id` and `signer` are provided, `__post_init__` builds a signed VMIP-0.1 attested result:

```python
{
    "result_version": "vmip-0.1",
    "result_id": str,
    "tool_id": str,
    "tool_version": str,
    "contract_hash": str,
    "scope_hash": str,
    "receipt_hash": str,
    "status": "success" | "failure",
    "result_payload": dict,
    "result_payload_hash": str,
    "timestamp": str,
    "external_ref": str,
    "signature": {
        "signer_id": str,
        "algo": "Ed25519",
        "sig": str
    }
}
```

On success, `result_payload` contains the business payload. On failure, it contains `{"failure_code": ..., "message": ...}`.

---

## 5. @vincul_agent

**Module:** `vincul.sdk.agent`

Class decorator for programmatic agents. Binds agent identity, contract, and scopes. Injects `invoke()`, `find_scope()`, and property accessors.

```python
@vincul_agent(*, agent_id: str)
```

**Injected `__init__` signature:**

```python
def __init__(self, *, contract: CoalitionContract, scopes: list[Scope], **kwargs)
```

Original `__init__` (if any) receives `**kwargs` without `contract`/`scopes`.

**Injected members:**

| Member | Type | Description |
|---|---|---|
| `agent_id` | `str` | The agent ID from the decorator |
| `contract` | `CoalitionContract` | Bound contract |
| `scope` | `Scope \| None` (property) | First scope |
| `scopes` | `list[Scope]` (property) | All bound scopes |
| `find_scope(namespace, action_type)` | method → `Scope \| None` | Find scope by namespace + action type |
| `invoke(tool, operation, **params)` | method → `ToolResult` | Call a `@vincul_tool_action`, auto-resolving scope |

### find_scope

```python
find_scope(namespace: str, action_type: str) -> Scope | None
```

Iterates `_scopes`, returns the first where `action_type in scope.domain.types` and `scope.domain.contains_namespace(namespace)`. Returns `None` if no match.

### invoke

```python
invoke(tool, operation: str, **params) -> ToolResult
```

Calls `tool.<operation>(scope_id=..., contract_id=..., initiated_by=..., **params)`.

**Scope resolution logic:**
- Multiple scopes + tool has `_vincul_namespace` and method has `_vincul_op_meta`: auto-resolves via `find_scope()`. Raises `ValueError` if no match.
- Single scope or no tool metadata: uses first scope.
- No scopes: raises `ValueError`.

**Example:**

```python
@vincul_agent(agent_id="agent:VendorA:buyer1")
class BuyerAgent:
    @vincul_agent_action(operation="place_order")
    def buy(self, tool, *, item_id: str, quantity: int) -> ToolResult:
        """Body replaced by auto-invoke."""

agent = BuyerAgent(contract=contract, scopes=[order_scope, shipping_scope])
result = agent.buy(order_tool, item_id="book-1", quantity=2)
# invoke() reads order_tool._vincul_namespace to pick order_scope
```

---

## 6. @vincul_agent_action

**Module:** `vincul.sdk.agent`

Method decorator for agent actions. Auto-routes to a `@vincul_tool_action` on a tool with authority injection.

```python
@vincul_agent_action(*, operation: str | None = None)
@vincul_agent_action   # no parentheses — operation defaults to method name
```

| Parameter | Description |
|---|---|
| `operation` | Tool method name to invoke. Default: decorated method's name. |

**Calling convention:** First positional arg after `self` is the tool instance. Remaining kwargs are business params.

```python
@vincul_agent_action(operation="place_order")
def buy(self, tool, *, item_id: str, quantity: int) -> ToolResult:
    """Calls self.invoke(tool, "place_order", item_id=..., quantity=...)"""
```

**Injected on method:** `_vincul_action_meta` dict:

```python
{"name": str, "operation": str}
```

---

## 7. VinculAgentContext

**Module:** `vincul.sdk.enforce`

Pre-built authority bundle for LLM agent tools. Bundles identity, runtime, scopes, and callbacks. Resolved at call time by `@vincul_enforce`.

```python
@dataclass
class VinculAgentContext:
    principal_id: str
    contract_id: str
    signer: KeyPair
    runtime: VinculRuntime
    _scopes: list[Scope] = field(default_factory=list)
    on_commit: Callable[[Receipt], None] | None = None
    on_result: Callable[[ToolResult, OperationType, dict], dict | None] | None = None
```

### find_scope

```python
find_scope(namespace: str, action_type: str) -> Scope | None
```

Same logic as `@vincul_agent.find_scope()`.

### Callbacks

| Callback | Signature | When | Purpose |
|---|---|---|---|
| `on_commit` | `(Receipt) -> None` | After successful enforcement | Broadcast receipt (e.g. over VinculNet) |
| `on_result` | `(ToolResult, OperationType, dict) -> dict \| None` | After every attempt | Return dict to merge into JSON response |

---

## 8. @vincul_enforce

**Module:** `vincul.sdk.enforce`

Function decorator for LLM agent tools. Composable with framework tool decorators (e.g. Strands `@tool`). Handles scope lookup, 7-step pipeline, ToolResult wrapping, attestation, callbacks, and JSON response formatting.

```python
vincul_enforce(
    *,
    action_type: OperationType,
    tool_id: str,
    agent: Callable[[], VinculAgentContext],
    namespace: str | Callable[..., str],
    action_params: str | Callable[..., dict] | None = None,
    tool_version: str = "0.1.0",
    pre_check: Callable[..., str | None] | None = None,
)
```

### Parameters

| Parameter | Type | Description |
|---|---|---|
| `action_type` | `OperationType` | `OBSERVE`, `PROPOSE`, or `COMMIT` |
| `tool_id` | `str` | Attestation identifier |
| `agent` | `() -> VinculAgentContext` | Resolved at call time |
| `namespace` | `str \| (**kwargs) -> str` | Static or dynamic namespace |
| `action_params` | `str \| (**kwargs) -> dict \| None` | Selects which kwargs become `action["params"]` |
| `tool_version` | `str` | Default `"0.1.0"` |
| `pre_check` | `(**kwargs) -> str \| None` | Return string to deny before enforcement |

### action_params

| Value | Behavior |
|---|---|
| `None` (default) | All tool kwargs become action params |
| `str` (e.g. `"params"`) | `kwargs["params"]` becomes action params |
| `callable` | `callable(**kwargs)` returns action params |

### Decorator Ordering

```python
@tool(name="...")         # outer: framework interface (runs first)
@vincul_enforce(...)      # inner: authority enforcement (runs second)
def my_action(...):       # business logic (runs only if allowed)
```

Decorators are applied bottom-up, executed top-down.

### Execution Flow

```
1. pre_check(**kwargs)          → if string returned, deny immediately
2. agent()                      → resolve VinculAgentContext
3. namespace                    → resolve (static or callable)
4. find_scope(ns, action_type)  → if None, deny with SCOPE_INVALID
5. action_params                → build action["params"]
6. runtime.commit(action, ...)  → 7-step enforcement pipeline
7. ToolResult(...)              → wrap receipt, auto-attest
8. on_result(tr, at, kwargs)    → callback, merge extra into response
9a. FAILURE → JSON {"status": "denied", "failure_code", "message", "hint", ...extra}
9b. SUCCESS → on_commit(receipt), call business logic,
              JSON {"status": "success", "action_type", "receipt_hash", ...payload, ...extra}
```

### Return Format

Always a JSON string. On success:

```json
{
    "status": "success",
    "action_type": "COMMIT",
    "receipt_hash": "abc123...",
    "...": "...business payload merged..."
}
```

On failure:

```json
{
    "status": "denied",
    "failure_code": "SCOPE_EXCEEDED",
    "message": "Field 'params.quantity' exceeds ceiling",
    "hint": "Your proposed values violate scope constraints. Try different values."
}
```

### Example

```python
@tool(name="propose_terms")
@vincul_enforce(
    action_type=OperationType.PROPOSE,
    tool_id="demo:propose",
    agent=lambda: agents[current_principal],
    namespace=lambda category, **_: f"terms.{category}",
    action_params="params",
    pre_check=lambda **kw: check_agreed(kw.get("category", "")),
)
def propose_terms(category: str, params: dict, rationale: str) -> dict:
    """Business logic — only runs if enforcement passes."""
    return {"category": category, "params": params}
```

---

## When to Use Each Pattern

### @vincul_tool + @vincul_tool_action

The tool provider controls enforcement. The caller passes `scope_id` explicitly. Use when multiple untrusted agents invoke the same tool — the tool is the trust boundary.

**Typical setup:** Cross-vendor marketplace, API service.

### @vincul_agent + @vincul_agent_action

The agent routes calls to tools with authority auto-injection. The tool still enforces, but the agent manages scope selection. Use when a programmatic agent invokes tools on behalf of a principal.

**Typical setup:** Marketplace buyer agent, automated workflow.

### @vincul_enforce + VinculAgentContext

Enforcement is in the decorator, not the tool. The LLM never sees scopes, contracts, or authority params. Use when an LLM decides which tools to call — enforcement must be invisible and non-bypassable.

**Typical setup:** LLM-powered agent (Strands, LangChain) with governed tool access.

---

`CC0 1.0 Universal — No rights reserved.`
