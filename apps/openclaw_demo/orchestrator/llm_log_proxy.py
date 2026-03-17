"""
Transparent HTTPS logging proxy for capturing OpenClaw → Anthropic API requests.

Sits between the OpenClaw SDK and the real API (via llm-proxy socat).
Logs full request bodies to /tmp/llm_requests.jsonl so we can see exactly
what system prompt, tools, and messages OpenClaw sends.

Usage (inside demo container):
    python3 -m apps.openclaw_demo.orchestrator.llm_log_proxy &
    export ANTHROPIC_BASE_URL=https://localhost:9443

Requires: self-signed cert at /tmp/proxy-cert.pem + /tmp/proxy-key.pem
"""

import json
import ssl
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.request import Request, urlopen

UPSTREAM = "https://llm-proxy:443"
LISTEN_PORT = 9443
LOG_FILE = Path("/tmp/llm_requests.jsonl")

# Upstream SSL context (don't verify socat's forwarded TLS)
_upstream_ctx = ssl.create_default_context()
_upstream_ctx.check_hostname = False
_upstream_ctx.verify_mode = ssl.CERT_NONE


class LoggingProxy(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)

        # Log the request
        try:
            parsed = json.loads(body)
            entry = {
                "ts": time.time(),
                "path": self.path,
                "model": parsed.get("model", "?"),
                "system_chars": sum(
                    len(b.get("text", "")) for b in parsed.get("system", [])
                ) if isinstance(parsed.get("system"), list) else len(str(parsed.get("system", ""))),
                "num_tools": len(parsed.get("tools", [])),
                "num_messages": len(parsed.get("messages", [])),
                "messages": parsed.get("messages"),
                "system": parsed.get("system"),
                "tools": parsed.get("tools"),
                "temperature": parsed.get("temperature"),
                "max_tokens": parsed.get("max_tokens"),
            }
            with open(LOG_FILE, "a") as f:
                f.write(json.dumps(entry) + "\n")

            # Also print summary
            print(
                f"[LOG] POST {self.path} | model={entry['model']} "
                f"| system={entry['system_chars']} chars "
                f"| tools={entry['num_tools']} "
                f"| msgs={entry['num_messages']}",
                flush=True,
            )
        except Exception as e:
            print(f"[LOG] parse error: {e}", flush=True)
            with open(LOG_FILE, "a") as f:
                f.write(json.dumps({"ts": time.time(), "raw": body.decode("utf-8", errors="replace")}) + "\n")

        # Forward to upstream
        url = f"{UPSTREAM}{self.path}"
        headers = {
            k: v for k, v in self.headers.items()
            if k.lower() not in ("host", "transfer-encoding")
        }
        headers["Host"] = "api.anthropic.com"

        req = Request(url, data=body, headers=headers, method="POST")
        try:
            resp = urlopen(req, context=_upstream_ctx, timeout=300)
            resp_body = resp.read()
            self.send_response(resp.status)
            for k, v in resp.getheaders():
                if k.lower() not in ("transfer-encoding", "connection"):
                    self.send_header(k, v)
            self.end_headers()
            self.wfile.write(resp_body)
        except Exception as e:
            print(f"[LOG] upstream error: {e}", flush=True)
            self.send_response(502)
            self.end_headers()
            self.wfile.write(str(e).encode())

    def do_GET(self):
        # Health check / passthrough
        url = f"{UPSTREAM}{self.path}"
        req = Request(url, method="GET")
        try:
            resp = urlopen(req, context=_upstream_ctx, timeout=30)
            self.send_response(resp.status)
            self.end_headers()
            self.wfile.write(resp.read())
        except Exception as e:
            self.send_response(502)
            self.end_headers()
            self.wfile.write(str(e).encode())

    def log_message(self, format, *args):
        pass  # Suppress default access logs


def main():
    import subprocess

    # Generate self-signed cert
    subprocess.run([
        "openssl", "req", "-x509", "-newkey", "rsa:2048",
        "-keyout", "/tmp/proxy-key.pem",
        "-out", "/tmp/proxy-cert.pem",
        "-days", "1", "-nodes",
        "-subj", "/CN=localhost",
    ], check=True, capture_output=True)

    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain("/tmp/proxy-cert.pem", "/tmp/proxy-key.pem")

    server = HTTPServer(("0.0.0.0", LISTEN_PORT), LoggingProxy)
    server.socket = ctx.wrap_socket(server.socket, server_side=True)

    print(f"[LOG] Logging proxy listening on https://0.0.0.0:{LISTEN_PORT}", flush=True)
    print(f"[LOG] Logging to {LOG_FILE}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
