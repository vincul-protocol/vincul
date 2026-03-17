"""
Analyze captured LLM API requests from the logging proxy.

Usage:
    # Copy log from container
    docker compose cp demo:/tmp/llm_requests.jsonl /tmp/llm_requests.jsonl
    python3 -m apps.openclaw_demo.orchestrator.analyze_llm_log /tmp/llm_requests.jsonl
"""

import json
import sys
from pathlib import Path


def analyze(log_path: str) -> None:
    entries = [json.loads(line) for line in Path(log_path).read_text().strip().split("\n") if line.strip()]

    for i, entry in enumerate(entries):
        print(f"\n{'='*60}")
        print(f"Request #{i+1}  —  {entry.get('path', '?')}")
        print(f"{'='*60}")
        print(f"  Model:       {entry.get('model', '?')}")
        print(f"  Temperature: {entry.get('temperature', '?')}")
        print(f"  Max tokens:  {entry.get('max_tokens', '?')}")

        # System prompt
        system = entry.get("system")
        if isinstance(system, list):
            total = sum(len(b.get("text", "")) for b in system)
            print(f"  System:      {total:,} chars ({len(system)} block(s))")
            for j, block in enumerate(system):
                text = block.get("text", "")
                # Show first/last 200 chars
                print(f"    Block {j}: {len(text):,} chars")
                if len(text) > 400:
                    print(f"      START: {text[:200]!r}")
                    print(f"      ...END: {text[-200:]!r}")
                else:
                    print(f"      {text!r}")
        elif isinstance(system, str):
            print(f"  System:      {len(system):,} chars")

        # Tools
        tools = entry.get("tools", [])
        print(f"  Tools:       {len(tools)}")
        for t in tools:
            name = t.get("name", t.get("toolSpec", {}).get("name", "?"))
            print(f"    - {name}")

        # Messages
        messages = entry.get("messages", [])
        print(f"  Messages:    {len(messages)}")
        for m in messages:
            role = m.get("role", "?")
            content = m.get("content", "")
            if isinstance(content, str):
                preview = content[:200].replace("\n", "\\n")
                print(f"    [{role}] {len(content)} chars: {preview}")
            elif isinstance(content, list):
                for block in content:
                    btype = block.get("type", "?")
                    if btype == "text":
                        text = block.get("text", "")
                        preview = text[:200].replace("\n", "\\n")
                        print(f"    [{role}/{btype}] {len(text)} chars: {preview}")
                    elif btype == "tool_use":
                        print(f"    [{role}/tool_use] {block.get('name', '?')}")
                    elif btype == "tool_result":
                        print(f"    [{role}/tool_result] id={block.get('tool_use_id', '?')[:12]}...")
                    else:
                        print(f"    [{role}/{btype}]")

    # Dump full system prompt of last request for diffing
    if entries:
        last = entries[-1]
        system = last.get("system")
        dump_path = Path(log_path).with_suffix(".system.txt")
        if isinstance(system, list):
            text = "\n".join(b.get("text", "") for b in system)
        elif isinstance(system, str):
            text = system
        else:
            text = ""
        dump_path.write_text(text)
        print(f"\n  Full system prompt of last request saved to: {dump_path}")
        print(f"  ({len(text):,} chars)")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python analyze_llm_log.py <path/to/llm_requests.jsonl>")
        sys.exit(1)
    analyze(sys.argv[1])
