"""Agentic demo engine — runs LLM agents under Vincul governance over VinculNet.

Uses Claude API directly with tool use. Each agent turn calls Claude with
custom tools that enforce actions through Vincul's 7-step pipeline and
broadcast receipts over VinculNet.
"""

from __future__ import annotations

import asyncio
import copy
import json
import logging
from dataclasses import dataclass
from typing import Any

import anthropic

from vincul.identity import KeyPair
from vincul.receipts import Receipt
from vincul.runtime import VinculRuntime
from vincul.sdk import VinculContext
from vincul.scopes import Scope
from vincul.transport.protocol_peer import ProtocolPeer
from vincul.types import Domain, OperationType

logger = logging.getLogger("vincul.agentic_demo")


@dataclass
class AgentConfig:
    """Configuration for a single negotiation agent."""
    principal_id: str
    agent_id: str
    system_prompt: str
    port: int
    scopes: list[dict[str, Any]]


@dataclass
class NegotiationEvent:
    """A single event in the negotiation timeline."""
    agent_id: str
    event_type: str  # "proposal", "acceptance", "denial", "message", "receipt"
    category: str | None = None
    params: dict | None = None
    rationale: str | None = None
    message: str | None = None
    failure_code: str | None = None
    failure_message: str | None = None
    receipt_hash: str | None = None


# Tool definitions for Claude API
TOOLS = [
    {
        "name": "propose_terms",
        "description": (
            "Propose a set of terms to the other parties. This is a PROPOSE action — "
            "it doesn't commit anyone. Specify the term category and your proposed values. "
            "IMPORTANT: The params object MUST use the exact field names listed below for "
            "ceiling validation to pass. Using other field names will cause rejection."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "enum": ["valuation", "equity", "board", "vesting", "liquidation", "technical"],
                    "description": "Which term category to propose on",
                },
                "params": {
                    "type": "object",
                    "description": (
                        "The proposed terms. You MUST use these exact field names per category: "
                        "valuation: {pre_money_valuation}; "
                        "equity: {founder_equity_pct, investor_equity_pct}; "
                        "board: {founder_board_seats, investor_board_seats}; "
                        "vesting: {vesting_years, cliff_months}; "
                        "liquidation: {liquidation_preference}."
                    ),
                    "properties": {
                        "pre_money_valuation": {
                            "type": "number",
                            "description": "Pre-money valuation amount. Required for ceiling validation in the valuation category.",
                        },
                        "founder_equity_pct": {
                            "type": "number",
                            "description": "Founder equity percentage. Required for ceiling validation in the equity category.",
                        },
                        "investor_equity_pct": {
                            "type": "number",
                            "description": "Investor equity percentage. Required for ceiling validation in the equity category.",
                        },
                        "founder_board_seats": {
                            "type": "integer",
                            "description": "Number of founder board seats. Required for ceiling validation in the board category.",
                        },
                        "investor_board_seats": {
                            "type": "integer",
                            "description": "Number of investor board seats. Required for ceiling validation in the board category.",
                        },
                        "vesting_years": {
                            "type": "number",
                            "description": "Vesting period in years. Required for ceiling validation in the vesting category.",
                        },
                        "cliff_months": {
                            "type": "integer",
                            "description": "Cliff period in months. Required for ceiling validation in the vesting category.",
                        },
                        "liquidation_preference": {
                            "type": "number",
                            "description": "Liquidation preference multiplier. Required for ceiling validation in the liquidation category.",
                        },
                    },
                },
                "rationale": {
                    "type": "string",
                    "description": "Brief explanation of why you're proposing these terms",
                },
            },
            "required": ["category", "params", "rationale"],
        },
    },
    {
        "name": "accept_terms",
        "description": (
            "Accept and commit to a set of terms. This is a COMMIT action — "
            "it binds your principal. Only use when you're ready to agree. "
            "IMPORTANT: The params object MUST use the exact field names listed below for "
            "ceiling validation to pass. Using other field names will cause rejection."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "enum": ["valuation", "equity", "board", "vesting", "liquidation", "technical"],
                    "description": "Which term category to accept",
                },
                "params": {
                    "type": "object",
                    "description": (
                        "The exact terms being accepted. You MUST use these exact field names per category: "
                        "valuation: {pre_money_valuation}; "
                        "equity: {founder_equity_pct, investor_equity_pct}; "
                        "board: {founder_board_seats, investor_board_seats}; "
                        "vesting: {vesting_years, cliff_months}; "
                        "liquidation: {liquidation_preference}."
                    ),
                    "properties": {
                        "pre_money_valuation": {
                            "type": "number",
                            "description": "Pre-money valuation amount. Required for ceiling validation in the valuation category.",
                        },
                        "founder_equity_pct": {
                            "type": "number",
                            "description": "Founder equity percentage. Required for ceiling validation in the equity category.",
                        },
                        "investor_equity_pct": {
                            "type": "number",
                            "description": "Investor equity percentage. Required for ceiling validation in the equity category.",
                        },
                        "founder_board_seats": {
                            "type": "integer",
                            "description": "Number of founder board seats. Required for ceiling validation in the board category.",
                        },
                        "investor_board_seats": {
                            "type": "integer",
                            "description": "Number of investor board seats. Required for ceiling validation in the board category.",
                        },
                        "vesting_years": {
                            "type": "number",
                            "description": "Vesting period in years. Required for ceiling validation in the vesting category.",
                        },
                        "cliff_months": {
                            "type": "integer",
                            "description": "Cliff period in months. Required for ceiling validation in the vesting category.",
                        },
                        "liquidation_preference": {
                            "type": "number",
                            "description": "Liquidation preference multiplier. Required for ceiling validation in the liquidation category.",
                        },
                    },
                },
                "rationale": {
                    "type": "string",
                    "description": "Brief explanation of why you're accepting",
                },
            },
            "required": ["category", "params", "rationale"],
        },
    },
    {
        "name": "send_message",
        "description": (
            "Send a message to the other negotiation parties. "
            "Use this to discuss, ask questions, or explain your position."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "message": {
                    "type": "string",
                    "description": "Your message to the other parties",
                },
            },
            "required": ["message"],
        },
    },
]


class NegotiationEngine:
    """Orchestrates multi-agent negotiation under Vincul governance."""

    def __init__(
        self,
        agents: list[AgentConfig],
        contract_purpose: str,
        contract_description: str,
        max_rounds: int = 10,
    ) -> None:
        self.agent_configs = {a.principal_id: a for a in agents}
        self.contract_purpose = contract_purpose
        self.contract_description = contract_description
        self.max_rounds = max_rounds

        self.client = anthropic.Anthropic()
        self.ctx: VinculContext | None = None
        self.contract = None
        self.peers: dict[str, ProtocolPeer] = {}
        self.keypairs: dict[str, KeyPair] = {}
        self.scopes: dict[str, list[Scope]] = {}  # principal_id -> scopes
        self.timeline: list[NegotiationEvent] = []
        self._received_receipts: dict[str, list[tuple[str, Receipt]]] = {}
        self._event_callbacks: list = []
        self._receipt_callbacks: list = []

        # COMMIT tracking: category -> {principal_id: params}
        self._commits: dict[str, dict[str, dict]] = {}
        # Agreed categories: category -> agreed params
        self._agreed: dict[str, dict] = {}
        # Which principals can COMMIT on each category
        self._commit_authorities: dict[str, set[str]] = {}
        # Enriched system prompts built after setup
        self._system_prompts: dict[str, str] = {}

    def on_event(self, callback) -> None:
        """Register a callback for negotiation events."""
        self._event_callbacks.append(callback)

    def on_receipt_exchange(self, callback) -> None:
        """Register a callback for receipt exchanges."""
        self._receipt_callbacks.append(callback)

    def _emit_event(self, event: NegotiationEvent) -> None:
        """Append event to timeline and notify callbacks."""
        self.timeline.append(event)
        for cb in self._event_callbacks:
            cb(event)

    def _emit_receipt(self, receiver: str, sender: str, receipt_hash: str) -> None:
        """Notify receipt exchange callbacks."""
        for cb in self._receipt_callbacks:
            cb(receiver, sender, receipt_hash)

    # ── Setup ─────────────────────────────────────────────────

    async def setup(self) -> None:
        """Initialize contracts, scopes, peers, and VinculNet connections."""
        print("\n" + "=" * 70)
        print("  SETUP: Initializing Vincul governance + VinculNet")
        print("=" * 70)

        # 1. Create context and register principals
        self.ctx = VinculContext()
        for pid, config in self.agent_configs.items():
            key = self.ctx.add_principal(
                pid,
                role="negotiator",
                permissions=["delegate", "commit", "revoke"],
            )
            self.keypairs[pid] = key
            print(f"  Registered: {pid}")

        # 2. Create contract
        self.contract = self.ctx.create_contract(
            purpose_title=self.contract_purpose,
            purpose_description=self.contract_description,
        )
        print(f"  Contract: {self.contract.contract_id[:20]}... ({self.contract.status.value})")

        # 3. Create scopes for each agent
        for pid, config in self.agent_configs.items():
            self.scopes[pid] = []
            for scope_def in config.scopes:
                from vincul.receipts import new_uuid, now_utc
                scope = Scope(
                    id=new_uuid(),
                    issued_by_scope_id=None,
                    issued_by=pid,
                    issued_at=now_utc(),
                    expires_at="2027-01-01T00:00:00Z",
                    domain=Domain(
                        namespace=scope_def["namespace"],
                        types=tuple(scope_def["operations"]),
                    ),
                    predicate=scope_def.get("ceiling", "TOP"),
                    ceiling=scope_def.get("ceiling", "TOP"),
                    delegate=scope_def.get("delegate", False),
                    revoke="principal_only",
                )
                self.ctx.runtime.scopes.add(scope)
                self.scopes[pid].append(scope)
                ops = [t.value for t in scope_def["operations"]]
                print(f"  Scope: {pid} -> {scope_def['namespace']} [{', '.join(ops)}] ceiling={scope_def.get('ceiling', 'TOP')}")

        # 3b. Build commit authority map: which principals can COMMIT on which categories
        for pid, scope_list in self.scopes.items():
            for scope in scope_list:
                if OperationType.COMMIT in scope.domain.types:
                    # Extract category from namespace (e.g., "terms.valuation" -> "valuation")
                    ns = scope.domain.namespace
                    category = ns.split(".")[-1] if "." in ns else ns
                    if category not in self._commit_authorities:
                        self._commit_authorities[category] = set()
                    self._commit_authorities[category].add(pid)

        # 4. Create ProtocolPeers with independent runtimes
        base_runtime = self.ctx.runtime
        for i, (pid, config) in enumerate(self.agent_configs.items()):
            peer = ProtocolPeer(pid, self.keypairs[pid])
            if i == 0:
                peer.runtime = base_runtime
            else:
                peer.runtime = _replicate_runtime(base_runtime)
            self.peers[pid] = peer
            self._received_receipts[pid] = []

            def _make_handler(principal_id):
                def handler(sender_id, receipt):
                    self._received_receipts[principal_id].append((sender_id, receipt))
                    self._on_receipt_received(principal_id, sender_id, receipt)
                return handler
            peer.on_receipt(_make_handler(pid))

        # 5. Start VinculNet — each peer listens on its port, connects to others
        peer_ids = list(self.peers.keys())

        # First peer listens
        first_pid = peer_ids[0]
        first_port = self.agent_configs[first_pid].port
        await self.peers[first_pid].listen("localhost", first_port)
        print(f"\n  VinculNet: {first_pid} listening on port {first_port}")

        # Others connect to first peer
        for pid in peer_ids[1:]:
            connected = await self.peers[pid].peer.connect(f"ws://localhost:{first_port}")
            print(f"  VinculNet: {pid} connected to {first_pid} (peer: {connected})")

        # Cross-connect remaining peers
        for i, pid_a in enumerate(peer_ids[1:], 1):
            port_a = self.agent_configs[pid_a].port
            await self.peers[pid_a].listen("localhost", port_a)
            for pid_b in peer_ids[i + 1:]:
                connected = await self.peers[pid_b].peer.connect(f"ws://localhost:{port_a}")
                print(f"  VinculNet: {pid_b} connected to {pid_a} (peer: {connected})")

        print(f"\n  Setup complete. {len(self.peers)} agents ready.")

        # 6. Build enriched system prompts with contract rules
        self._build_system_prompts()

    def _build_system_prompts(self) -> None:
        """Build system prompts with contract rules and each agent's own authority."""
        # Shared rules (compact)
        commit_rules = []
        for cat, principals in self._commit_authorities.items():
            names = [self.agent_configs[p].agent_id for p in principals]
            commit_rules.append(f"  {cat}: {' + '.join(names)}")

        shared = (
            "NEGOTIATION RULES:\n"
            "- propose_terms = non-binding suggestion\n"
            "- accept_terms = binding COMMIT that locks your position\n"
            "- A category is AGREED only when ALL required parties commit the EXACT SAME terms\n"
            "- If your commit is denied, you'll see the error — adjust and retry\n\n"
            "WHO MUST COMMIT per category:\n" + "\n".join(commit_rules) + "\n\n"
            "PARAM NAMES (use exactly):\n"
            "  valuation: pre_money_valuation | equity: founder_equity_pct, investor_equity_pct\n"
            "  board: founder_board_seats, investor_board_seats | vesting: vesting_years, cliff_months\n"
            "  liquidation: liquidation_preference"
        )

        for pid, config in self.agent_configs.items():
            # Agent's own authority
            my_scopes = []
            for scope in self.scopes.get(pid, []):
                ops = [t.value for t in scope.domain.types]
                ceiling = scope.ceiling if scope.ceiling != "TOP" else "no limit"
                my_scopes.append(f"  {scope.domain.namespace} [{','.join(ops)}] ceiling: {ceiling}")

            own_auth = "YOUR AUTHORITY:\n" + "\n".join(my_scopes)

            self._system_prompts[pid] = f"{config.system_prompt}\n\n{shared}\n\n{own_auth}"

    # ── Run negotiation ───────────────────────────────────────

    async def run(self) -> None:
        """Run the negotiation for max_rounds rounds."""
        print("\n" + "=" * 70)
        print("  NEGOTIATION START")
        print("=" * 70)

        agent_order = list(self.agent_configs.keys())

        for round_num in range(1, self.max_rounds + 1):
            print(f"\n{'─' * 70}")
            print(f"  ROUND {round_num}")
            print(f"{'─' * 70}")

            for pid in agent_order:
                await self._agent_turn(pid, round_num)
                await asyncio.sleep(0.1)

            # Check if all negotiable categories are agreed
            if self._all_agreed():
                print(f"\n  🎉 All categories agreed — deal closed!")
                self._emit_event(NegotiationEvent(
                    agent_id="system",
                    event_type="deal_closed",
                    message="All categories have been agreed upon. Deal closed!",
                ))
                break

        print("\n" + "=" * 70)
        print("  NEGOTIATION COMPLETE")
        print("=" * 70)
        self._print_summary()

    def _all_agreed(self) -> bool:
        """Check if all categories with commit authorities are agreed."""
        if not self._commit_authorities:
            return False
        return all(
            cat in self._agreed
            for cat in self._commit_authorities
        )

    async def _agent_turn(self, principal_id: str, round_num: int) -> None:
        """Execute one turn for an agent using Claude API with tool use.

        Runs a proper agentic loop: if Claude makes tool calls, the results
        are fed back so the agent can see denials and adjust its strategy.
        """
        config = self.agent_configs[principal_id]
        context = self._build_context(principal_id)
        max_iterations = 5  # prevent runaway loops

        messages = [{"role": "user", "content": context}]

        print(f"\n  [{config.agent_id}] thinking...")

        try:
            for _ in range(max_iterations):
                response = self.client.messages.create(
                    model="claude-sonnet-4-5-20250929",
                    max_tokens=1024,
                    system=self._system_prompts[principal_id],
                    tools=TOOLS,
                    messages=messages,
                )

                # Process text blocks
                for block in response.content:
                    if block.type == "text" and block.text.strip():
                        print(f"\n  [{config.agent_id}] {block.text.strip()}")

                # If Claude is done (no more tool calls), break
                if response.stop_reason == "end_turn":
                    break

                # Collect tool calls and execute them
                tool_use_blocks = [b for b in response.content if b.type == "tool_use"]
                if not tool_use_blocks:
                    break

                # Append assistant response to conversation
                messages.append({"role": "assistant", "content": response.content})

                # Execute each tool and collect results
                tool_results = []
                for tool_block in tool_use_blocks:
                    result = await self._handle_tool_call(
                        principal_id, tool_block.name, tool_block.input
                    )
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tool_block.id,
                        "content": json.dumps(result),
                        "is_error": result.get("status") == "denied",
                    })

                # Feed results back to Claude so it can see denials and adjust
                messages.append({"role": "user", "content": tool_results})

        except Exception as e:
            print(f"\n  [{config.agent_id}] Agent error: {e}")

    async def _handle_tool_call(
        self, principal_id: str, tool_name: str, tool_input: dict
    ) -> dict:
        """Handle a tool call from an agent, enforce via Vincul."""
        config = self.agent_configs[principal_id]
        category = tool_input.get("category", "")
        params = tool_input.get("params", {})
        rationale = tool_input.get("rationale", "")

        if tool_name == "send_message":
            message = tool_input.get("message", "")
            print(f"\n  [{config.agent_id}] 💬 {message}")
            event = NegotiationEvent(
                agent_id=config.agent_id,
                event_type="message",
                message=message,
            )
            self._emit_event(event)
            payload = {"type": "message", "sender": config.agent_id, "message": message}
            for peer_id in self.peers[principal_id].peer.registry.all_peers():
                await self.peers[principal_id].peer.send(peer_id, payload)
            return {"status": "sent", "message": "Message delivered to all parties"}

        # propose_terms or accept_terms
        namespace = f"terms.{category}"
        action_type = "PROPOSE" if tool_name == "propose_terms" else "COMMIT"

        # Block actions on already-agreed categories
        if category in self._agreed:
            msg = f"Category '{category}' is already agreed upon: {json.dumps(self._agreed[category])}. No further changes allowed."
            print(f"\n  [{config.agent_id}] ⛔ {action_type} {category}: ALREADY AGREED")
            event = NegotiationEvent(
                agent_id=config.agent_id,
                event_type="denial",
                category=category,
                params=params,
                rationale=rationale,
                failure_code="ALREADY_AGREED",
                failure_message=msg,
            )
            self._emit_event(event)
            return {"status": "denied", "failure_code": "ALREADY_AGREED", "message": msg}

        scope = self._find_scope(principal_id, namespace, action_type)
        if scope is None:
            failure_msg = (
                f"No authority to {action_type} on {namespace}. "
                f"You may not have a scope for this namespace or action type."
            )
            print(f"\n  [{config.agent_id}] ❌ DENIED {action_type} {category}: NO SCOPE")
            event = NegotiationEvent(
                agent_id=config.agent_id,
                event_type="denial",
                category=category,
                params=params,
                rationale=rationale,
                failure_code="NO_SCOPE",
                failure_message=failure_msg,
            )
            self._emit_event(event)
            return {"status": "denied", "failure_code": "NO_SCOPE", "message": failure_msg}

        action = {
            "type": action_type,
            "namespace": namespace,
            "resource": f"{category}-proposal",
            "params": params,
        }

        peer = self.peers[principal_id]
        receipt = peer.runtime.commit(
            action=action,
            scope_id=scope.id,
            contract_id=self.contract.contract_id,
            initiated_by=principal_id,
        )

        if receipt.outcome == "success":
            label = "ACCEPTED" if action_type == "COMMIT" else "PROPOSED"
            emoji = "✅" if action_type == "COMMIT" else "📋"
            print(f"\n  [{config.agent_id}] {emoji} {label} {category}: {json.dumps(params)}")
            print(f"    Rationale: {rationale}")
            print(f"    Receipt: {receipt.receipt_hash[:32]}...")

            event = NegotiationEvent(
                agent_id=config.agent_id,
                event_type="acceptance" if action_type == "COMMIT" else "proposal",
                category=category,
                params=params,
                rationale=rationale,
                receipt_hash=receipt.receipt_hash,
            )
            self._emit_event(event)

            payload = {"type": "receipt", "receipt": receipt.to_dict()}
            for peer_id in peer.peer.registry.all_peers():
                await peer.peer.send(peer_id, payload)

            result_msg = f"{action_type} on {category} accepted and broadcast to all parties"

            # Track COMMITs and check for agreement
            if action_type == "COMMIT":
                if category not in self._commits:
                    self._commits[category] = {}
                self._commits[category][principal_id] = params

                # Check: have all principals with COMMIT authority committed to matching terms?
                required = self._commit_authorities.get(category, set())
                if required and required.issubset(self._commits.get(category, {}).keys()):
                    # Check all committed params match
                    committed_values = list(self._commits[category].values())
                    if all(v == committed_values[0] for v in committed_values[1:]):
                        self._agreed[category] = committed_values[0]
                        parties = [self.agent_configs[p].agent_id for p in required]
                        print(f"\n  🤝 AGREED on {category}: {json.dumps(committed_values[0])}")
                        print(f"     Parties: {', '.join(parties)}")
                        self._emit_event(NegotiationEvent(
                            agent_id="system",
                            event_type="agreed",
                            category=category,
                            params=committed_values[0],
                            message=f"All parties agreed on {category}! Terms locked.",
                        ))
                        result_msg += f". AGREED — all parties with authority have committed to the same terms on {category}. This category is now locked."
                    else:
                        # Show what others committed to so agent can align
                        other_commits = {
                            self.agent_configs[pid].agent_id: p
                            for pid, p in self._commits[category].items()
                            if pid != principal_id
                        }
                        result_msg += f". Note: other commits on {category}: {json.dumps(other_commits)}. Terms don't match yet — category not agreed."

            return {
                "status": "success",
                "action_type": action_type,
                "receipt_hash": receipt.receipt_hash[:32],
                "message": result_msg,
            }
        else:
            failure_code = receipt.detail.get("error_code", "UNKNOWN")
            failure_msg = receipt.detail.get("message", "Validation failed")
            print(f"\n  [{config.agent_id}] ❌ DENIED {action_type} {category}: {failure_code}")
            print(f"    {failure_msg}")
            print(f"    Attempted: {json.dumps(params)}")

            event = NegotiationEvent(
                agent_id=config.agent_id,
                event_type="denial",
                category=category,
                params=params,
                rationale=rationale,
                failure_code=failure_code,
                failure_message=failure_msg,
            )
            self._emit_event(event)

            return {
                "status": "denied",
                "failure_code": failure_code,
                "message": failure_msg,
                "hint": "Your proposed values violate your scope constraints. Try different values.",
            }

    def _find_scope(
        self, principal_id: str, namespace: str, action_type: str
    ) -> Scope | None:
        """Find a scope that authorizes this action for this principal."""
        op_type = OperationType(action_type)
        for scope in self.scopes.get(principal_id, []):
            if scope.domain.contains_namespace(namespace):
                if op_type in scope.domain.types:
                    return scope
        return None

    # ── Context building ──────────────────────────────────────

    def _build_context(self, principal_id: str) -> str:
        """Build a context summary for the agent."""
        parts = []

        if not self.timeline:
            parts.append("No actions yet — you go first. Make an opening proposal.")
        else:
            for event in self.timeline:
                if event.event_type == "proposal":
                    parts.append(f"- {event.agent_id} PROPOSED {event.category}: {json.dumps(event.params)}")
                elif event.event_type == "acceptance":
                    parts.append(f"- {event.agent_id} COMMITTED {event.category}: {json.dumps(event.params)}")
                elif event.event_type == "denial":
                    parts.append(f"- {event.agent_id} DENIED on {event.category}: {event.failure_code}")
                elif event.event_type == "message":
                    parts.append(f"- {event.agent_id}: \"{event.message}\"")
                elif event.event_type == "agreed":
                    parts.append(f"- AGREED {event.category}: {json.dumps(event.params)} [LOCKED]")

        if self._agreed:
            parts.append("\nLOCKED: " + ", ".join(self._agreed.keys()))

        pending = {c: d for c, d in self._commits.items() if c not in self._agreed and d}
        if pending:
            parts.append("\nPENDING COMMITS:")
            for cat, commits in pending.items():
                for pid, p in commits.items():
                    parts.append(f"  {self.agent_configs[pid].agent_id} on {cat}: {json.dumps(p)}")
                needed = self._commit_authorities.get(cat, set()) - commits.keys()
                if needed:
                    parts.append(f"  Still need: {', '.join(self.agent_configs[p].agent_id for p in needed)}")

        open_cats = [c for c in self._commit_authorities if c not in self._agreed]
        if open_cats:
            parts.append(f"\nOPEN: {', '.join(open_cats)}")

        parts.append("\nYour turn.")
        return "\n".join(parts)

    def _on_receipt_received(
        self, principal_id: str, sender_id: str, receipt: Receipt
    ) -> None:
        """Called when a receipt arrives over VinculNet."""
        config = self.agent_configs[principal_id]
        print(f"  [{config.agent_id}] 📨 Receipt from {sender_id}: {receipt.receipt_hash[:20]}...")
        self._emit_receipt(principal_id, sender_id, receipt.receipt_hash[:32])

    # ── Summary ───────────────────────────────────────────────

    def _print_summary(self) -> None:
        """Print final negotiation summary."""
        print(f"\n  Timeline: {len(self.timeline)} events")

        proposals = [e for e in self.timeline if e.event_type == "proposal"]
        acceptances = [e for e in self.timeline if e.event_type == "acceptance"]
        denials = [e for e in self.timeline if e.event_type == "denial"]
        messages = [e for e in self.timeline if e.event_type == "message"]

        print(f"    Proposals: {len(proposals)}")
        print(f"    Acceptances: {len(acceptances)}")
        print(f"    Denials: {len(denials)} (Vincul enforced)")
        print(f"    Messages: {len(messages)}")

        total_receipts = sum(len(r) for r in self._received_receipts.values())
        print(f"\n  VinculNet receipts exchanged: {total_receipts}")

        if acceptances:
            print(f"\n  Agreed terms:")
            for a in acceptances:
                print(f"    {a.category}: {json.dumps(a.params)}")

        if denials:
            print(f"\n  Vincul enforcements (denials):")
            for d in denials:
                print(f"    {d.agent_id} -> {d.category}: {d.failure_code}")

    # ── Cleanup ───────────────────────────────────────────────

    async def cleanup(self) -> None:
        """Stop all peers."""
        for peer in self.peers.values():
            await peer.stop()


def _replicate_runtime(source: VinculRuntime) -> VinculRuntime:
    """Create an independent runtime with identical state."""
    replica = VinculRuntime()

    for contract in source.contracts._contracts.values():
        cloned = copy.deepcopy(contract)
        replica.contracts._contracts[cloned.contract_id] = cloned

    for scope in source.scopes._scopes.values():
        cloned = copy.deepcopy(scope)
        replica.scopes._scopes[cloned.id] = cloned
        if cloned.issued_by_scope_id:
            parent_id = cloned.issued_by_scope_id
            if parent_id not in replica.scopes._children:
                replica.scopes._children[parent_id] = []
            replica.scopes._children[parent_id].append(cloned.id)

    for receipt in source.receipts.timeline():
        cloned = copy.deepcopy(receipt)
        replica.receipts.append(cloned)

    for key, value in source.budget._ceilings.items():
        replica.budget._ceilings[key] = value
    for key, value in source.budget._consumed.items():
        replica.budget._consumed[key] = copy.deepcopy(value)

    return replica
