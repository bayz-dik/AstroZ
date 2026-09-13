/* AstroZ UI logic.
   Three surfaces, deliberately not merged:
     - chat column: my messages and AstroZ's answers, one bubble each;
     - activity: what the supervisor and the workers are doing, in its own
       boxes (drawer on a phone, side column on a wide screen);
     - tools: model, files, git, tests.
   The chat scrolls inside its own column and stays pinned to the newest turn,
   so a running task never pushes the answer out of view. */

const $ = (s) => document.querySelector(s);
const $$ = (s) => Array.from(document.querySelectorAll(s));
const el = (t, c, h) => { const e = document.createElement(t); if (c) e.className = c; if (h !== undefined) e.innerHTML = h; return e; };

const S = {
  sessions: [],
  sid: localStorage.getItem("astroz.sid") || "",
  messages: [],
  activity: {},
  live: {},            /* task id -> last line seen */
  running: new Set(),
  tab: "jalankan",
  modelPick: null,
  models: [],
  providers: [],
  provider: "",
  threadsOpen: false,
  toolsOpen: false,
  detailTask: null,
};

/* --------------------------------------------------------------- helpers */
const esc = (s) => String(s == null ? "" : s)
  .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
  .replace(/"/g, "&quot;")
  .replace(/\u2014/g, ",");            /* no em dash anywhere in the UI */

const stripProvider = (m) => (!m ? "" : (m.includes("/") ? m.split("/").slice(1).join("/") : m));

const clock = (ts) => ts ? new Date(ts * 1000).toLocaleTimeString("id-ID", { hour: "2-digit", minute: "2-digit" }) : "";
const when = (ts) => ts ? new Date(ts * 1000).toLocaleString("id-ID", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }) : "";
const secs = (a, b) => (a && b) ? Math.max(1, Math.round(b - a)) + "s" : "";

const STATUS = {
  running: ["sedang dikerjakan", "warn"],
  done: ["selesai", "ok"],
  error: ["gagal", "bad"],
  interrupted: ["terputus", "bad"],
};

function statusTag(st) {
  const w = STATUS[st] || [st || "tidak diketahui", ""];
  return `<span class="tag ${w[1]}">${esc(w[0])}</span>`;
}

/* light markdown: paragraphs, bullets, fenced code, inline code */
function rich(text) {
  const src = esc(text || "").trim();
  if (!src) return "";
  const parts = src.split(/```/);
  let html = "";
  parts.forEach((chunk, i) => {
    if (i % 2) { html += `<pre>${chunk.replace(/^\w*\n/, "")}</pre>`; return; }
    chunk.split(/\n{2,}/).forEach((block) => {
      const b = block.trim();
      if (!b) return;
      if (/^[-*] /m.test(b)) {
        const items = b.split(/\n/).filter((l) => /^[-*] /.test(l.trim())).map((l) => `<li>${l.trim().replace(/^[-*] /, "")}</li>`).join("");
        html += `<ul>${items}</ul>`;
      } else {
        html += `<p>${b.replace(/\n/g, "<br>").replace(/`([^`]+)`/g, "<code>$1</code>")}</p>`;
      }
    });
  });
  return html;
}

async function api(path, opt) {
  try {
    const r = await fetch(path, opt || {});
    try { return await r.json(); } catch { return { ok: false, error: "balasan bukan JSON" }; }
  } catch (e) { return { ok: false, error: String(e && e.message || e) }; }
}
const post = (p, body) => api(p, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) });

function toast(text, kind) {
  const box = $("#toasts");
  const t = el("div", "toast " + (kind || ""));
  t.innerHTML = `<span>${esc(text)}</span>`;
  const x = el("button", "x", "\u00d7");
  x.setAttribute("aria-label", "Tutup pesan");
  x.onclick = () => t.remove();
  t.appendChild(x);
  box.appendChild(t);
  setTimeout(() => { if (t.isConnected) t.remove(); }, kind === "bad" ? 9000 : 5000);
}

/* ------------------------------------------------------------ scrolling */
const scroller = () => $("#messages");
function nearBottom() {
  const c = scroller();
  return c.scrollHeight - c.scrollTop - c.clientHeight < 120;
}
function toBottom(force) {
  const c = scroller();
  if (force || nearBottom()) c.scrollTop = c.scrollHeight;
}

/* ticker text comes straight from a worker's stdout: strip the progress chatter
   and the punctuation the models like to sprinkle in */
function cleanLine(s) {
  return String(s || "")
    .replace(/\u2014/g, ",")
    .replace(/^\[[^\]]+\]\s*/, "")
    .replace(/^(working|thinking|processing|starting)[.\u2026\s]*$/i, "")
    .replace(/\s+/g, " ")
    .trim();
}

/* ------------------------------------------------------------- messages */
function turnUser(m) {
  const li = el("li", "turn me");
  li.dataset.task = m.task || "";
  li.innerHTML = `<div class="bubble">${rich(m.text)}</div><div class="stamp">${clock(m.ts)}</div>`;
  return li;
}

function turnAstro(m) {
  const li = el("li", "turn astro");
  li.dataset.task = m.task || "";
  li.dataset.role = "astroz";
  const st = m.status || "running";
  const done = st === "done" || st === "error" || st === "interrupted";
  const dur = m.ts ? secs(m.created, m.ts) : "";
  const tags = [
    statusTag(st),
    m.size ? `<span class="tag">${esc(m.size)}</span>` : "",
    (m.workers || []).length ? `<span class="tag">${esc((m.workers || []).join(", "))}</span>` : "",
    m.model ? `<span class="tag">${esc(stripProvider(m.model))}</span>` : "",
    m.tests === true ? `<span class="tag ok">tes lulus</span>` : "",
    m.tests === false && !m.tests_skipped ? `<span class="tag bad">tes gagal</span>` : "",
    m.review ? `<span class="tag ${String(m.review).toUpperCase().startsWith("PASS") ? "ok" : "warn"}">penilaian ${esc(String(m.review).toLowerCase())}</span>` : "",
  ].filter(Boolean).join("");

  const body = m.text ? `<div class="answer">${rich(m.text)}</div>` : "";
  const working = done ? "" : `<div class="working"><span class="bars"><i></i><i></i><i></i><i></i></span><span>sedang dikerjakan</span></div>
     <div class="ticker" id="tick-${esc(m.task)}">menyiapkan rencana</div>`;
  const empty = done && !m.text ? `<p class="note" style="margin:0">Tidak ada jawaban yang bisa dibaca. Buka aktivitas untuk melihat keluaran mentah.</p>` : "";

  li.innerHTML = `<div class="bubble">${body}${empty}${working}
      <div class="meta">${tags}</div>
      <div class="meta"><button class="btn sm ghost" data-act="open">Lihat aktivitas</button></div>
      <div class="stamp">${clock(m.ts)}${dur ? " · " + dur : ""}</div>
    </div>`;
  li.querySelector("[data-act=open]").onclick = () => openActivity(m.task);
  return li;
}

function renderMessages(force) {
  const box = $("#messages");
  const stick = force || nearBottom();
  box.innerHTML = "";
  if (!S.messages.length) {
    box.appendChild(el("div", "wrap", `
      <div class="empty">
        <h2>Tulis apa yang mau dikerjakan</h2>
        <p>AstroZ meneruskan pesanmu ke tim: satu perencana, empat pekerja, lalu satu penilai.
        Jawabannya muncul di sini. Proses kerjanya ada di panel aktivitas, terpisah dari percakapan.</p>
      </div>`));
    return;
  }
  const frag = document.createDocumentFragment();
  const wrap = el("div", "wrap");
  S.messages.forEach((m) => wrap.appendChild(m.role === "user" ? turnUser(m) : turnAstro(m)));
  frag.appendChild(wrap);
  box.appendChild(frag);
  if (stick) toBottom(true);
}

function findTurn(tid) { return document.querySelector(`.turn.astro[data-task="${tid}"]`); }

function patchTurn(tid, patch) {
  const li = findTurn(tid);
  if (!li) return false;
  const bubble = li.querySelector(".bubble");
  const answer = bubble.querySelector(".answer");
  if (patch.text !== undefined) {
    if (answer) answer.innerHTML = rich(patch.text);
    else {
      const a = el("div", "answer", rich(patch.text));
      bubble.insertBefore(a, bubble.firstChild);
    }
  }
  if (patch.status) {
    const tag = bubble.querySelector(".meta .tag");
    const w = STATUS[patch.status] || [patch.status, ""];
    if (tag) { tag.className = "tag " + w[1]; tag.textContent = w[0]; }
    if (patch.status !== "running") {
      const wk = bubble.querySelector(".working");
      if (wk) wk.remove();
      const tk = bubble.querySelector(".ticker");
      if (tk) tk.remove();
    }
  }
  if (patch.ticker) {
    const tk = li.querySelector(".ticker");
    if (tk) tk.textContent = patch.ticker;
  }
  return true;
}

/* --------------------------------------------------------------- threads */
async function loadThreads() {
  const r = await api("/api/sessions");
  S.sessions = (r && r.sessions) || [];
  renderThreads();
}

function renderThreads() {
  const box = $("#thread-list");
  box.innerHTML = "";
  if (!S.sessions.length) {
    box.appendChild(el("div", "empty", "<p>Belum ada percakapan.</p>"));
    return;
  }
  S.sessions.forEach((s) => {
    const b = el("button", "thread");
    b.setAttribute("aria-current", String(s.id === S.sid));
    b.innerHTML = `<span class="t">${esc(s.title)}</span>
      <span class="m">${esc((s.last || "").trim() || "belum ada isi")}</span>
      <span class="row"><span class="pip ${s.running ? "" : "idle"}"></span>
      <span class="m" style="margin:0">${s.task_count} pesan${s.running ? " · sedang jalan" : ""}</span></span>`;
    b.onclick = () => { openSession(s.id); closeDrawers(); };
    box.appendChild(b);
  });
}

async function openSession(sid, keep) {
  S.sid = sid;
  localStorage.setItem("astroz.sid", sid);
  const r = await api("/api/sessions/" + encodeURIComponent(sid));
  if (!r || !r.ok) {
    toast("Percakapan tidak bisa dibuka", "bad");
    return;
  }
  S.messages = r.messages || [];
  S.activity = r.activity || {};
  S.running = new Set(S.messages.filter((m) => m.role === "astroz" && m.status === "running").map((m) => m.task));
  $("#chat-title").textContent = r.session.title || "Percakapan";
  renderMessages(true);
  renderRuns();
  if (!keep) $("#input").focus();
}

async function newSession() {
  const r = await post("/api/sessions", {});
  if (!r || !r.ok) { toast("Gagal membuat percakapan", "bad"); return; }
  await loadThreads();
  await openSession(r.session.id);
  closeDrawers();
}

async function ensureSession() {
  if (S.sid) return S.sid;
  const r = await post("/api/sessions", {});
  if (r && r.ok) { S.sid = r.session.id; localStorage.setItem("astroz.sid", r.session.id); await loadThreads(); }
  return S.sid;
}

/* -------------------------------------------------------------- composer */
async function send() {
  const box = $("#input");
  const text = box.value.trim();
  if (!text) { toast("Tulis dulu pesannya.", "bad"); box.focus(); return; }
  await ensureSession();
  const btn = $("#send");
  btn.disabled = true;
  box.disabled = true;
  const r = await post("/api/chat", { text, session: S.sid, workflow: $("#size").value });
  btn.disabled = false;
  box.disabled = false;
  if (!r || !r.ok) {
    toast("Gagal mengirim: " + ((r && r.error) || "tidak diketahui"), "bad");
    return;
  }
  box.value = "";
  box.style.height = "auto";
  S.sid = r.session;
  localStorage.setItem("astroz.sid", r.session);
  S.running.add(r.task_id);
  S.messages.push({ role: "user", text, ts: Date.now() / 1000, task: r.task_id });
  S.messages.push({ role: "astroz", text: "", ts: 0, task: r.task_id, status: "running", workers: [], model: "" });
  renderMessages(true);
  renderRuns();
  loadThreads();
}

/* ------------------------------------------------------------ activity UI */
function openActivity(tid) {
  S.detailTask = tid;
  const task = (S.messages.find((m) => m.task === tid && m.role === "astroz")) || {};
  $("#detail-title").textContent = (S.messages.find((m) => m.task === tid && m.role === "user") || {}).text || "Aktivitas";
  renderActivity(tid);
  $("#activity-drawer").classList.add("on");
  $("#activity-drawer").setAttribute("aria-hidden", "false");
}
function closeActivity() {
  $("#activity-drawer").classList.remove("on");
  $("#activity-drawer").setAttribute("aria-hidden", "true");
  S.detailTask = null;
}

function evLine(e) {
  const d = el("div", "ev");
  const text = e.text || "";
  const long = text.length > 240;
  d.innerHTML = `<span class="t">${clock(e.ts)}</span><span class="k k-${esc(e.kind)}">${esc(e.kind)}</span>`
    + `<span class="body">${esc(long ? text.slice(0, 240) + "\u2026" : text)}</span>`;
  if (long) {
    const b = el("button", "more", "lihat semua");
    b.setAttribute("aria-expanded", "false");
    b.onclick = (ev) => {
      ev.stopPropagation();
      const on = b.getAttribute("aria-expanded") === "true";
      b.setAttribute("aria-expanded", String(!on));
      d.querySelector(".body").textContent = on ? text.slice(0, 240) + "\u2026" : text;
      b.textContent = on ? "lihat semua" : "tutup";
    };
    d.appendChild(b);
  }
  return d;
}

function renderActivity(tid) {
  const evs = (S.activity[tid] || []);
  const task = S.messages.find((m) => m.task === tid && m.role === "astroz") || {};
  const box = $("#detail-body");
  box.innerHTML = "";

  const tags = [
    statusTag(task.status || "running"),
    task.size ? `<span class="tag">${esc(task.size)}</span>` : "",
    task.model ? `<span class="tag">${esc(stripProvider(task.model))}</span>` : "",
    task.tests === true ? `<span class="tag ok">tes lulus</span>` : "",
    task.tests === false && !task.tests_skipped ? `<span class="tag bad">tes gagal</span>` : "",
  ].filter(Boolean).join("");
  box.appendChild(el("div", "meta", tags));

  /* supervisor first: the plan and the verdict are the decisions */
  const plan = evs.find((e) => e.kind === "plan" && e.plan);
  if (plan && plan.plan) {
    box.appendChild(el("h2", null, "Rencana dari perencana"));
    box.appendChild(el("pre", "out", esc(JSON.stringify(plan.plan, null, 1))));
  }

  const byWorker = {};
  evs.filter((e) => e.kind === "worker" && e.worker).forEach((e) => {
    const w = byWorker[e.worker] || (byWorker[e.worker] = { lines: [], end: null, start: null });
    if (e.phase === "out" && e.text) w.lines.push(e.text.replace(/^\[[^\]]+\]\s*/, ""));
    if (e.phase === "end") w.end = e;
    if (e.phase === "start") w.start = e;
  });
  const names = Object.keys(byWorker);
  if (names.length) {
    box.appendChild(el("h2", null, "Pekerja"));
    names.forEach((n) => {
      const w = byWorker[n];
      const d = el("div", "worker");
      d.innerHTML = `<div class="top"><span class="nm">${esc(n)}</span>
        ${w.end ? `<span class="tag ${w.end.ok ? "ok" : "bad"}">${w.end.ok ? "selesai" : "gagal"}</span>` : `<span class="tag warn">jalan</span>`}
        ${w.end && w.end.duration ? `<span class="tag">${Math.round(w.end.duration)}s</span>` : ""}</div>`;
      const body = (w.lines.join("\n") || "").trim();
      if (body) d.appendChild(el("pre", "out", esc(body.slice(-4000))));
      box.appendChild(d);
    });
  }

  const tests = evs.filter((e) => e.kind === "test" && e.phase === "end");
  if (tests.length) {
    const t = tests[tests.length - 1];
    box.appendChild(el("h2", null, "Tes"));
    box.appendChild(el("pre", "out", esc(`${t.ok ? "LULUS" : "TIDAK LULUS"} · kode ${t.rc} · ${Math.round(t.duration || 0)}s\n\n${(t.output || "").slice(-3000)}`)));
  }

  const rev = evs.filter((e) => e.kind === "review" && e.phase === "end");
  if (rev.length) {
    box.appendChild(el("h2", null, "Penilaian"));
    box.appendChild(el("pre", "out", esc((rev[rev.length - 1].text || "").slice(0, 4000))));
  }

  const git = evs.filter((e) => e.kind === "git");
  if (git.length) {
    box.appendChild(el("h2", null, "Perubahan berkas"));
    box.appendChild(el("pre", "out", esc(git.map((g) => g.text || "").join("\n").slice(0, 4000))));
  }

  box.appendChild(el("h2", null, "Semua kejadian"));
  const feed = el("div", "feed");
  if (!evs.length) feed.innerHTML = '<div class="empty">Belum ada kejadian.</div>';
  else evs.forEach((e) => feed.appendChild(evLine(e)));
  box.appendChild(feed);
  feed.scrollTop = feed.scrollHeight;
}

function appendActivity(e) {
  if (!e || !e.task) return;
  const list = S.activity[e.task] || (S.activity[e.task] = []);
  list.push(e);
  if (list.length > 400) list.shift();
  if (S.detailTask === e.task) renderActivity(e.task);
  renderRuns();
}

/* --------------------------------------------------------------- runs pane */
function renderRuns() {
  const box = $("#runs");
  if (!box) return;
  box.innerHTML = "";
  const tasks = [];
  const seen = new Set();
  S.messages.filter((m) => m.role === "astroz").forEach((m) => {
    if (!seen.has(m.task)) { seen.add(m.task); tasks.push(m); }
  });
  if (!tasks.length) {
    box.innerHTML = '<div class="empty"><p>Belum ada pekerjaan di percakapan ini.</p></div>';
    return;
  }
  tasks.reverse().forEach((m) => {
    const prompt = (S.messages.find((x) => x.task === m.task && x.role === "user") || {}).text || "";
    const st = m.status || "running";
    const w = STATUS[st] || [st, ""];
    const b = el("button", "run");
    b.innerHTML = `<span class="l1"><span class="pip ${st === "running" ? "" : "idle"}"></span>
        <span class="ttl">${esc(prompt.slice(0, 90))}</span>
        <span class="tag ${w[1]}">${esc(w[0])}</span></span>
      <span class="l2">${esc((m.workers || []).join(", ") || "belum mulai")}${m.model ? " · " + esc(stripProvider(m.model)) : ""}</span>`;
    b.onclick = () => openActivity(m.task);
    box.appendChild(b);
  });
}

/* ------------------------------------------------------------- tools pane */
function setTab(tab) {
  S.tab = tab;
  $$("#tool-seg button").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.pane === tab)));
  $$(".pane").forEach((p) => p.classList.toggle("on", p.id === "pane-" + tab));
  if (tab === "model") loadModels();
  if (tab === "berkas") { loadTree(); loadGit(); }
  if (tab === "log") fillLog();
}

/* model */
async function loadModels() {
  const q = ($("#model-search").value || "").trim();
  const onlyOk = $("#model-ok").checked;
  const url = "/api/gateway/models?limit=400" + (onlyOk ? "&only_healthy=1" : "")
    + (S.provider ? "&provider=" + encodeURIComponent(S.provider) : "")
    + (q ? "&q=" + encodeURIComponent(q) : "");
  const r = await api(url);
  const box = $("#model-list");
  if (!r || r.error) { box.innerHTML = '<div class="empty"><p>Gagal memuat daftar model.</p></div>'; return; }
  S.models = r.models || [];
  S.providers = r.providers || [];
  const cur = r.current || "";
  $("#model-now").textContent = cur || "belum dipilih";
  renderProviders();
  box.innerHTML = "";
  if (!S.models.length) {
    box.innerHTML = '<div class="empty"><p>Belum ada model yang cocok. Tekan "Muat dari gateway" untuk membaca ulang daftarnya.</p></div>';
    return;
  }
  const list = el("div", "list");
  S.models.slice(0, 150).forEach((m) => {
    const b = el("button", "row2" + (m.id === (S.modelPick || cur) ? " pick" : ""));
    const caps = m.caps || {};
    b.innerHTML = `<span class="grow"><span>${esc(stripProvider(m.id))}</span><br>
        <span class="path">${esc(m.provider || "")}${caps.contextWindow ? " · " + Math.round(caps.contextWindow / 1000) + "k" : ""}${m.callable ? " · bisa dipanggil" : ""}</span></span>
      ${m.id === cur ? '<span class="tag ok">dipakai</span>' : ""}
      ${m.health && m.health.ok ? `<span class="tag ok">hidup</span>` : (m.health ? '<span class="tag bad">tidak menjawab</span>' : "")}`;
    b.onclick = () => { S.modelPick = m.id; loadModels(); $("#apply-model").disabled = false; $("#pick-note").textContent = "Dipilih: " + m.id; };
    list.appendChild(b);
  });
  box.appendChild(list);
  if (S.models.length > 150) box.appendChild(el("p", "note", `Menampilkan 150 dari ${r.total} model. Persempit dengan pencarian atau provider.`));
}

function renderProviders() {
  const box = $("#providers");
  if (!box) return;
  box.innerHTML = "";
  const all = el("button", "tag" + (S.provider ? "" : " ok"), "semua");
  all.onclick = () => { S.provider = ""; loadModels(); };
  box.appendChild(all);
  S.providers.slice(0, 12).forEach((p) => {
    const b = el("button", "tag" + (S.provider === p.id ? " ok" : ""), `${p.id} ${p.count}`);
    b.onclick = () => { S.provider = p.id; loadModels(); };
    box.appendChild(b);
  });
}

async function loadWorkers() {
  const r = await api("/api/state");
  if (!r || !r.workers) return;
  const box = $("#workers");
  box.innerHTML = "";
  r.workers.forEach((w) => {
    const cfg = (r.worker_cfg || {})[w.key] || {};
    const d = el("div", "worker");
    d.innerHTML = `<div class="top"><span class="pip ${w.installed ? "" : "idle"}"></span>
        <span class="nm">${esc(w.label || w.key)}</span>
        <span class="tag ${w.installed ? "ok" : "bad"}">${w.installed ? "terpasang" : "tidak ada"}</span></div>
      <div class="p">${esc(w.version || w.error || "versi tidak diketahui")}</div>
      <div class="p">${esc(w.path || "-")}</div>`;
    const row = el("div", "btnrow");
    row.style.marginTop = "8px";
    const lab = el("label", "sw");
    lab.innerHTML = `<input type="checkbox" ${cfg.enabled !== false ? "checked" : ""}> dipakai`;
    lab.querySelector("input").onchange = (e) => saveWorker(w.key, { enabled: e.target.checked });
    const mi = el("input");
    mi.placeholder = "paksa model lain";
    mi.value = cfg.model || "";
    mi.setAttribute("aria-label", "Model khusus untuk " + (w.label || w.key));
    mi.onchange = () => saveWorker(w.key, { model: mi.value });
    const pb = el("button", "btn sm ghost", "Periksa");
    pb.onclick = async () => {
      pb.disabled = true; pb.textContent = "Memeriksa";
      await post(`/api/workers/${w.key}/probe`);
      pb.disabled = false; pb.textContent = "Periksa";
      loadWorkers();
    };
    row.appendChild(lab); row.appendChild(pb);
    d.appendChild(mi); d.appendChild(row);
    box.appendChild(d);
  });
}

async function saveWorker(k, patch) {
  const r = await post("/api/workers/" + k, patch);
  if (!r || r.ok === false) toast("Gagal menyimpan setelan pekerja", "bad");
  loadWorkers();
}

/* files, git, tests */
async function loadTree() {
  const r = await api("/api/project/tree");
  const box = $("#tree");
  if (!r || r.error) { box.innerHTML = '<div class="empty"><p>Gagal memuat daftar berkas.</p></div>'; return; }
  $("#proj-dir").textContent = r.dir || "";
  box.innerHTML = "";
  const entries = r.entries || [];
  if (!entries.length) { box.innerHTML = '<div class="empty"><p>Folder ini masih kosong.</p></div>'; return; }
  entries.forEach((e) => {
    if (e.type === "dir") { box.appendChild(el("div", "dir", esc(e.path))); return; }
    const b = el("button", "file", `${esc(e.path)} <span class="tag">${e.size}b</span>`);
    b.onclick = async () => {
      const f = await api("/api/project/file?path=" + encodeURIComponent(e.path));
      $("#file-out").textContent = (f && f.ok) ? f.content : "Gagal membuka berkas: " + ((f && f.error) || "tidak diketahui");
      $("#file-name").textContent = e.path;
    };
    box.appendChild(b);
  });
}

async function loadGit() {
  const g = await api("/api/git");
  if (!g || g.error) { $("#git-out").textContent = "Gagal memuat status git."; return; }
  $("#git-out").textContent =
    (g.branch ? "Cabang: " + g.branch + "\n" : "")
    + (g.status ? "Belum disimpan:\n" + g.status + "\n" : "Tidak ada perubahan yang menunggu.\n")
    + (g.diffstat ? "\nRingkasan:\n" + g.diffstat + "\n" : "")
    + "\nCommit terakhir:\n" + (g.log || "(belum ada)");
  const d = await api("/api/git/diff");
  $("#diff-out").textContent = (d && d.diff) || "Tidak ada perbedaan.";
}

async function runTest() {
  const out = $("#test-out");
  out.textContent = "Menjalankan tes";
  const r = await post("/api/test", { command: $("#test-cmd").value || null });
  const res = (r && r.result) || {};
  if (!r || r.error) { out.textContent = "Gagal menjalankan tes: " + ((r && r.error) || "tidak diketahui"); return; }
  out.textContent = (res.skipped ? "Tidak ada perintah tes yang bisa dijalankan."
    : `${res.ok ? "LULUS" : "TIDAK LULUS"} · kode ${res.rc} · ${res.duration || 0} detik\n\n`) + (res.output || "");
}

/* ------------------------------------------------------------- SSE stream */
function handleEvent(e) {
  pushLog(e);
  if (e.session && e.session !== S.sid && e.kind !== "system") { loadThreads(); }
  if (!e.task) {
    if (e.kind === "gateway" || e.kind === "system") loadStateChips();
    return;
  }
  const mine = S.messages.some((m) => m.task === e.task);
  appendActivity(e);
  if (!mine) { if (e.kind === "task" && e.phase === "done") loadThreads(); return; }

  if (e.kind === "worker" && e.phase === "out") {
    const line = cleanLine(e.text);
    if (line) patchTurn(e.task, { ticker: line.slice(0, 180) });
  } else if (e.kind === "worker" && e.phase === "start") {
    patchTurn(e.task, { ticker: `pekerja ${e.worker || ""} mulai` });
  } else if (e.kind === "plan" && e.phase === "start") {
    patchTurn(e.task, { ticker: "menyusun rencana" });
  } else if (e.kind === "test" && e.phase === "end") {
    patchTurn(e.task, { ticker: e.ok ? "tes lulus" : "tes belum lulus, mencoba perbaikan" });
  } else if (e.kind === "review" && e.phase === "end") {
    patchTurn(e.task, { ticker: "penilaian: " + (e.verdict || "selesai") });
  } else if (e.kind === "task" && e.phase === "answer") {
    patchTurn(e.task, { text: e.answer || "" });
  } else if (e.kind === "task" && (e.phase === "done" || e.phase === "error")) {
    patchTurn(e.task, { status: e.phase === "done" ? "done" : "error" });
    S.running.delete(e.task);
    const m = S.messages.find((x) => x.task === e.task && x.role === "astroz");
    if (m) { m.status = e.phase === "done" ? "done" : "error"; m.ts = Date.now() / 1000; }
    refreshTask(e.task);
    loadThreads();
    renderRuns();
  }
}

async function refreshTask(tid) {
  if (!S.sid) return;
  const r = await api("/api/sessions/" + encodeURIComponent(S.sid));
  if (!r || !r.ok) return;
  const before = S.messages.length;
  S.messages = r.messages || [];
  S.activity = r.activity || {};
  const li = findTurn(tid);
  if (li && r.messages) {
    const m = r.messages.find((x) => x.task === tid && x.role === "astroz");
    if (m) { const fresh = turnAstro(m); li.replaceWith(fresh); toBottom(); }
  } else if (S.messages.length !== before) {
    renderMessages(true);
  }
  renderRuns();
}

async function loadStateChips() {
  const r = await api("/api/state");
  if (!r || !r.gateway) return;
  const g = r.gateway;
  const chip = $("#chip-model");
  chip.textContent = stripProvider(g.model) || "belum ada model";
  chip.title = g.model || "";
  const gw = $("#chip-gw");
  gw.className = "tag " + (g.online ? "ok" : "bad");
  gw.textContent = g.online ? "gateway hidup" : "gateway mati";
  $("#foot-info").textContent = `${g.base_url || "-"} · ${g.model_count || 0} model · proyek ${(r.project || {}).dir || "-"}`;
}

/* ------------------------------------------------------------- drawers */
function closeDrawers() {
  $("#threads").classList.remove("on");
  $("#tools").classList.remove("on");
  $("#scrim").classList.remove("on");
}
function openThreads() { $("#threads").classList.add("on"); $("#scrim").classList.add("on"); }
function openTools() { $("#tools").classList.add("on"); $("#scrim").classList.add("on"); }

/* --------------------------------------------------------------- log pane */
const LOG_KINDS = ["worker", "plan", "test", "review", "git", "gateway", "hermes", "system", "log", "discuss"];
let LOG_MAX_ID = 0;
let LOG_FILLED = null;

async function fillLog() {
  const box = $("#log-feed");
  if (!box) return;
  const kind = $("#log-filter").value;
  if (kind === LOG_FILLED) return;
  box.innerHTML = '<div class="empty">Memuat catatan</div>';
  const r = await api("/api/events/recent?limit=300" + (kind ? "&kind=" + encodeURIComponent(kind) : ""));
  const events = (r && r.events) || [];
  box.innerHTML = "";
  if (!events.length) {
    box.innerHTML = '<div class="empty"><p>Belum ada catatan untuk saringan ini.</p></div>';
    LOG_FILLED = kind;
    return;
  }
  events.forEach((e) => { if (LOG_KINDS.includes(e.kind)) box.appendChild(evLine(e)); });
  if (!box.children.length) box.innerHTML = '<div class="empty"><p>Belum ada catatan untuk saringan ini.</p></div>';
  else box.scrollTop = box.scrollHeight;
  LOG_MAX_ID = Math.max(LOG_MAX_ID, ...events.map((e) => e.id || 0));
  LOG_FILLED = kind;
}

function pushLog(e) {
  if (!LOG_KINDS.includes(e.kind)) return;
  if ((e.id || 0) <= LOG_MAX_ID) return;
  const sel = $("#log-filter");
  if (sel && sel.value && e.kind !== sel.value) return;
  const box = $("#log-feed");
  if (!box) return;
  if (box.querySelector(".empty")) box.innerHTML = "";
  box.appendChild(evLine(e));
  while (box.children.length > 400) box.removeChild(box.firstChild);
  const stick = box.scrollTop + box.clientHeight >= box.scrollHeight - 40;
  if (stick) box.scrollTop = box.scrollHeight;
  LOG_MAX_ID = Math.max(LOG_MAX_ID, e.id || 0);
}

/* ------------------------------------------------------------------ boot */
function wire() {
  $("#composer").addEventListener("submit", (e) => { e.preventDefault(); send(); });
  const ta = $("#input");
  ta.addEventListener("input", () => {
    ta.style.height = "auto";
    ta.style.height = Math.min(190, ta.scrollHeight) + "px";
  });
  ta.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); }
  });
  $("#new-thread").onclick = newSession;
  $("#open-threads").onclick = openThreads;
  $("#open-tools").onclick = openTools;
  $("#close-activity").onclick = closeActivity;
  $("#activity-drawer").querySelector(".scrim").onclick = closeActivity;
  $("#scrim").onclick = closeDrawers;
  $("#log-filter").onchange = () => { LOG_FILLED = null; fillLog(); };
  $("#log-clear").onclick = () => {
    $("#log-feed").innerHTML = '<div class="empty"><p>Tampilan dikosongkan. Catatan baru muncul di sini.</p></div>';
    LOG_FILLED = $("#log-filter").value;
  };
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") { closeActivity(); closeDrawers(); }
  });
  $$("[data-close]").forEach((b) => b.onclick = closeDrawers);
  $$("#tool-seg button").forEach((b) => b.onclick = () => setTab(b.dataset.pane));
  $$("#file-seg button").forEach((b) => b.onclick = () => {
    $$("#file-seg button").forEach((x) => x.setAttribute("aria-selected", String(x === b)));
    $$(".fpane").forEach((p) => p.classList.toggle("on", p.id === "f-" + b.dataset.f));
    if (b.dataset.f === "git") loadGit();
  });
  $("#model-search").oninput = () => { clearTimeout(window.__mt); window.__mt = setTimeout(loadModels, 250); };
  $("#model-ok").onchange = loadModels;
  $("#model-sync").onclick = async () => {
    const b = $("#model-sync"); b.disabled = true; b.textContent = "Memuat";
    const r = await post("/api/gateway/sync?apply=0");
    b.disabled = false; b.textContent = "Muat dari gateway";
    if (!r || r.error) { toast("Gagal memuat daftar model", "bad"); return; }
    toast(`${r.models || 0} model terbaca dari gateway`, "ok");
    loadModels(); loadStateChips();
  };
  $("#model-probe").onclick = async () => {
    const b = $("#model-probe"); b.disabled = true; b.textContent = "Menguji";
    const r = await post("/api/gateway/probe", {});
    b.disabled = false; b.textContent = "Tes mana yang hidup";
    if (!r || r.error) { toast("Gagal menguji model", "bad"); return; }
    toast(`${(r.healthy || []).length} dari ${(r.results || []).length} model menjawab`, (r.healthy || []).length ? "ok" : "bad");
    loadModels();
  };
  let armed = false;
  $("#apply-model").onclick = async () => {
    if (!S.modelPick) { toast("Pilih dulu satu model", "bad"); return; }
    if (!armed) {
      armed = true;
      $("#apply-model").textContent = "Tekan sekali lagi untuk menerapkan";
      setTimeout(() => { armed = false; $("#apply-model").textContent = "Terapkan ke semua"; }, 6000);
      return;
    }
    armed = false;
    const b = $("#apply-model"); b.disabled = true; b.textContent = "Menerapkan";
    const r = await post("/api/gateway/model", { model: S.modelPick, apply_workers: true });
    b.disabled = false; b.textContent = "Terapkan ke semua";
    if (!r || r.error) { toast("Gagal menerapkan model", "bad"); return; }
    const bad = Object.entries(r.workers || {}).filter(([, v]) => !v.ok).map(([k]) => k);
    toast(bad.length ? `Diterapkan, gagal di: ${bad.join(", ")}` : "Model diterapkan ke semua pekerja", bad.length ? "bad" : "ok");
    loadStateChips(); loadModels(); loadWorkers();
  };
  $("#proj-refresh").onclick = loadTree;
  $("#git-refresh").onclick = loadGit;
  $("#test-run").onclick = runTest;
  $("#git-commit-save").onclick = async () => {
    const msg = $("#git-msg").value.trim();
    if (!msg) { toast("Tulis dulu pesan commit-nya.", "bad"); return; }
    const r = await post("/api/git/commit", { message: msg });
    if (!r || !r.ok) { toast("Commit gagal: " + ((r && (r.error || r.out)) || "tidak diketahui"), "bad"); return; }
    toast("Perubahan sudah disimpan sebagai commit", "ok");
    $("#git-msg").value = "";
    loadGit();
  };
  $("#workers-apply").onclick = async () => {
    const r = await post("/api/apply", {});
    if (!r || r.error) { toast("Gagal menerapkan", "bad"); return; }
    toast("Model diterapkan ke semua pekerja", "ok");
    loadWorkers(); loadStateChips();
  };
  $("#workers-probe").onclick = async () => {
    const r = await api("/api/state");
    for (const w of (r.workers || [])) await post(`/api/workers/${w.key}/probe`);
    toast("Semua pekerja diperiksa", "ok");
    loadWorkers();
  };
}

async function boot() {
  wire();
  setTab("jalankan");
  await loadStateChips();
  await loadThreads();
  if (S.sid && S.sessions.some((s) => s.id === S.sid)) await openSession(S.sid, true);
  else if (S.sessions.length) await openSession(S.sessions[0].id, true);
  else { $("#chat-title").textContent = "Percakapan baru"; renderMessages(true); }
  loadWorkers();
  fillLog();
  const es = new EventSource("/api/events?replay=60");
  es.onmessage = (m) => { let e; try { e = JSON.parse(m.data); } catch { return; } handleEvent(e); };
  es.onerror = () => { $("#chip-gw").className = "tag bad"; $("#chip-gw").textContent = "sambungan putus"; };
  setInterval(loadStateChips, 20000);
}

boot();
