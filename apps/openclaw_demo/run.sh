#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

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
    echo "  export LLM_API_KEY=sk-...       # OpenAI"
    echo "  ./run.sh"
    echo ""
    echo "Or for Ollama (no key needed):"
    echo "  export LLM_PROVIDER=ollama LLM_BASE_URL=http://host.docker.internal:11434"
    echo "  export LLM_API_KEY=unused"
    echo "  ./run.sh"
    exit 1
fi

echo "=== OpenClaw + Vincul Demo ==="
echo ""
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

echo ""
echo "=== Services Running ==="
echo "  WebChat UI:     http://localhost:18789"
echo "  Vincul Enforce: http://localhost:8100"
echo ""
echo "=== Running Act 1 ==="
echo ""

$DC exec demo python -m apps.openclaw_demo.orchestrator.act1

echo ""
echo "=== Done ==="
echo "Services are still running. To stop:"
echo "  cd $(pwd) && $DC down"
