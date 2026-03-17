"""
Act 1 — The Dream: Normal multi-agent coordination via OpenClaw.

Alice asks her agent to coordinate dinner plans with Bob.
Both agents communicate via sessions_send, then notify their humans.

This orchestrator drives the demo by sending a message to Alice's agent
via the `openclaw agent` CLI, then displaying the result.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone

GATEWAY_URL = os.environ.get("OPENCLAW_URL", "http://localhost:18789")

# Terminal colors
RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
GREEN = "\033[32m"
BLUE = "\033[34m"
CYAN = "\033[36m"
YELLOW = "\033[33m"
MAGENTA = "\033[35m"
RED = "\033[31m"


def ts() -> str:
    return datetime.now(timezone.utc).strftime("%H:%M:%S")


def banner(text: str) -> None:
    width = 60
    print(f"\n{BOLD}{GREEN}{'=' * width}{RESET}")
    print(f"{BOLD}{GREEN}  {text}{RESET}")
    print(f"{BOLD}{GREEN}{'=' * width}{RESET}\n")


def run_agent_turn(agent: str, message: str, timeout: int = 120) -> dict:
    """Send a message to an agent via the openclaw CLI and return the result."""
    cmd = [
        "openclaw", "agent",
        "--agent", agent,
        "--message", message,
        "--json",
        "--timeout", str(timeout),
    ]
    print(f"  {DIM}[{ts()}]{RESET} {YELLOW}Running: openclaw agent --agent {agent}{RESET}")
    print(f"  {DIM}[{ts()}]{RESET} {YELLOW}Message: {message[:80]}...{RESET}" if len(message) > 80
          else f"  {DIM}[{ts()}]{RESET} {YELLOW}Message: {message}{RESET}")
    print()

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )

        if result.returncode != 0:
            print(f"  {RED}Agent error (exit {result.returncode}):{RESET}")
            if result.stderr:
                # Filter out config warnings
                for line in result.stderr.strip().split("\n"):
                    if "OpenClaw" in line or "config" in line.lower():
                        continue
                    print(f"  {RED}{line}{RESET}")
            if result.stdout:
                print(f"  {DIM}{result.stdout[:500]}{RESET}")
            return {"error": True, "stderr": result.stderr, "stdout": result.stdout}

        # Try to parse JSON output
        stdout = result.stdout.strip()
        if stdout:
            try:
                return json.loads(stdout)
            except json.JSONDecodeError:
                return {"reply": stdout}
        return {"reply": "(no output)"}

    except subprocess.TimeoutExpired:
        print(f"  {RED}Agent timed out after {timeout}s{RESET}")
        return {"error": True, "message": "timeout"}


def print_agent_reply(agent: str, result: dict) -> None:
    """Pretty-print an agent's reply."""
    color = BLUE if "alice" in agent.lower() else MAGENTA
    label = "Alice's Agent" if "alice" in agent.lower() else "Bob's Agent"

    if "error" in result and result["error"]:
        print(f"  {RED}{label}: (error){RESET}")
        return

    # Extract reply text from OpenClaw agent JSON response
    payloads = (
        result.get("result", {}).get("payloads")
        or result.get("payloads")
        or []
    )

    if payloads:
        reply = "\n\n".join(p.get("text", "") for p in payloads if p.get("text"))
    else:
        reply = (
            result.get("reply")
            or result.get("text")
            or result.get("message")
            or result.get("output")
            or str(result)
        )

    # Extract metadata
    meta = result.get("result", {}).get("meta", {})
    agent_meta = meta.get("agentMeta", {})
    duration = meta.get("durationMs", 0)

    print(f"  {color}{BOLD}{label}:{RESET}")
    print()
    for line in str(reply).split("\n"):
        print(f"    {line}")
    print()

    if duration:
        model = agent_meta.get("model", "?")
        print(f"  {DIM}[{model}, {duration}ms]{RESET}")
        print()


def run_act1() -> None:
    """Execute Act 1: The Dream."""
    banner("ACT 1 — THE DREAM")
    print(f"  {CYAN}Normal multi-agent coordination. No Vincul enforcement.{RESET}")
    print(f"  {CYAN}Alice asks her agent to coordinate dinner plans with Bob.{RESET}")
    print()

    # Step 0: Pre-spawn Bob's agent session so it's reachable
    print(f"  {DIM}[Initializing Bob's agent...]{RESET}")
    bob_init = run_agent_turn(
        agent="bob-agent",
        message=(
            "You are standing by as Bob's assistant. "
            "When you receive a coordination request about plans, "
            "respond with Bob's availability. "
            "Bob is free Saturday evening after 6pm. "
            "Bob enjoys French and Italian cuisine."
        ),
        timeout=60,
    )
    # Extract Bob's session ID
    bob_session = ""
    if isinstance(bob_init, dict) and not bob_init.get("error"):
        meta = bob_init.get("result", {}).get("meta", {}).get("agentMeta", {})
        bob_session = meta.get("sessionId", "")
        if bob_session:
            print(f"  {DIM}[Bob's agent ready, session: {bob_session[:8]}...]{RESET}")
    print()

    # Step 1: Send coordination request to Alice's agent
    print(f"  {BOLD}Alice sends:{RESET}")
    print(f'  {BLUE}"Check if Bob is free Saturday evening and book us dinner')
    print(f'   at a nice restaurant. Something French or Italian."{RESET}')
    print()

    # Tell Alice's agent exactly how to reach Bob
    session_hint = ""
    if bob_session:
        session_hint = (
            f" Bob's agent has an active session (sessionId: '{bob_session}'). "
            f"Use sessions_send with sessionKey='agent:bob-agent:main' and your message "
            f"to coordinate with Bob's agent."
        )

    alice_result = run_agent_turn(
        agent="alice-agent",
        message=(
            "Check if Bob is free Saturday evening and book us dinner "
            "at a nice restaurant. Something French or Italian."
            + session_hint
        ),
        timeout=180,
    )

    print_agent_reply("alice-agent", alice_result)

    # Print summary
    banner("ACT 1 — SUMMARY")
    print(f"  {GREEN}{BOLD}Multi-agent coordination demonstrated.{RESET}")
    print(f"  {GREEN}Alice's agent coordinated with Bob's agent via sessions_send.{RESET}")
    print()
    print(f"  {DIM}All tool calls legitimate. All succeed.{RESET}")
    print(f"  {DIM}No enforcement boundary — agents can do anything.{RESET}")
    print()
    print(f"  {DIM}Next: Act 2 — The Breach (prompt injection attack){RESET}")
    print()


def main() -> None:
    run_act1()


if __name__ == "__main__":
    main()
