#!/usr/bin/env bash
# Deploy and run the agentic demo on EC2 via Docker.
#
# Usage:
#   ./apps/agentic_demo/deploy.sh EC2_HOST [SSH_KEY]
#
# Examples:
#   ./apps/agentic_demo/deploy.sh ubuntu@10.0.1.50
#   ./apps/agentic_demo/deploy.sh ubuntu@10.0.1.50 ~/.ssh/my-key.pem
#
# Prerequisites:
#   - EC2 has Docker installed
#   - EC2 has IAM role with Bedrock access (no AWS keys needed)
#   - SSH access to EC2

set -euo pipefail

EC2_HOST="${1:?Usage: $0 EC2_HOST [SSH_KEY]}"
SSH_KEY="${2:-}"
REMOTE_DIR="/tmp/vincul-demo"
IMAGE_NAME="vincul-agentic-demo"

SSH_CMD="ssh"
SCP_CMD="scp"
if [ -n "$SSH_KEY" ]; then
    SSH_CMD="ssh -i $SSH_KEY"
    SCP_CMD="scp -i $SSH_KEY"
fi

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

echo "==> Syncing code to $EC2_HOST:$REMOTE_DIR"
$SSH_CMD "$EC2_HOST" "mkdir -p $REMOTE_DIR"
rsync -az --delete \
    -e "${SSH_CMD}" \
    --include='pyproject.toml' \
    --include='setup.py' \
    --include='src/***' \
    --include='apps/' \
    --include='apps/agentic_demo/***' \
    --exclude='*' \
    "$REPO_ROOT/" "$EC2_HOST:$REMOTE_DIR/"

echo "==> Building Docker image on EC2"
$SSH_CMD "$EC2_HOST" "cd $REMOTE_DIR && docker build -f apps/agentic_demo/Dockerfile -t $IMAGE_NAME ."

echo "==> Stopping old container (if any)"
$SSH_CMD "$EC2_HOST" "docker rm -f $IMAGE_NAME 2>/dev/null || true"

echo "==> Starting container"
$SSH_CMD "$EC2_HOST" "docker run -d \
    --name $IMAGE_NAME \
    --restart unless-stopped \
    -p 8199:8800 \
    $IMAGE_NAME"

echo ""
echo "==> Done! Demo running at http://$EC2_HOST:8199"
echo "    Logs: ssh $EC2_HOST docker logs -f $IMAGE_NAME"
echo "    Stop: ssh $EC2_HOST docker rm -f $IMAGE_NAME"
