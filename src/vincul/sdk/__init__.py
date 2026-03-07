"""vincul.sdk — High-level SDK for building vincul agents and tools.

Reduces onboarding boilerplate by providing:
  - VinculContext: one-stop coalition setup (principals, contracts, scopes)
  - @vincul_tool / @tool_operation: decorators for tool providers
  - @vincul_agent / @agent_action: decorators for agents
  - ToolResult: unified return type from decorated operations
"""

from vincul.sdk.context import VinculContext
from vincul.sdk.decorators import ToolResult, tool_operation, vincul_tool
from vincul.sdk.agent import agent_action, vincul_agent

__all__ = [
    "VinculContext",
    "ToolResult",
    "tool_operation",
    "vincul_tool",
    "agent_action",
    "vincul_agent",
]
