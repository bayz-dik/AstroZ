#!/usr/bin/env python3
"""
Combined self-hosted UI server + OpenAI-compatible API proxy (known-good).

Copy this file next to the UI files (e.g. an index.html single-file app) and run:

    UPSTREAM_BASE=https://your-provider/v1  UPSTREAM_KEY=sk-...  python3 openai-proxy-server.py
    # optional: PORT=8483  BIND_HOST=0.0.0.0  (default loopback-only)

Browser setup: page at http://<host>:<port>/, provider base URL
http://<host>:<port>/v1 (same host as the page). Key stays server-side.

Verified behaviors (do not regress):
- Accept-Encoding is NOT forwarded upstream (else upstream gzips, proxy relays
  compressed bytes without Content-Encoding, browser JSON parse fails with
  'Unexpected token ... is not valid JSON').
- OPTIONS preflight carries Access-Control-Allow-Private-Network: true (Chrome PNA).
- Logs tag [ui] vs [proxy] so failed browser fetches are diagnosable from the log.
"""
import os
import sys
import urllib.parse
import urllib.request
import urllib.error
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler

ROOT = os.path.dirname(os.path.abspath(__file__))
PORT = int(os.environ.get("PORT", "8483"))
BIND_HOST = os.environ.get("BIND_HOST", "127.0.0.1")
UPSTREAM = os.environ.get("UPSTREAM_BASE", "").rstrip("/")
API_KEY = os.environ.get("UPSTREAM_KEY", "")

PROXY_PREFIX = "/v1/"
HOP_HEADERS = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailers", "transfer-encoding", "upgrade", "host", "content-length",
    "accept-encoding",  # upstream must return identity; see docstring
}


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=ROOT, **kw)

    def _is_proxy(self):
        return self.path.startswith(PROXY_PREFIX) or self.path in ("/v1", "/v1/")

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.send_header("Access-Control-Allow-Private-Network", "true")

    def _proxy(self):
        if not (UPSTREAM and API_KEY):
            return self._json(500, {"error": "UPSTREAM_BASE / UPSTREAM_KEY not set"})
        url = UPSTREAM + self.path[len("/v1"):]
        body = None
        if self.command == "POST":
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length) if length else b""
        req = urllib.request.Request(url, data=body, method=self.command)
        for h, v in self.headers.items():
            if h.lower() in HOP_HEADERS or h.lower() == "authorization":
                continue
            req.add_header(h, v)
        req.add_header("Authorization", f"Bearer {API_KEY}")
        req.add_header("Host", urllib.parse.urlsplit(url).netloc)
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                payload = r.read()
                self.send_response(r.status)
                self.send_header("Content-Type", r.headers.get("Content-Type", "application/json"))
                self.send_header("Content-Length", str(len(payload)))
                self._cors()
                self.end_headers()
                self.wfile.write(payload)
        except urllib.error.HTTPError as e:
            payload = e.read()
            self.send_response(e.code)
            self.send_header("Content-Type", e.headers.get("Content-Type", "application/json"))
            self.send_header("Content-Length", str(len(payload)))
            self._cors()
            self.end_headers()
            self.wfile.write(payload)
        except Exception as e:
            self._json(502, {"error": f"proxy failure: {type(e).__name__}: {e}"})

    def _json(self, code, obj):
        import json
        payload = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.send_header("Access-Control-Max-Age", "86400")
        self.end_headers()

    def do_GET(self):
        if self._is_proxy():
            return self._proxy()
        return super().do_GET()

    def do_POST(self):
        if self._is_proxy():
            return self._proxy()
        self._json(404, {"error": "not found"})

    def log_message(self, fmt, *args):
        p = self.path.split("?")[0]
        tag = "[proxy]" if p.startswith("/v1") else "[ui]"
        print(f"{tag} {self.command} {p}", file=sys.stderr)


if __name__ == "__main__":
    if not (UPSTREAM and API_KEY):
        print("WARNING: UPSTREAM_BASE / UPSTREAM_KEY not set; /v1/* returns 500", file=sys.stderr)
    else:
        print(f"upstream: {UPSTREAM} (key ***{API_KEY[-4:]})", file=sys.stderr)
    print(f"UI : http://{'127.0.0.1' if BIND_HOST == '127.0.0.1' else '<lan-ip>'}:{PORT}/", file=sys.stderr)
    print(f"API: http://<same-host>:{PORT}/v1  <- enter this in the UI settings", file=sys.stderr)
    ThreadingHTTPServer((BIND_HOST, PORT), Handler).serve_forever()
