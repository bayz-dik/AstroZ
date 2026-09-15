# Gmail API notes for local sender apps

## Scopes — split send from read
- Send: `https://www.googleapis.com/auth/gmail.send`.
- Read + label: `https://www.googleapis.com/auth/gmail.readonly` and `.../gmail.modify`.

Use SEPARATE token files per capability so the send path keeps working before read consent is
granted. `gmail.modify` is needed to remove the `UNREAD` label; `readonly` alone cannot.

## Read receipts do not exist — but a tracking pixel gives an unreliable signal
The Gmail API cannot tell you whether a recipient OPENED your mail: there is no read-receipt field.
The only read state the API exposes is on YOUR OWN inbox — the `UNREAD` label on inbound messages.

When the user asks for "centang biru" (WhatsApp-style read receipts), say up front that email has no
such protocol; the only real "opened" signal is a TRACKING PIXEL, and its limits must be stated:
- Embed a 1x1 transparent image in the HTML part: `msg.set_content(body);
  msg.add_alternative(html_with_img, subtype="html")` where the html holds
  `<img src="{PUBLIC_URL}/track/{id}.png" width=1 height=1>`. Serve it from a `GET /track/<id>.png`
  route that logs a hit and returns the PNG bytes with `Cache-Control: no-store` (a 68-byte 1x1 PNG
  is fine: `base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=")`).
- It needs a PUBLIC url, so the localhost server must be tunnel-exposed (`references/public-tunnel.md`).
- It only works for mail sent AFTER the pixel was added — already-sent mail cannot be tracked.
- It is unreliable, so label it "kemungkinan dibuka" (likely opened), never "read": corporate clients
  block remote images (never recorded), Gmail rewrites/proxies the fetch (user-agent shows
  `... via ggpht.com GoogleImageProxy`), and Apple Mail auto-loads images on delivery (false positives).

## Reading replies
`users().messages().list(userId="me", q="in:inbox", maxResults=N)` then
`users().messages().get(userId="me", id=..., format="metadata", metadataHeaders=["From","Subject","Date"])`
— the metadata format avoids downloading bodies. Parse `payload.headers`, read `labelIds`
(`"UNREAD" in labelIds`), and use `snippet` for a cheap preview.

## Batch metadata fetch (avoid the N+1 round-trips)
A `get()` per message is one request per message — slow enough that the user notices the page lag.
Fetch them in one batch instead, keying each response by the message id:
```python
ids = [m["id"] for m in service.users().messages().list(userId="me", q="in:inbox", maxResults=30).execute().get("messages", [])]
fetched = {}
def _cb(rid, resp, err):
    if err is None and resp is not None:
        fetched[rid] = resp
batch = service.new_batch_http_request()
for mid in ids:
    req = service.users().messages().get(userId="me", id=mid, format="metadata",
                                         metadataHeaders=["From", "Subject", "Date"])
    batch.add(req, request_id=mid, callback=_cb)   # request_id is REQUIRED to map results
batch.execute()
out = [parse_headers(fetched[mid]) for mid in ids if mid in fetched]
```
Cache the parsed result for a short TTL (e.g. 60s) and expose a `?refresh=1` link that bypasses the
cache, so repeat page loads are instant but a live pull is one click away.

## Marking read
`users().messages().modify(userId="me", id=..., body={"removeLabelIds": ["UNREAD"]})`.

## 401/403 on first read
A 401/403 usually means the read scope was never granted (or the token expired). Route the user to
the app's own consent page (e.g. `GET /oauth/read`) — do NOT tell them to delete a token file and
re-open a page that tries to auto-launch a browser (that path fails on Termux/proot). See the
web-based OAuth convention in SKILL.md.

## Never auto-launch a browser for consent
`InstalledAppFlow.run_local_server(open_browser=True)` fails on Termux/proot with
`could not locate runnable browser` before printing the consent URL. Use the app's own redirect +
callback routes instead (SKILL.md).
