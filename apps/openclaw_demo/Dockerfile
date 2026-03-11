# OpenClaw + Vincul Demo
# Base image with Node.js (OpenClaw) + Python 3.11 (enforcement + orchestrator)

FROM node:22-slim AS base

# Install Python 3.11
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        python3 python3-pip python3-venv curl git && \
    rm -rf /var/lib/apt/lists/*

# Install OpenClaw globally
RUN npm install -g openclaw@latest

# Set up Python virtual environment
RUN python3 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Install Python dependencies
COPY pyproject.toml setup.py /app/
COPY src/ /app/src/
WORKDIR /app
RUN pip install --no-cache-dir -e ".[server]" && \
    pip install --no-cache-dir httpx

# Copy demo files
COPY apps/openclaw_demo/ /app/apps/openclaw_demo/

# OpenClaw config directory
RUN mkdir -p /root/.openclaw
COPY apps/openclaw_demo/config/openclaw.json /root/.openclaw/openclaw.json
COPY apps/openclaw_demo/config/agents/ /root/.openclaw/agents/

# Expose ports: OpenClaw gateway + Vincul enforcement service
EXPOSE 18789 8100

# Entry point: start both services
COPY apps/openclaw_demo/entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

CMD ["/app/entrypoint.sh"]
