"""Agentic demo engine — base class for multi-agent negotiation under Vincul governance.

Framework-specific subclasses (Strands, LangGraph) override three methods:
  _make_tools()   — wrap raw tools with the framework's decorator
  _build_agents() — create framework-specific agent instances
  _agent_turn()   — invoke the framework agent for one turn
"""

from __future__ import annotations

import asyncio
import copy
import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from vincul.identity import KeyPair
from vincul.receipts import Receipt, new_uuid, now_utc
from vincul.sdk import VinculContext, ToolResult, VinculAgentContext, vincul_enforce
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


class NegotiationEngine(ABC):
    """Orchestrates multi-agent negotiation under Vincul governance.

    Subclasses provide framework-specific tool construction, agent building,
    and turn execution.
    """

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
        # VinculAgentContext per principal
        self._vincul_agents: dict[str, VinculAgentContext] = {}
        # Current principal context for tool dispatch
        self._current_principal: str | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    # ── Abstract methods (framework-specific) ──────────────

    @abstractmethod
    def _make_tools(self) -> list:
        """Create framework-wrapped tool functions."""

    @abstractmethod
    def _build_agents(self) -> None:
        """Create framework-specific agent instances per principal."""

    @abstractmethod
    async def _agent_turn(self, principal_id: str, round_num: int) -> None:
        """Execute one agent turn using the framework."""

    # ── Event callbacks ────────────────────────────────────

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

    # ── Shared tool creation ───────────────────────────────

    def _make_raw_tools(self):
        """Create tool functions with @vincul_enforce applied but no framework decorator.

        Returns (propose_terms, accept_terms, send_message) — ready to be
        wrapped by the subclass's framework decorator.
        """
        engine = self

        @vincul_enforce(
            action_type=OperationType.PROPOSE,
            tool_id="agentic_demo:propose_terms",
            agent=lambda: engine._vincul_agents[engine._current_principal],
            namespace=lambda category, **_: f"terms.{category}",
            action_params="params",
            pre_check=lambda **kw: engine._check_agreed(kw.get("category", "")),
        )
        def propose_terms(
            category: str,
            params: dict,
            rationale: str,
        ) -> dict:
            """Propose terms to other parties (non-binding).

            Args:
                category: Term category. One of: valuation, equity, board, vesting, liquidation, technical.
                params: Proposed values. Use exact field names: valuation: {pre_money_valuation}; equity: {founder_equity_pct, investor_equity_pct}; board: {founder_board_seats, investor_board_seats}; vesting: {vesting_years, cliff_months}; liquidation: {liquidation_preference}.
                rationale: Brief explanation of why you're proposing these terms.
            """
            return {"category": category, "params": params}

        @vincul_enforce(
            action_type=OperationType.COMMIT,
            tool_id="agentic_demo:accept_terms",
            agent=lambda: engine._vincul_agents[engine._current_principal],
            namespace=lambda category, **_: f"terms.{category}",
            action_params="params",
            pre_check=lambda **kw: engine._check_agreed(kw.get("category", "")),
        )
        def accept_terms(
            category: str,
            params: dict,
            rationale: str,
        ) -> dict:
            """Commit to terms (binding — locks your position). Only use when ready to agree.

            Args:
                category: Term category. One of: valuation, equity, board, vesting, liquidation, technical.
                params: Exact terms to commit. Use exact field names: valuation: {pre_money_valuation}; equity: {founder_equity_pct, investor_equity_pct}; board: {founder_board_seats, investor_board_seats}; vesting: {vesting_years, cliff_months}; liquidation: {liquidation_preference}.
                rationale: Brief explanation of why you're accepting.
            """
            return {"category": category, "params": params}

        def send_message(message: str) -> str:
            """Send a message to other negotiation parties. Use to discuss or explain position.

            Args:
                message: Your message to the other parties.
            """
            pid = engine._current_principal
            config = engine.agent_configs[pid]
            print(f"\n  [{config.agent_id}] 💬 {message}")
            engine._emit_event(NegotiationEvent(
                agent_id=config.agent_id,
                event_type="message",
                message=message,
            ))
            engine._broadcast_message(pid, message)
            return json.dumps({"status": "sent", "message": "Message delivered to all parties"})

        return propose_terms, accept_terms, send_message

    # ── Callbacks for @vincul_enforce ──────────────────────

    def _check_agreed(self, category: str) -> str | None:
        """Pre-check: deny if category is already agreed."""
        if category not in self._agreed:
            return None
        msg = f"Category '{category}' is already agreed upon: {json.dumps(self._agreed[category])}. No further changes allowed."
        pid = self._current_principal
        config = self.agent_configs[pid]
        print(f"\n  [{config.agent_id}] ⛔ {category}: ALREADY AGREED")
        self._emit_event(NegotiationEvent(
            agent_id=config.agent_id,
            event_type="denial",
            category=category,
            failure_code="ALREADY_AGREED",
            failure_message=msg,
        ))
        return msg

    def _on_tool_result(
        self, tool_result: ToolResult, action_type: OperationType, kwargs: dict
    ) -> dict | None:
        """Callback fired after every enforcement attempt (success or failure)."""
        pid = self._current_principal
        config = self.agent_configs[pid]
        category = kwargs.get("category", "")
        params = kwargs.get("params", {})
        rationale = kwargs.get("rationale", "")
        extra = {}

        if tool_result.success:
            receipt = tool_result.receipt
            label = "ACCEPTED" if action_type == OperationType.COMMIT else "PROPOSED"
            emoji = "✅" if action_type == OperationType.COMMIT else "📋"
            print(f"\n  [{config.agent_id}] {emoji} {label} {category}: {json.dumps(params)}")
            print(f"    Rationale: {rationale}")
            print(f"    Receipt: {receipt.receipt_hash[:32]}...")

            self._emit_event(NegotiationEvent(
                agent_id=config.agent_id,
                event_type="acceptance" if action_type == OperationType.COMMIT else "proposal",
                category=category,
                params=params,
                rationale=rationale,
                receipt_hash=receipt.receipt_hash,
            ))

            if action_type == OperationType.COMMIT:
                extra = self._track_commit(pid, category, params)
        else:
            print(f"\n  [{config.agent_id}] ❌ DENIED {action_type.value} {category}: {tool_result.failure_code}")
            print(f"    {tool_result.message}")
            print(f"    Attempted: {json.dumps(params)}")

            self._emit_event(NegotiationEvent(
                agent_id=config.agent_id,
                event_type="denial",
                category=category,
                params=params,
                rationale=rationale,
                failure_code=tool_result.failure_code,
                failure_message=tool_result.message,
            ))

        return extra

    def _track_commit(self, principal_id: str, category: str, params: dict) -> dict:
        """Track a commit and check for agreement. Returns extra response fields."""
        extra = {}
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
                extra["message"] = (
                    f"AGREED — all parties with authority have committed to the same terms "
                    f"on {category}. This category is now locked."
                )
            else:
                other_commits = {
                    self.agent_configs[pid].agent_id: p
                    for pid, p in self._commits[category].items()
                    if pid != principal_id
                }
                extra["note"] = (
                    f"Other commits on {category}: {json.dumps(other_commits)}. "
                    f"Terms don't match yet — category not agreed."
                )
        return extra

    def _make_broadcaster(self, peer: ProtocolPeer):
        """Create a sync callback that broadcasts a receipt over VinculNet."""
        engine = self

        def broadcast(receipt: Receipt) -> None:
            async def _send():
                payload = {"type": "receipt", "receipt": receipt.to_dict()}
                for peer_id in peer.peer.registry.all_peers():
                    await peer.peer.send(peer_id, payload)
            asyncio.run_coroutine_threadsafe(_send(), engine._loop).result(timeout=10)

        return broadcast

    def _broadcast_message(self, principal_id: str, message: str) -> None:
        """Broadcast a chat message over VinculNet (sync wrapper)."""
        peer = self.peers[principal_id]
        config = self.agent_configs[principal_id]

        async def _send():
            payload = {"type": "message", "sender": config.agent_id, "message": message}
            for peer_id in peer.peer.registry.all_peers():
                await peer.peer.send(peer_id, payload)

        asyncio.run_coroutine_threadsafe(_send(), self._loop).result(timeout=10)

    # ── Setup ──────────────────────────────────────────────

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
                self.ctx.add_scope(scope)
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
                peer.runtime = copy.deepcopy(base_runtime)
            self.peers[pid] = peer
            self._received_receipts[pid] = []

            def _make_handler(principal_id):
                def handler(sender_id, receipt):
                    self._received_receipts[principal_id].append((sender_id, receipt))
                    self._on_receipt_received(principal_id, sender_id, receipt)
                return handler
            peer.on_receipt(_make_handler(pid))

        # 4b. Build VinculAgentContext per principal
        for pid in self.agent_configs:
            self._vincul_agents[pid] = VinculAgentContext(
                principal_id=pid,
                contract_id=self.contract.contract_id,
                signer=self.keypairs[pid],
                runtime=self.peers[pid].runtime,
                _scopes=self.scopes[pid],
                on_commit=self._make_broadcaster(self.peers[pid]),
                on_result=self._on_tool_result,
            )

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

        # 6. Build system prompts and framework agents
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

    # ── Run negotiation ────────────────────────────────────

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

    # ── Context building ───────────────────────────────────

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

    # ── Summary ────────────────────────────────────────────

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

    # ── Cleanup ────────────────────────────────────────────

    async def cleanup(self) -> None:
        for peer in self.peers.values():
            await peer.stop()
