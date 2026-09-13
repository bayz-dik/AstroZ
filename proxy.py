#!/usr/bin/env python3
"""SSE-sanitising pass-through proxy in front of 9Router.

Why this exists: 9Router terminates a streaming chat completion with
`data: [DONE]` **twice** (verified by reading the raw stream). Strict SSE
parsers reject the second terminator, opencode dies with
`JSON parsing failed: Text: [DONE] [DONE]` and the worker returns no answer.
Claude Code, Codex and OMP tolerate it, opencode does not.

This proxy forwards /v1/* to the gateway untouched except for the SSE
terminator: the first `[DONE]` is forwarded, later ones in the same stream are
dropped. Everything else (headers, body, status, non-streaming responses) is
passed through verbatim.

Usage: proxy.py [--listen 20129] [--upstream 127.0.0.1:20128]
"""
from __future__ import annotations

import argparse
import http.client
import socket
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

UPSTREAM = ("127.0.0.1", 20128)
HOP_BY_HOP = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
    "content-length",
    "host",
}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "astroz-sse-sanitizer"

    def log_message(self, fmt: str, *args) -> None:  # keep the log quiet
        pass

    # -- helpers -----------------------------------------------------------
    def _upstream(self) -> http.client.HTTPConnection:
        return http.client.HTTPConnection(*UPSTREAM, timeout=900)

    def _read_body(self) -> bytes:
        length = self.headers.get("Content-Length")
        if length:
            return self.rfile.read(int(length))
        if self.headers.get("Transfer-Encoding", "").lower() == "chunked":
            chunks = []
            while True:
                size = int(self.rfile.readline().strip() or b"0", 16)
                if size == 0:
                    self.rfile.readline()
                    break
                chunks.append(self.rfile.read(size))
                self.rfile.readline()
            return b"".join(chunks)
        return b""

    def _forward(self, method: str) -> None:
        body = self._read_body() if method in ("POST", "PUT", "PATCH") else None
        headers = {
            k: v for k, v in self.headers.items() if k.lower() not in HOP_BY_HOP
        }
        conn = self._upstream()
        try:
            conn.request(method, self.path, body=body, headers=headers)
            resp = conn.getresponse()
        except Exception as e:  # upstream down / refused
            payload = f'{{"error":{{"message":"sanitizer: {e}"}}}}'.encode()
            self.send_response(502)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            conn.close()
            return

        ctype = resp.getheader("Content-Type", "") or ""
        streaming = "text/event-stream" in ctype
        self.send_response(resp.status)
        for k, v in resp.getheaders():
            if k.lower() in HOP_BY_HOP:
                continue
            self.send_header(k, v)
        if streaming:
            # Unknown length, so stream it out with chunked encoding.
            self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()

        if not streaming:
            data = resp.read()
            if data:
                self.wfile.write(data)
            conn.close()
            return

        seen_done = False
        try:
            for raw in resp:
                line = raw.rstrip(b"\r\n")
                if line.strip() == b"data: [DONE]":
                    if seen_done:
                        continue
                    seen_done = True
                out = line + b"\n"
                self.wfile.write(b"%x\r\n%s\r\n" % (len(out), out))
                self.wfile.flush()
            self.wfile.write(b"0\r\n\r\n")
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            conn.close()

    # -- verbs -------------------------------------------------------------
    def do_GET(self) -> None:
        self._forward("GET")

    def do_POST(self) -> None:
        self._forward("POST")

    def do_DELETE(self) -> None:
        self._forward("DELETE")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--listen", type=int, default=20129)
    ap.add_argument("--upstream", default="127.0.0.1:20128")
    ap.add_argument("--host", default="127.0.0.1")
    args = ap.parse_args()

    global UPSTREAM
    host, _, port = args.upstream.partition(":")
    UPSTREAM = (host, int(port or 80))

    srv = ThreadingHTTPServer((args.host, args.listen), Handler)
    srv.daemon_threads = True
    print(f"[sanitizer] http://{args.host}:{args.listen} -> http://{host}:{UPSTREAM[1]}", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    socket.setdefaulttimeout(None)
    sys.exit(main())
