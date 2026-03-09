"""Run the agentic term sheet negotiation demo.

Usage:
    python -m apps.agentic_demo.run [--rogue] [--rounds N]

Flags:
    --rogue   Use aggressive investor agent (demonstrates Vincul enforcement)
    --rounds  Number of negotiation rounds (default: 5)
"""

from __future__ import annotations

import argparse
import asyncio
import logging

from apps.agentic_demo.engine import AgentConfig, NegotiationEngine
from apps.agentic_demo.scenarios.term_sheet import (
    AGENT_A_ID,
    AGENT_B_ID,
    AGENT_INV_ID,
    CONTRACT_DESCRIPTION,
    CONTRACT_PURPOSE,
    FOUNDER_A_ID,
    FOUNDER_A_SCOPES,
    FOUNDER_B_ID,
    FOUNDER_B_SCOPES,
    INVESTOR_ID,
    INVESTOR_SCOPES,
    PORTS,
    ROGUE_SYSTEM_PROMPTS,
    SYSTEM_PROMPTS,
)


def main():
    parser = argparse.ArgumentParser(description="Vincul Agentic Demo — Term Sheet Negotiation")
    parser.add_argument("--rogue", action="store_true", help="Use aggressive investor agent")
    parser.add_argument("--rounds", type=int, default=5, help="Number of negotiation rounds")
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging")
    args = parser.parse_args()

    if args.verbose:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.WARNING)

    # Select system prompts
    investor_prompt = (
        ROGUE_SYSTEM_PROMPTS[INVESTOR_ID] if args.rogue
        else SYSTEM_PROMPTS[INVESTOR_ID]
    )

    mode = "ROGUE INVESTOR" if args.rogue else "COOPERATIVE"
    print(f"\n{'=' * 70}")
    print(f"  VINCUL AGENTIC DEMO — Term Sheet Negotiation")
    print(f"  Mode: {mode}")
    print(f"  Rounds: {args.rounds}")
    print(f"{'=' * 70}")

    agents = [
        AgentConfig(
            principal_id=FOUNDER_A_ID,
            agent_id=AGENT_A_ID,
            system_prompt=SYSTEM_PROMPTS[FOUNDER_A_ID],
            port=PORTS[FOUNDER_A_ID],
            scopes=FOUNDER_A_SCOPES,
        ),
        AgentConfig(
            principal_id=FOUNDER_B_ID,
            agent_id=AGENT_B_ID,
            system_prompt=SYSTEM_PROMPTS[FOUNDER_B_ID],
            port=PORTS[FOUNDER_B_ID],
            scopes=FOUNDER_B_SCOPES,
        ),
        AgentConfig(
            principal_id=INVESTOR_ID,
            agent_id=AGENT_INV_ID,
            system_prompt=investor_prompt,
            port=PORTS[INVESTOR_ID],
            scopes=INVESTOR_SCOPES,
        ),
    ]

    engine = NegotiationEngine(
        agents=agents,
        contract_purpose=CONTRACT_PURPOSE,
        contract_description=CONTRACT_DESCRIPTION,
        max_rounds=args.rounds,
    )

    asyncio.run(_run(engine))


async def _run(engine: NegotiationEngine) -> None:
    try:
        await engine.setup()
        await engine.run()
    finally:
        await engine.cleanup()


if __name__ == "__main__":
    main()
