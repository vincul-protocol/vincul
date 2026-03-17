#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# Which act to run (optional — if omitted, just start services + web UI)
ACT="${1:-}"

# Detect docker compose command (v2 plugin vs v1 standalone)
if docker compose version > /dev/null 2>&1; then
    DC="docker compose"
elif docker-compose version > /dev/null 2>&1; then
    DC="docker-compose"
else
    echo "ERROR: Neither 'docker compose' nor 'docker-compose' found."
    echo "Install Docker Compose: https://docs.docker.com/compose/install/"
    exit 1
fi

# Check for API key
if [ -z "$LLM_API_KEY" ]; then
    echo "ERROR: LLM_API_KEY is not set."
    echo ""
    echo "Usage:"
    echo "  export LLM_API_KEY=sk-ant-...   # Anthropic"
    echo "  ./run.sh          # Start services + open web UI"
    echo "  ./run.sh act1     # Run Act 1 (CLI)"
    echo "  ./run.sh act2     # Run Act 2 (CLI)"
    echo "  ./run.sh act3     # Run Act 3 (CLI)"
    exit 1
fi

echo "=== OpenClaw + Vincul Demo ==="
echo ""

# Build and start if not already running
if ! curl -sf http://localhost:18789/health > /dev/null 2>&1; then
    echo "Building Docker image..."
    $DC build

    echo ""
    echo "Starting services..."
    $DC up -d

    echo ""
    echo "Waiting for services to be ready..."
    for i in $(seq 1 30); do
        if curl -sf http://localhost:18789/health > /dev/null 2>&1; then
            echo "OpenClaw gateway ready!"
            break
        fi
        if [ "$i" -eq 30 ]; then
            echo "ERROR: Gateway did not start in time. Check logs:"
            echo "  $DC logs"
            exit 1
        fi
        sleep 1
    done
else
    echo "Services already running."
fi

echo ""
echo "=== Services Running ==="
echo "  Demo UI:        http://localhost:3000"
echo "  WebChat UI:     http://localhost:18789"
echo "  Vincul Enforce: http://localhost:8100"
echo ""

if [ -n "$ACT" ]; then
    echo "=== Running ${ACT} ==="
    echo ""
    $DC exec -w /app/apps/openclaw_demo demo python -m "orchestrator.${ACT}"
    echo ""
    echo "=== Done ==="
else
    echo "Open http://localhost:3000 to run the demo."
    echo ""
    echo "Or run an act directly:"
    echo "  ./run.sh act1     # Normal coordination"
    echo "  ./run.sh act2     # The Breach (jailbreak)"
fi

echo ""
echo "To stop services:"
echo "  cd $(pwd) && $DC down"
