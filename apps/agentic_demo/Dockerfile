FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml setup.py ./
COPY src/ src/

RUN pip install --no-cache-dir -e ".[server]" strands-agents

COPY apps/agentic_demo/ apps/agentic_demo/

EXPOSE 8800

CMD ["uvicorn", "apps.agentic_demo.server:app", "--host", "0.0.0.0", "--port", "8800"]
