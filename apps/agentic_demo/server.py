"""FastAPI server for the agentic demo — streams negotiation events via SSE."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import AsyncGenerator

from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse, StreamingResponse

from apps.agentic_demo.engine import AgentConfig, NegotiationEngine, NegotiationEvent
from apps.agentic_demo.scenarios.term_sheet import (
    AGENT_A_ID, AGENT_B_ID, AGENT_INV_ID,
    CONTRACT_DESCRIPTION, CONTRACT_PURPOSE,
    FOUNDER_A_ID, FOUNDER_A_SCOPES, FOUNDER_B_ID, FOUNDER_B_SCOPES,
    INVESTOR_ID, INVESTOR_SCOPES,
    PORTS, ROGUE_SYSTEM_PROMPTS, SYSTEM_PROMPTS,
)

logging.basicConfig(level=logging.WARNING)

app = FastAPI(title="Vincul Agentic Demo")

STATIC_DIR = Path(__file__).parent / "static"


@app.get("/", response_class=HTMLResponse)
async def index():
    return (STATIC_DIR / "index.html").read_text()


@app.get("/api/run")
async def run_negotiation(
    mode: str = Query("cooperative", enum=["cooperative", "rogue"]),
    rounds: int = Query(3, ge=1, le=10),
):
    """Stream negotiation events via SSE."""

    async def event_stream() -> AsyncGenerator[str, None]:
        rogue = mode == "rogue"
        investor_prompt = (
            ROGUE_SYSTEM_PROMPTS[INVESTOR_ID] if rogue
            else SYSTEM_PROMPTS[INVESTOR_ID]
        )

        agents = [
            AgentConfig(
                principal_id=FOUNDER_A_ID, agent_id=AGENT_A_ID,
                system_prompt=SYSTEM_PROMPTS[FOUNDER_A_ID],
                port=PORTS[FOUNDER_A_ID], scopes=FOUNDER_A_SCOPES,
            ),
            AgentConfig(
                principal_id=FOUNDER_B_ID, agent_id=AGENT_B_ID,
                system_prompt=SYSTEM_PROMPTS[FOUNDER_B_ID],
                port=PORTS[FOUNDER_B_ID], scopes=FOUNDER_B_SCOPES,
            ),
            AgentConfig(
                principal_id=INVESTOR_ID, agent_id=AGENT_INV_ID,
                system_prompt=investor_prompt,
                port=PORTS[INVESTOR_ID], scopes=INVESTOR_SCOPES,
            ),
        ]

        engine = NegotiationEngine(
            agents=agents,
            contract_purpose=CONTRACT_PURPOSE,
            contract_description=CONTRACT_DESCRIPTION,
            max_rounds=rounds,
        )

        # Event queue for SSE streaming
        queue: asyncio.Queue = asyncio.Queue()

        def on_event(event: NegotiationEvent):
            queue.put_nowait(("event", {
                "type": "negotiation_event",
                "event_type": event.event_type,
                "agent_id": event.agent_id,
                "category": event.category,
                "params": event.params,
                "rationale": event.rationale,
                "message": event.message,
                "failure_code": event.failure_code,
                "failure_message": event.failure_message,
                "receipt_hash": event.receipt_hash,
            }))

        def on_receipt(receiver, sender, receipt_hash):
            queue.put_nowait(("receipt", {
                "type": "receipt_exchange",
                "receiver": receiver,
                "sender": sender,
                "hash": receipt_hash,
            }))

        engine.on_event(on_event)
        engine.on_receipt_exchange(on_receipt)

        # Send setup_start immediately
        yield _sse({"type": "setup_start", "mode": mode, "rounds": rounds})

        # Run setup
        try:
            await engine.setup()
        except Exception as e:
            # Cleanup any partially started peers
            await engine.cleanup()
            yield _sse({"type": "error", "message": f"Setup failed: {e}"})
            return

        # Send setup complete with state
        scope_info = []
        for pid, scopes in engine.scopes.items():
            for s in scopes:
                ops = [t.value for t in s.domain.types]
                scope_info.append({
                    "principal": pid,
                    "namespace": s.domain.namespace,
                    "operations": ops,
                    "ceiling": s.ceiling,
                })

        peer_info = []
        for pid, peer in engine.peers.items():
            connected = list(peer.peer.registry.all_peers())
            peer_info.append({
                "principal": pid,
                "port": engine.agent_configs[pid].port,
                "connected_to": connected,
            })

        yield _sse({
            "type": "setup_complete",
            "contract_id": engine.contract.contract_id,
            "contract_status": engine.contract.status.value,
            "scopes": scope_info,
            "peers": peer_info,
            "agents": [
                {"id": c.agent_id, "principal": c.principal_id, "port": c.port}
                for c in engine.agent_configs.values()
            ],
        })

        # Run negotiation in background
        async def run_engine():
            try:
                await engine.run()
            except Exception as e:
                queue.put_nowait(("error", {"type": "error", "message": str(e)}))
            finally:
                queue.put_nowait(("done", None))

        task = asyncio.create_task(run_engine())

        # Stream events from queue
        try:
            while True:
                try:
                    kind, data = await asyncio.wait_for(queue.get(), timeout=120)
                except asyncio.TimeoutError:
                    yield _sse({"type": "keepalive"})
                    continue

                if kind == "done":
                    yield _sse({
                        "type": "complete",
                        "summary": {
                            "total_events": len(engine.timeline),
                            "proposals": len([e for e in engine.timeline if e.event_type == "proposal"]),
                            "acceptances": len([e for e in engine.timeline if e.event_type == "acceptance"]),
                            "denials": len([e for e in engine.timeline if e.event_type == "denial"]),
                            "messages": len([e for e in engine.timeline if e.event_type == "message"]),
                            "receipts_exchanged": sum(
                                len(r) for r in engine._received_receipts.values()
                            ),
                        },
                    })
                    break
                else:
                    yield _sse(data)

            await task
        finally:
            # Always cleanup peers so ports are freed for the next run
            await engine.cleanup()

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


def _sse(data: dict) -> str:
    return f"data: {json.dumps(data)}\n\n"
