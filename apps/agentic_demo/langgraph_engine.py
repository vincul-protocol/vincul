"""LangGraph framework backend for the negotiation engine."""

from __future__ import annotations

import asyncio
from typing import Any

from langchain_aws import ChatBedrock
from langchain_core.messages import SystemMessage
from langchain_core.tools import tool as langchain_tool
from langgraph.prebuilt import create_react_agent

from apps.agentic_demo.engine import NegotiationEngine


class LangGraphNegotiationEngine(NegotiationEngine):
    """Negotiation engine using LangGraph ReAct agents."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._langgraph_agents: dict[str, Any] = {}

    def _make_tools(self) -> list:
        propose_terms, accept_terms, send_message = self._make_raw_tools()
        return [
            langchain_tool(propose_terms),
            langchain_tool(accept_terms),
            langchain_tool(send_message),
        ]

    def _build_agents(self) -> None:
        tools = self._make_tools()
        cfg = self.model_config

        for pid in self.agent_configs:
            model = ChatBedrock(
                model_id=cfg.model_id,
                region_name=cfg.region_name,
                model_kwargs={
                    "temperature": cfg.temperature,
                    "max_tokens": cfg.max_tokens,
                },
            )
            self._langgraph_agents[pid] = create_react_agent(
                model=model,
                tools=tools,
            )

    async def _agent_turn(self, principal_id: str, round_num: int) -> None:
        config = self.agent_configs[principal_id]
        context = self._build_context(principal_id)

        print(f"\n  [{config.agent_id}] thinking...")
        self._current_principal = principal_id

        try:
            graph = self._langgraph_agents[principal_id]
            system_msg = SystemMessage(content=self._system_prompts[principal_id])

            result = await asyncio.to_thread(
                graph.invoke,
                {"messages": [system_msg, ("human", context)]},
            )

            messages = result.get("messages", [])
            if messages:
                last_msg = messages[-1]
                text = getattr(last_msg, "content", str(last_msg))
                if isinstance(text, str) and text.strip():
                    print(f"\n  [{config.agent_id}] {text.strip()[:200]}")

        except Exception as e:
            print(f"\n  [{config.agent_id}] Agent error: {e}")
        finally:
            self._current_principal = None
