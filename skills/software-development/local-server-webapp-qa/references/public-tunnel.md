# Exposing a localhost server to the internet (cloudflared quick tunnel)

Needed whenever something OUTSIDE the phone must reach the app: email tracking pixels, provider
webhooks, a shareable preview URL. The app binds `127.0.0.1`, so it is unreachable from the network.

## Quick tunnel
```
cloudflared tunnel --protocol http2 --url http://127.0.0.1:<port>
```
- Get the binary for aarch64 phones:
  `curl -sL -o ~/bin/cloudflared https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm64 && chmod +x ~/bin/cloudflared`
- **Force `--protocol http2`.** The default QUIC handshake is often blocked on mobile networks; the
  tunnel then serves `HTTP 530` and never registers. http2 registers fine.
- Wait for `Registered tunnel connection` in the log before declaring it live, then prove it with a
  real request through the public URL (`curl -s -o /dev/null -w '%{http_code}' <url>/`).
- Read the assigned URL from the log: `grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' <log>`.

## Caveats
- The `*.trycloudflare.com` URL CHANGES on every restart, so any URL already embedded in sent
  content (a tracking pixel, a remotely-registered webhook) breaks when the tunnel restarts. For a
  stable URL use a named tunnel with a domain; a quick tunnel is fine for testing.
- Pass the URL into the app via an env var (e.g. `PUBLIC_URL`) so the pixel builder uses it, and show
  an active/not-active banner in the UI rather than silently sending untracked mail.

## Port probing under proot
`ss`/`netstat` do NOT report listening sockets inside proot-distro — their silence is not proof a port
is free. Probe with a real connect: bash `(echo >/dev/tcp/127.0.0.1/$p) 2>/dev/null`, or a short
Python socket connect. Use the same probe to detect a stale server and to pick a fallback port.

## Launcher that starts app + tunnel together
See `templates/launcher-with-tunnel.sh`: it probes the port, clears stale processes, falls back to a
free port, starts the tunnel, exports the public URL, then execs the app. Ctrl+C stops both.
