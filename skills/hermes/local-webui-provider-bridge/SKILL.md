---
name: local-webui-provider-bridge
description: "Bridge self-hosted AI web UIs to remote providers via proxy."
version: 1.0.0
license: MIT
---

# Bridging Self-Hosted Web UIs to Remote AI Providers

## Always-on rules

- Never modify the stock UI or vendored skill files — build the compat layer (proxy server, runner script) OUTSIDE the vendored tree. Stock files must stay patchable by upstream updates, and the user has explicitly required this.
- Inspect the UI's provider/validation code BEFORE choosing an integration path: grep the shipped JS/HTML for `localhost`, `hostname`, `127.0.0.1`, and `fetch(` to learn which origins it allows and which URL it will call. A UI that hard-restricts 'local models' to loopback cannot point at a remote base URL directly — proxy, don't patch.
- Inject API keys server-side in the proxy (from env / ~/.hermes/.env); never type the key into a browser settings field. Mask keys in all test output (`***` + last 4).
- In the browser, the page URL host and the base-URL setting host must match exactly (same hostname AND scheme). Mixed hosts are the #1 cause of 'Failed to fetch' reports.

## Procedure

1. Clone/obtain the UI and read its README self-host section — the best ones are a single `index.html` with no build step; serve the directory as-is.
2. Confirm the upstream API speaks OpenAI-compatible `/v1/models` + `/v1/chat/completions` and check its CORS (curl -X OPTIONS with an Origin header) — but expect to proxy anyway if the UI restricts hosts.
3. Deploy the combined server from `templates/openai-proxy-server.py` (copy next to the UI files): it serves the UI directory AND forwards `/v1/*` to the upstream provider with the key injected. Set the upstream URL and key via env vars.
4. Verify server-side before touching the browser: `GET /` returns the UI; `GET /v1/models` returns JSON with `Accept-Encoding: gzip, deflate, br, zstd` set (Chrome-like); one `POST /v1/chat/completions` round-trips. Reasoning models need max_tokens ≥ ~300 or content comes back empty with `finish_reason: length`.
5. In the UI: Settings → local/custom models → base URL = the SAME host the browser uses (loopback for same-device, LAN IP for other devices). Test & discover models. If it fails, read the proxy log: request absent → network/typo; OPTIONS present but no GET/POST → browser rejected after preflight (PNA/host mismatch).

## Pitfalls

- Strip `Accept-Encoding` from headers forwarded upstream — if the upstream gzips and the proxy relays compressed bytes without a `Content-Encoding` header, the browser parses them as JSON and dies with `Unexpected token ... is not valid JSON`. The error text mentions CORS and misleads.
- Serve the PNA preflight header `Access-Control-Allow-Private-Network: true` on OPTIONS and responses — Chrome enforces it when a public page fetches a private-network endpoint.
- Bind `0.0.0.0` only when other LAN devices need the UI; loopback-only otherwise — an open proxy with an injected key is usable by anyone on the network.
- When a vendor tool (CLI or skill script) hardcodes OpenRouter defaults (base URL, `model.name` config key, `OPENROUTER_API_KEY` fallback), do not edit it: load its functions via exec into a namespace from an external runner and call the entry function with explicit `model=`, `base_url=`, `api_key=` arguments resolved from Hermes config + env.
- Diagnose browser fetch failures from the server log first, not by guessing: the log splits `[ui]` vs `[proxy]` lines and tells you which layer to fix.

## Support files

- `templates/openai-proxy-server.py` — known-good combined UI server + OpenAI-compatible proxy (Accept-Encoding stripped, PNA header, env-configured bind host/upstream/key).