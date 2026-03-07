"""vincul.sdk.agent — @vincul_agent and @agent_action decorators.

Mirrors the tool-side decorators (@vincul_tool / @tool_operation) so that
both sides of a vincul coalition use the same annotation-driven pattern.

@vincul_agent: class decorator — binds agent identity, contract, and scope;
               injects invoke() for calling tool operations.

@agent_action: method decorator — auto-routes to a @tool_operation on a tool,
               injecting authority params (scope_id, contract_id, initiated_by).
"""

from __future__ import annotations

import functools
from typing import Any

from vincul.sdk.decorators import ToolResult


# ── @vincul_agent class decorator ─────────────────────────────

def vincul_agent(*, agent_id: str):
    """Class decorator for vincul agents.

    Wraps ``__init__`` to accept ``contract`` and ``scope`` as keyword args.
    Adds an ``invoke(tool, operation, **params)`` method that auto-injects
    authority params from the bound contract and scope.

    Example::

        @vincul_agent(agent_id="agent:VendorA:buyer1")
        class BuyerAgent:
            @agent_action(operation="place_order")
            def buy(self, tool, *, item_id, quantity, shipping_zip):
                \"\"\"Decorated — body is replaced by auto-invoke.\"\"\"

        agent = BuyerAgent(contract=contract, scope=leaf_scope)
        result = agent.buy(tool_provider, item_id="book-1", quantity=2, shipping_zip="10001")
    """

    def decorator(cls):
        cls._vincul_agent_id = agent_id

        orig_init = cls.__dict__.get("__init__")

        @functools.wraps(orig_init or object.__init__)
        def wrapped_init(self, *, contract, scope, **kwargs):
            self.agent_id = agent_id
            self.contract = contract
            self.scope = scope
            if orig_init:
                orig_init(self, **kwargs)

        cls.__init__ = wrapped_init

        def invoke(self, tool: Any, operation: str, **params: Any) -> ToolResult:
            """Invoke a @tool_operation on a tool, injecting authority params."""
            method = getattr(tool, operation)
            return method(
                scope_id=self.scope.id,
                contract_id=self.contract.contract_id,
                initiated_by=self.agent_id,
                **params,
            )

        cls.invoke = invoke

        return cls

    return decorator


# ── @agent_action method decorator ────────────────────────────

def agent_action(fn=None, *, operation: str | None = None):
    """Method decorator for agent actions.

    Auto-invokes ``tool.<operation>(**business_params)`` with authority
    params (scope_id, contract_id, initiated_by) injected from the
    agent's bound contract and scope.

    The first positional arg after ``self`` is the tool instance.
    Remaining keyword args are forwarded as business params.

    If ``operation`` is not specified, the method name is used.

    Example::

        @agent_action(operation="place_order")
        def buy(self, tool, *, item_id, quantity, shipping_zip):
            \"\"\"Auto-invokes tool.place_order(...) with authority injection.\"\"\"

        @agent_action  # operation defaults to method name
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
        # Called without parentheses: @agent_action
        return decorator(fn)
    return decorator
