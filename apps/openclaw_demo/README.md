# OpenClaw + Vincul Demo: "The Jailbreak That Doesn't Matter"

Demonstrates that system prompt boundaries are breakable (100% bypass rate),
while Vincul enforcement is cryptographically unbreakable.

## Prerequisites

- Docker and Docker Compose
- An Anthropic API key (or OpenAI/Ollama — see Configuration)

## Quick Start

```bash
# From this directory:
export LLM_API_KEY=sk-ant-...   # your Anthropic API key

./run.sh                        # builds + starts everything
```

Then open http://localhost:18789 in your browser to watch agents in real-time.

## The 3 Acts

### Act 1 — The Dream (normal operation, no Vincul)

Alice asks her agent to coordinate dinner plans with Bob.
Both agents communicate via `sessions_send`, check calendars, book a restaurant.
Everything works as intended.

### Act 2 — The Breach (coming soon)

A prompt injection in a WebChat message compromises Alice's agent.
3 attacks (cross-tenant message, unauthorized booking, data exfiltration) — all succeed.

### Act 3 — The Fix (coming soon)

Same injection, but Vincul enforcement is active.
3 attacks — all denied with cryptographic receipts and full audit trail.

## Configuration

Environment variables (set before running `run.sh` or in `.env`):

| Variable | Default | Description |
|----------|---------|-------------|
| `LLM_API_KEY` | (required) | API key for the LLM provider |
| `LLM_PROVIDER` | `anthropic` | `anthropic`, `openai`, or `ollama` |
| `LLM_MODEL` | `claude-sonnet-4-20250514` | Model identifier |
| `LLM_BASE_URL` | (auto) | Custom API base URL (required for Ollama) |

## Architecture

```
Docker container
├── OpenClaw Gateway (ws://127.0.0.1:18789)
│   ├── Alice's Agent (WebChat, real LLM)
│   ├── Bob's Agent (WebChat, real LLM)
│   └── tool.before interceptor (Acts 2-3 only)
│       → HTTP POST http://localhost:8100/enforce
│
├── Vincul Enforcement Service (Python/FastAPI, port 8100)
│   ├── VinculRuntime with coalition contract + scopes
│   └── POST /enforce endpoint (7-step pipeline)
│
└── Demo Orchestrator (Python script)
    └── Drives all 3 acts via OpenClaw HTTP/WebSocket API
```

## Manual Interaction

After starting, you can also interact with agents directly through the
WebChat UI at http://localhost:18789. The orchestrator and manual interaction
can coexist.
