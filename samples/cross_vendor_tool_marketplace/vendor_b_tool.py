"""Vendor B — Order Tool provider, built on vincul SDK decorators.

The @vincul_tool and @tool_operation decorators handle:
  - Tool manifest generation
  - Action dict construction
  - 7-step enforcement pipeline (runtime.commit)
  - Receipt emission (commitment or failure)
  - Signed attested result construction

The tool author writes only business logic.
"""

from __future__ import annotations

from vincul.identity import KeyPair
from vincul.runtime import VinculRuntime
from vincul.sdk import tool_operation, vincul_tool
from vincul.types import OperationType


VENDOR_B_ID = "vendor:VendorB"
TOOL_ID = "tool:VendorB:order-tool"
TOOL_VERSION = "0.1.0"
TOOL_NAMESPACE = "marketplace.orders"


@vincul_tool(namespace=TOOL_NAMESPACE, tool_id=TOOL_ID, tool_version=TOOL_VERSION)
class VendorBToolProvider:
    """Vendor B's tool host. Only business logic — SDK handles the rest."""

    def __init__(self, key_pair: KeyPair, runtime: VinculRuntime) -> None:
        self.key_pair = key_pair
        self.runtime = runtime
        self._order_counter = 0

    @tool_operation(action_type=OperationType.COMMIT, resource_key="item_id")
    def place_order(self, *, item_id: str, quantity: int, shipping_zip: str) -> dict:
        """Create an order (dummy side-effect)."""
        self._order_counter += 1
        order_id = f"order-demo-{self._order_counter:04d}"
        return {
            "order_id": order_id,
            "charged_amount_usd": round(12.34 * quantity, 2),
            "notes": "dummy order placed",
        }
