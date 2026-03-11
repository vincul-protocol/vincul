"""Strands Agents framework backend for the negotiation engine."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from botocore.config import Config as BotocoreConfig
from strands import Agent, tool

from apps.agentic_demo.engine import ModelConfig, NegotiationEngine


@dataclass
class StrandsModelConfig(ModelConfig):
    """Strands-specific model config with timeout/retry settings."""
    connect_timeout: int = 120
    read_timeout: int = 120
    max_retries: int = 5


class StrandsNegotiationEngine(NegotiationEngine):
    """Negotiation engine using Strands Agents SDK."""

    def __init__(self, **kwargs) -> None:
        if kwargs.get("model_config") is None:
            kwargs["model_config"] = StrandsModelConfig()
        super().__init__(**kwargs)
        self._strands_agents: dict[str, Agent] = {}

    def _make_tools(self) -> list:
        propose_terms, accept_terms, send_message = self._make_raw_tools()
        return [
            tool(name="propose_terms")(propose_terms),
            tool(name="accept_terms")(accept_terms),
            tool(name="send_message")(send_message),
        ]

    def _build_agents(self) -> None:
        tools = self._make_tools()
        cfg = self.model_config

        from strands.models.bedrock import BedrockModel

        boto_kwargs = {}
        if isinstance(cfg, StrandsModelConfig):
            boto_kwargs = {
                "connect_timeout": cfg.connect_timeout,
                "read_timeout": cfg.read_timeout,
                "retries": {"max_attempts": cfg.max_retries, "mode": "adaptive"},
            }

        for pid in self.agent_configs:
            model = BedrockModel(
                model_id=cfg.model_id,
                region_name=cfg.region_name,
                temperature=cfg.temperature,
                max_tokens=cfg.max_tokens,
                boto_client_config=BotocoreConfig(**boto_kwargs) if boto_kwargs else None,
            )
            self._strands_agents[pid] = Agent(
                model=model,
                tools=tools,
                system_prompt=self._system_prompts[pid],
            )

    async def _agent_turn(self, principal_id: str, round_num: int) -> None:
        config = self.agent_configs[principal_id]
        context = self._build_context(principal_id)

        print(f"\n  [{config.agent_id}] thinking...")
        self._current_principal = principal_id

        try:
            agent = self._strands_agents[principal_id]
            result = await asyncio.to_thread(agent, context)

            text = str(result)
            if text.strip():
                print(f"\n  [{config.agent_id}] {text.strip()[:200]}")

            agent.messages.clear()
        except Exception as e:
            print(f"\n  [{config.agent_id}] Agent error: {e}")
        finally:
            self._current_principal = None
