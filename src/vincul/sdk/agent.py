"""vincul.sdk.agent — @vincul_agent and @vincul_agent_action decorators.

Mirrors the tool-side decorators (@vincul_tool / @vincul_tool_action) so that
both sides of a vincul coalition use the same annotation-driven pattern.

@vincul_agent: class decorator — binds agent identity, contract, and scope(s);
               injects invoke() for calling tool operations.

@vincul_agent_action: method decorator — auto-routes to a @vincul_tool_action on a tool,
               injecting authority params (scope_id, contract_id, initiated_by).
"""

from __future__ import annotations

import functools
from typing import Any

from vincul.sdk.decorators import ToolResult
from vincul.types import OperationType


# ── @vincul_agent class decorator ─────────────────────────────

def vincul_agent(*, agent_id: str):
    """Class decorator for vincul agents.

    Wraps ``__init__`` to accept ``contract`` and ``scopes`` (list).
    Adds ``invoke()``, ``find_scope()``, and a ``scope`` property.

    When multiple scopes are bound, ``invoke()`` auto-resolves the right
    scope from the tool's namespace and operation type metadata.

    Example::

        @vincul_agent(agent_id="agent:VendorA:buyer1")
        class BuyerAgent:
            @vincul_agent_action(operation="place_order")
            def buy(self, tool, *, item_id, quantity, shipping_zip):
                \"\"\"Decorated — body is replaced by auto-invoke.\"\"\"

        agent = BuyerAgent(contract=contract, scopes=[leaf_scope])
        result = agent.buy(tool_provider, item_id="book-1", quantity=2, shipping_zip="10001")
    """

    def decorator(cls):
        cls._vincul_agent_id = agent_id

        orig_init = cls.__dict__.get("__init__")

        @functools.wraps(orig_init or object.__init__)
        def wrapped_init(self, *, contract, scopes, **kwargs):
            self.agent_id = agent_id
            self.contract = contract
            self._scopes = list(scopes)
            if orig_init:
                orig_init(self, **kwargs)

        cls.__init__ = wrapped_init

        @property
        def _scope_prop(self):
            """First scope (backward compat for single-scope agents)."""
            return self._scopes[0] if self._scopes else None

        cls.scope = _scope_prop

        @property
        def _scopes_prop(self):
            """All scopes bound to this agent."""
            return self._scopes

        cls.scopes = _scopes_prop

        def find_scope(self, namespace: str, action_type: str):
            """Find a scope authorizing *action_type* on *namespace*."""
            op = OperationType(action_type)
            for scope in self._scopes:
                if op in scope.domain.types and scope.domain.contains_namespace(namespace):
                    return scope
            return None

        cls.find_scope = find_scope

        def invoke(self, tool: Any, operation: str, **params: Any) -> ToolResult:
            """Invoke a @vincul_tool_action on a tool, auto-resolving scope."""
            method = getattr(tool, operation)
            # Auto-resolve scope from tool metadata when multiple scopes exist
            namespace = getattr(tool, '_vincul_namespace', None)
            meta = getattr(method, '_vincul_op_meta', None)
            if namespace and meta and len(self._scopes) > 1:
                resolved = self.find_scope(namespace, meta['action_type'].value)
                if resolved is None:
                    raise ValueError(
                        f"No scope authorizing {meta['action_type'].value} on {namespace}"
                    )
                scope_id = resolved.id
            elif self._scopes:
                scope_id = self._scopes[0].id
            else:
                raise ValueError("No scopes bound to agent")
            return method(
                scope_id=scope_id,
                contract_id=self.contract.contract_id,
                initiated_by=self.agent_id,
                **params,
            )

        cls.invoke = invoke

        return cls

    return decorator


# ── @vincul_agent_action method decorator ────────────────────────────

def vincul_agent_action(fn=None, *, operation: str | None = None):
    """Method decorator for agent actions.

    Auto-invokes ``tool.<operation>(**business_params)`` with authority
    params (scope_id, contract_id, initiated_by) injected from the
    agent's bound contract and scopes.

    The first positional arg after ``self`` is the tool instance.
    Remaining keyword args are forwarded as business params.

    If ``operation`` is not specified, the method name is used.

    Example::

        @vincul_agent_action(operation="place_order")
        def buy(self, tool, *, item_id, quantity, shipping_zip):
            \"\"\"Auto-invokes tool.place_order(...) with authority injection.\"\"\"

        @vincul_agent_action  # operation defaults to method name
        def place_order(self, tool, *, item_id, quantity):
            \"\"\"Auto-invokes tool.place_order(...).\"\"\"
    """

    def decorator(fn):
        op_name = operation or fn.__name__

        @functools.wraps(fn)
        def wrapper(self, tool, **kwargs):
            return self.invoke(tool, op_name, **kwargs)

        wrapper._vincul_action_meta = {
            "name": fn.__name__,
            "operation": op_name,
        }
        return wrapper

    if fn is not None:
        # Called without parentheses: @vincul_agent_action
        return decorator(fn)
    return decorator
