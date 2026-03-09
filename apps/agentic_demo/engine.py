"""Agentic demo engine — runs LLM agents under Vincul governance over VinculNet.

Uses Strands Agents SDK with Bedrock. Each agent turn calls Claude via Strands
with custom tools that enforce actions through Vincul's 7-step pipeline and
broadcast receipts over VinculNet.
"""

from __future__ import annotations

import asyncio
import copy
import json
import logging
from dataclasses import dataclass, field
from typing import Any

from botocore.config import Config as BotocoreConfig
from strands import Agent, tool
from strands.models.bedrock import BedrockModel

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
class ModelConfig:
    """Bedrock model configuration."""
    model_id: str = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
    region_name: str = "us-west-2"
    temperature: float = 0.7
    max_tokens: int = 1024
    connect_timeout: int = 120
    read_timeout: int = 120
    max_retries: int = 5


@dataclass
class NegotiationEvent:
    """A single event in the negotiation timeline."""
    agent_id: str
    event_type: str  # "proposal", "acceptance", "denial", "message", "agreed", "deal_closed"
    category: str | None = None
    params: dict | None = None
    rationale: str | None = None
    message: str | None = None
    failure_code: str | None = None
    failure_message: str | None = None
    receipt_hash: str | None = None


class NegotiationEngine:
    """Orchestrates multi-agent negotiation under Vincul governance."""

    def __init__(
        self,
        agents: list[AgentConfig],
        contract_purpose: str,
        contract_description: str,
        max_rounds: int = 10,
        model_config: ModelConfig | None = None,
    ) -> None:
        self.agent_configs = {a.principal_id: a for a in agents}
        self.contract_purpose = contract_purpose
        self.contract_description = contract_description
        self.max_rounds = max_rounds
        self.model_config = model_config or ModelConfig()

        self.ctx: VinculContext | None = None
        self.contract = None
        self.peers: dict[str, ProtocolPeer] = {}
        self.keypairs: dict[str, KeyPair] = {}
        self.scopes: dict[str, list[Scope]] = {}  # principal_id -> scopes
        self.timeline: list[NegotiationEvent] = []
        self._received_receipts: dict[str, list[tuple[str, Receipt]]] = {}
        self._event_callbacks: list = []
        self._receipt_callbacks: list = []

        # COMMIT tracking
        self._commits: dict[str, dict[str, dict]] = {}
        self._agreed: dict[str, dict] = {}
        self._commit_authorities: dict[str, set[str]] = {}
        # Enriched system prompts built after setup
        self._system_prompts: dict[str, str] = {}
        # Strands Agent instances per principal
        self._agents: dict[str, Agent] = {}
        # Current principal context for tool dispatch
        self._current_principal: str | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    def on_event(self, callback) -> None:
        self._event_callbacks.append(callback)

    def on_receipt_exchange(self, callback) -> None:
        self._receipt_callbacks.append(callback)

    def _emit_event(self, event: NegotiationEvent) -> None:
        self.timeline.append(event)
        for cb in self._event_callbacks:
            cb(event)

    def _emit_receipt(self, receiver: str, sender: str, receipt_hash: str) -> None:
        for cb in self._receipt_callbacks:
            cb(receiver, sender, receipt_hash)

    # ── Tools (Strands @tool decorated) ──────────────────────

    def _make_tools(self):
        """Create tool functions bound to this engine instance."""
        engine = self

        @tool(name="propose_terms")
        def propose_terms(
            category: str,
            params: dict,
            rationale: str,
        ) -> str:
            """Propose terms to other parties (non-binding).

            Args:
                category: Term category. One of: valuation, equity, board, vesting, liquidation, technical.
                params: Proposed values. Use exact field names: valuation: {pre_money_valuation}; equity: {founder_equity_pct, investor_equity_pct}; board: {founder_board_seats, investor_board_seats}; vesting: {vesting_years, cliff_months}; liquidation: {liquidation_preference}.
                rationale: Brief explanation of why you're proposing these terms.
            """
            result = engine._sync_handle_tool_call(
                engine._current_principal, "propose_terms",
                {"category": category, "params": params, "rationale": rationale},
            )
            return json.dumps(result)

        @tool(name="accept_terms")
        def accept_terms(
            category: str,
            params: dict,
            rationale: str,
        ) -> str:
            """Commit to terms (binding — locks your position). Only use when ready to agree.

            Args:
                category: Term category. One of: valuation, equity, board, vesting, liquidation, technical.
                params: Exact terms to commit. Use exact field names: valuation: {pre_money_valuation}; equity: {founder_equity_pct, investor_equity_pct}; board: {founder_board_seats, investor_board_seats}; vesting: {vesting_years, cliff_months}; liquidation: {liquidation_preference}.
                rationale: Brief explanation of why you're accepting.
            """
            result = engine._sync_handle_tool_call(
                engine._current_principal, "accept_terms",
                {"category": category, "params": params, "rationale": rationale},
            )
            return json.dumps(result)

        @tool(name="send_message")
        def send_message(message: str) -> str:
            """Send a message to other negotiation parties. Use to discuss or explain position.

            Args:
                message: Your message to the other parties.
            """
            result = engine._sync_handle_tool_call(
                engine._current_principal, "send_message",
                {"message": message},
            )
            return json.dumps(result)

        return [propose_terms, accept_terms, send_message]

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

        # 3b. Build commit authority map
        for pid, scope_list in self.scopes.items():
            for scope in scope_list:
                if OperationType.COMMIT in scope.domain.types:
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

        # 5. Start VinculNet
        peer_ids = list(self.peers.keys())
        first_pid = peer_ids[0]
        first_port = self.agent_configs[first_pid].port
        await self.peers[first_pid].listen("localhost", first_port)
        print(f"\n  VinculNet: {first_pid} listening on port {first_port}")

        for pid in peer_ids[1:]:
            connected = await self.peers[pid].peer.connect(f"ws://localhost:{first_port}")
            print(f"  VinculNet: {pid} connected to {first_pid} (peer: {connected})")

        for i, pid_a in enumerate(peer_ids[1:], 1):
            port_a = self.agent_configs[pid_a].port
            await self.peers[pid_a].listen("localhost", port_a)
            for pid_b in peer_ids[i + 1:]:
                connected = await self.peers[pid_b].peer.connect(f"ws://localhost:{port_a}")
                print(f"  VinculNet: {pid_b} connected to {pid_a} (peer: {connected})")

        print(f"\n  Setup complete. {len(self.peers)} agents ready.")

        # 6. Build system prompts and Strands agents
        self._build_system_prompts()
        self._build_agents()

    def _build_system_prompts(self) -> None:
        """Build system prompts with contract rules and each agent's own authority."""
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
            my_scopes = []
            for scope in self.scopes.get(pid, []):
                ops = [t.value for t in scope.domain.types]
                ceiling = scope.ceiling if scope.ceiling != "TOP" else "no limit"
                my_scopes.append(f"  {scope.domain.namespace} [{','.join(ops)}] ceiling: {ceiling}")

            own_auth = "YOUR AUTHORITY:\n" + "\n".join(my_scopes)
            self._system_prompts[pid] = f"{config.system_prompt}\n\n{shared}\n\n{own_auth}"

    def _build_agents(self) -> None:
        """Create a Strands Agent per principal."""
        tools = self._make_tools()
        cfg = self.model_config

        for pid in self.agent_configs:
            model = BedrockModel(
                model_id=cfg.model_id,
                region_name=cfg.region_name,
                temperature=cfg.temperature,
                max_tokens=cfg.max_tokens,
                boto_client_config=BotocoreConfig(
                    connect_timeout=cfg.connect_timeout,
                    read_timeout=cfg.read_timeout,
                    retries={"max_attempts": cfg.max_retries, "mode": "adaptive"},
                ),
            )
            self._agents[pid] = Agent(
                model=model,
                tools=tools,
                system_prompt=self._system_prompts[pid],
            )

    # ── Run negotiation ───────────────────────────────────────

    async def run(self) -> None:
        """Run the negotiation for max_rounds rounds."""
        self._loop = asyncio.get_event_loop()

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
        if not self._commit_authorities:
            return False
        return all(cat in self._agreed for cat in self._commit_authorities)

    async def _agent_turn(self, principal_id: str, round_num: int) -> None:
        """Execute one turn for an agent using Strands."""
        config = self.agent_configs[principal_id]
        context = self._build_context(principal_id)

        print(f"\n  [{config.agent_id}] thinking...")

        # Set current principal so tools know who's calling
        self._current_principal = principal_id

        try:
            agent = self._agents[principal_id]
            # Strands handles the agentic loop (tool calls, retries) automatically
            result = await asyncio.to_thread(agent, context)

            # Extract text response
            text = str(result)
            if text.strip():
                print(f"\n  [{config.agent_id}] {text.strip()[:200]}")

            # Reset conversation for next turn
            agent.messages.clear()

        except Exception as e:
            print(f"\n  [{config.agent_id}] Agent error: {e}")
        finally:
            self._current_principal = None

    # ── Tool dispatch ─────────────────────────────────────────

    def _sync_handle_tool_call(
        self, principal_id: str, tool_name: str, tool_input: dict
    ) -> dict:
        """Synchronous wrapper for _handle_tool_call (called from Strands tools)."""
        future = asyncio.run_coroutine_threadsafe(
            self._handle_tool_call(principal_id, tool_name, tool_input),
            self._loop,
        )
        return future.result(timeout=30)

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

            if action_type == "COMMIT":
                if category not in self._commits:
                    self._commits[category] = {}
                self._commits[category][principal_id] = params

                required = self._commit_authorities.get(category, set())
                if required and required.issubset(self._commits.get(category, {}).keys()):
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
        op_type = OperationType(action_type)
        for scope in self.scopes.get(principal_id, []):
            if scope.domain.contains_namespace(namespace):
                if op_type in scope.domain.types:
                    return scope
        return None

    # ── Context building ──────────────────────────────────────

    def _build_context(self, principal_id: str) -> str:
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
        config = self.agent_configs[principal_id]
        print(f"  [{config.agent_id}] 📨 Receipt from {sender_id}: {receipt.receipt_hash[:20]}...")
        self._emit_receipt(principal_id, sender_id, receipt.receipt_hash[:32])

    # ── Summary ───────────────────────────────────────────────

    def _print_summary(self) -> None:
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
