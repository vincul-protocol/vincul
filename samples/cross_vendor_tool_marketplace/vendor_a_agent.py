"""Vendor A — Buyer Agent, built on vincul SDK decorators.

The @vincul_agent decorator handles:
  - Binding agent identity, contract, and scope
  - Injecting invoke() for calling tool operations

The @agent_action decorator handles:
  - Auto-routing to the correct tool operation
  - Injecting authority params (scope_id, contract_id, initiated_by)

The agent author writes only the action interface.
"""

from __future__ import annotations

from vincul.sdk import vincul_agent, agent_action, ToolResult

from .vendor_b_tool import VendorBToolProvider


VENDOR_A_ID = "vendor:VendorA"
VENDOR_B_ID = "vendor:VendorB"
VENDOR_C_ID = "vendor:VendorC"
AGENT_ID = "agent:VendorA:buyerAgent1"


@vincul_agent(agent_id=AGENT_ID)
class VendorABuyerAgent:
    """Vendor A's buyer agent. Only action interface — SDK handles the rest."""

    @agent_action(operation="place_order")
    def buy(self, tool_provider: VendorBToolProvider, *, item_id: str, quantity: int, shipping_zip: str) -> ToolResult:
        """Place an order through the tool provider."""
