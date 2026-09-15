# Driver for auditing a local static web app through the browser_exec tool.
# Paste into browser_exec(code=...) and adapt the selectors / namespace / test list.
# Nothing here needs a build step; the app is plain HTML+CSS+JS on a local http.server.

BASE = "http://127.0.0.1:8100"      # python3 -m http.server 8100 --bind 127.0.0.1
NS = "PSI"                          # app's window.<NAMESPACE> exposed API
TEST_IDS = ["math", "tiu5", "cfit", "kraepelin", "pauli", "epps"]


# --- never let an assertion decide by raising -------------------------------
def ev(expr, default="MISSING"):
    """Evaluate JS, return 'ERR: ...' on failure and `default` on a null result.
    A null from a broken render and a null from a wrong selector look identical
    when an exception is the only signal."""
    try:
        v = js(expr)
    except Exception as ex:
        return "ERR:" + str(ex)[:180]
    return default if v is None else v


# --- fresh, cache-busted, dialog-proof page --------------------------------
cdp("Network.setCacheDisabled", cacheDisabled=True)   # else you re-test the old bundle
new_tab(f"{BASE}/?v=1")
wait_for_load()
goto_url(f"{BASE}/?v=2")          # second load: fresh document, cleared localStorage
wait_for_load()
ev("localStorage.clear()")
ev("window.__errs=[]; window.onerror=(m,s,l)=>{window.__errs.push(m+' @'+l)};")
# A confirm() that survives a reload blocks Runtime.evaluate (shows up as a 5s timeout):
ev("window.confirm=()=>true; window.alert=()=>{};")
print("namespace:", ev(f"typeof window.{NS}"))


# --- happy path for every feature, asserting RENDERED text ------------------
def run_case(test_id):
    ev(f'{NS}.brief("{test_id}")')
    ev(f'{NS}.start("{test_id}", true, true)')      # true/false/null are LOWERCASE
    kind = ev(f'window.{NS}_DATA.{test_id}.type')
    if kind == "mc":
        ev(f'(() => {{ const q={NS}_DATA.{test_id}.questions, o={NS}._session().order;'
           ' for (let i=0;i<o.length;i++){ '
           ' const qi=o[i]; '
           f' {NS}.jump(i); {NS}.answer(q[qi].a); }} }})()')
    elif kind == "kraepelin":
        ev(f'(() => {{ const s={NS}._session(), d=s.def; '
           ' for (let c=0;c<d.columns;c++) for (let r=0;r<d.rowsPerColumn;r++) '
           f' {NS}.krapDigit((s.cols[c][r][0]+s.cols[c][r][1])%10); }})()')
    else:
        ev(f'(() => {{ const s={NS}._session(); '
           f' for (let k=0;k<s.def.pairs.length;k++) {NS}.eppsPick(s.def.pairs[k][0]); }})()')
    ev(f"{NS}.confirmFinish()")
    # assert the RENDERED screen, not a return value
    return ev("document.querySelector('.verdict') ? document.querySelector('.verdict').innerText : 'NO-VERDICT'")


for t in TEST_IDS:
    print(f"{t:10s} -> {run_case(t)}")
print("history stored:", ev("JSON.parse(localStorage.getItem('psikotes_history_v1')).length"))


# --- fast-forward time instead of sleeping ---------------------------------
# ev("(() => { PSI._session().startedAt -= 30*60*1000; })()")   # pretend 30 minutes


# --- responsive probe (clear it before the next desktop assertion) ---------
cdp("Emulation.setDeviceMetricsOverride", width=390, height=844, deviceScaleFactor=2, mobile=True)
ev(f'{NS}.go("home")')
print("no horizontal overflow:", ev("document.documentElement.scrollWidth <= window.innerWidth + 2"))
cdp("Emulation.clearDeviceMetricsOverride")


# --- print CSS present? (window.print() itself is not observable) ----------
print("print rules:", ev("(() => { let n=0; for (const s of document.styleSheets) { try { "
                         "for (const r of s.cssRules) if (r.type===4 && r.conditionText.includes('print')) n++; "
                         "} catch(e){} } return n; })()"))


# --- generated report text: grep it in-page before trusting the download ---
# print(ev("(() => { const r=window.__lastResult; return r.pctl != null ? r.pctl : 'none'; })()"))

print("errs:", ev("window.__errs"))
