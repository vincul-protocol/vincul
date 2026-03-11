#!/bin/bash
set -e

echo "=== OpenClaw + Vincul Demo ==="
echo ""

# ── Copy config into tmpfs (read-only rootfs) ────────────────
cp /app/apps/openclaw_demo/config/openclaw.json /root/.openclaw/openclaw.json

# ── Vincul enforcement service ────────────────────────────────
echo "[*] Starting Vincul enforcement service on :8100..."
cd /app
PYTHONPATH=/app python3 -m uvicorn apps.openclaw_demo.enforcement_service.main:app \
    --host 0.0.0.0 --port 8100 --log-level warning &
VINCUL_PID=$!

for i in $(seq 1 10); do
    if curl -sf http://localhost:8100/health > /dev/null 2>&1; then
        echo "[+] Vincul enforcement service ready"
        break
    fi
    sleep 0.5
done

# ── OpenClaw setup ────────────────────────────────────────────
echo "[*] Configuring OpenClaw model auth..."

# Set up model auth (Anthropic API key) for default agent
PROVIDER="${LLM_PROVIDER:-anthropic}"
MODEL="${LLM_MODEL:-claude-sonnet-4-20250514}"

echo "$LLM_API_KEY" | openclaw models auth paste-token \
    --provider "$PROVIDER" \
    --profile-id "$PROVIDER:demo" 2>/dev/null || true

# Set default model
openclaw models set "$MODEL" 2>/dev/null || true

echo "[*] Configuring OpenClaw agents..."

# Create alice-agent and bob-agent
openclaw agents add alice-agent \
    --model "$MODEL" \
    --non-interactive \
    --workspace /tmp/alice-workspace 2>/dev/null || true

openclaw agents add bob-agent \
    --model "$MODEL" \
    --non-interactive \
    --workspace /tmp/bob-workspace 2>/dev/null || true

# Copy auth profiles to ALL agent dirs (main, alice-agent, bob-agent)
# The paste-token only writes to the default agent dir
MAIN_AUTH=$(find /root/.openclaw -path "*/auth-profiles.json" -print -quit 2>/dev/null)
if [ -n "$MAIN_AUTH" ]; then
    echo "[*] Copying auth profiles to all agents..."
    for AGENT_DIR in /root/.openclaw/agents/*/; do
        mkdir -p "${AGENT_DIR}agent"
        cp "$MAIN_AUTH" "${AGENT_DIR}agent/auth-profiles.json"
    done
else
    # Fallback: write auth profiles manually
    echo "[*] Writing auth profiles directly..."
    python3 -c "
import json, os
key = os.environ['LLM_API_KEY']
# Strip curly and straight quotes (common copy-paste issue)
key = key.strip().strip('\u2018\u2019\u201c\u201d\\'\"')
provider = '${PROVIDER}'
auth = {'profiles': {f'{provider}:demo': {'provider': provider, 'token': key}}, 'order': [f'{provider}:demo']}
s = json.dumps(auth)
# Write to default agent dir
os.makedirs('/root/.openclaw/agent', exist_ok=True)
open('/root/.openclaw/agent/auth-profiles.json', 'w').write(s)
# Write to each named agent
for d in os.listdir('/root/.openclaw/agents'):
    p = f'/root/.openclaw/agents/{d}/agent'
    os.makedirs(p, exist_ok=True)
    open(f'{p}/auth-profiles.json', 'w').write(s)
# Write to main agent (used by WebChat)
os.makedirs('/root/.openclaw/agents/main/agent', exist_ok=True)
open('/root/.openclaw/agents/main/agent/auth-profiles.json', 'w').write(s)
print('Auth profiles written')
"
fi

# Write agent system prompts via .clawinstructions files
mkdir -p /tmp/alice-workspace /tmp/bob-workspace

cat > /tmp/alice-workspace/.clawinstructions << 'ALICE_EOF'
You are Alice's personal assistant. You help her coordinate plans with friends and family.
You can message Alice on her WebChat and coordinate with Bob's agent via sessions_send.
When asked to coordinate with Bob, use sessions_send to reach bob-agent.
Be helpful, concise, and proactive about making plans happen.
ALICE_EOF

cat > /tmp/bob-workspace/.clawinstructions << 'BOB_EOF'
You are Bob's personal assistant. You help him manage his calendar and plans.
You can message Bob on his WebChat and respond to coordination requests from other agents.
Bob is generally free on Saturday evenings after 6pm.
Bob enjoys Italian and French cuisine.
When you receive a coordination request, check availability and respond helpfully.
Once plans are confirmed, message Bob with the details.
BOB_EOF

echo "[+] Agents configured"

# ── Start OpenClaw gateway ────────────────────────────────────
echo "[*] Starting OpenClaw gateway on :18789..."
openclaw gateway --port 18789 &
OPENCLAW_PID=$!

for i in $(seq 1 30); do
    if curl -sf http://localhost:18789/health > /dev/null 2>&1; then
        echo "[+] OpenClaw gateway ready"
        break
    fi
    sleep 1
done

# Auto-approve any pending device pairing requests (demo convenience)
(
    sleep 5
    while true; do
        # Parse pending request IDs from the table output
        openclaw devices list 2>/dev/null | \
            grep -oE '[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}' | \
            while read -r REQ_ID; do
                openclaw devices approve "$REQ_ID" 2>/dev/null && \
                    echo "[+] Auto-approved device $REQ_ID"
            done
        sleep 2
    done
) &

echo ""
echo "=== Services running ==="
echo "  OpenClaw WebChat: http://localhost:18789"
echo "  Vincul Enforce:   http://localhost:8100"
echo ""
echo "Run the demo orchestrator:"
echo "  docker compose exec demo python -m apps.openclaw_demo.orchestrator.act1"
echo ""

# Keep container alive
wait $OPENCLAW_PID $VINCUL_PID
