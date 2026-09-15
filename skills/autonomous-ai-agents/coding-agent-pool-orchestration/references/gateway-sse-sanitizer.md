# SSE-sanitising pass-through proxy

When a worker CLI dies on a gateway's stream framing (`JSON parsing failed: Text:
[DONE] [DONE]`, or any strict SSE parser aborting on a malformed terminator), the
fix belongs in one place in front of every worker, not in each CLI's config.

## When to reach for this

- A gateway ends a stream with a duplicate terminator, an out-of-order event, or a
  keep-alive comment a strict parser rejects.
- Some workers tolerate it and one does not. Fixing it per-worker means the next
  worker you add inherits the bug; a proxy fixes all of them and stays true to
  what the gateway actually sent.
- You must not patch the gateway binary. A proxy is reversible: change the port
  back and the old behaviour returns.

## Shape

Stdlib `http.server.ThreadingHTTPServer`, one handler forwarding every method to
the upstream:

1. Read the request body (`Content-Length`, or de-chunk `Transfer-Encoding:
   chunked`) and forward it verbatim.
2. Strip hop-by-hop headers both ways (`connection`, `keep-alive`, `te`,
   `trailers`, `upgrade`, `content-length`, `host`).
3. If the response `Content-Type` is not `text/event-stream`, forward status +
   headers + body unchanged and stop — do not touch non-streaming responses.
4. If it is a stream, drop the inbound `Content-Length`, send
   `Transfer-Encoding: chunked`, then re-emit each line as its own chunk.
   Suppress the framing you are fixing (e.g. forward the first `data: [DONE]`,
   skip subsequent ones **within that stream** — reset the flag per response).
5. Swallow `BrokenPipeError`/`ConnectionResetError`: a client that hangs up
   mid-stream is normal, not an error.

Two details that bite:

- Always terminate with the zero-length chunk (`0\r\n\r\n`) once the upstream
  stream ends, or chunked clients hang waiting for a length they will never get.
- `protocol_version = "HTTP/1.1"` on the handler class; HTTP/1.0 responses close
  the connection per request and break long streams.

## Wiring

- Put the proxy port in the gateway config (`api_base`) and keep the real
  upstream URL beside it, so switching to or from the proxy is a one-line change
  and both are documented.
- Start it in the launcher next to the gateway, guarded by a port check, and
  print its URL labelled as the proxy, not the gateway: the gateway keeps its own
  (usually default, often hardcoded) port and the proxy listens on a second one.
  Two ports is the intended state — say which is which wherever the URLs appear.
- Point **only the strict-parser clients** at the proxy port. Lenient clients
  ([CC], Codex, OMP, Hermes itself) should stay on the upstream URL: the hop buys
  them nothing and makes the proxy a new way for them to fail. `api_base` is the
  proxy, `upstream_base_url` the gateway.
- Verify with a raw streaming request before touching worker configs:
  `curl -sN -m 90 <proxy>/v1/chat/completions -H "Authorization: Bearer $KEY" -d
  '{"model":"<id>","messages":[{"role":"user","content":"hi"}],"stream":true}' |
  grep -c 'data: \[DONE\]'` — it must print `1`, not `2`.
- Then re-run the per-worker smoke test; the worker that failed on framing should
  pass with no change to its own config.

## What this is not

Not a retry layer, not a cache, not an auth proxy. Keep it a faithful pass-through
that removes exactly one class of framing defect — anything more and a future
debugger cannot tell which layer mangled the stream.
