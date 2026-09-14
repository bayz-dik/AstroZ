/* AstroZ. Satu berkas, tanpa kerangka kerja. Lihat DESIGN.md untuk arah tampilan. */

const el = (id) => document.getElementById(id);
const alur = el("alur");
const keadaan = {
  sesi: null,
  judul: "",
  entri: [],
  nomor: 0,
  tugasJalan: null,
  lampiran: null,
  kejadianTerakhir: 0,
  modelSekarang: "",
  pekerja: [],
  sehat: [],
};

/* ------------------------------------------------------------------ bantuan */

async function minta(jalan, opsi) {
  const r = await fetch(jalan, opsi);
  const teks = await r.text();
  let data = {};
  try { data = teks ? JSON.parse(teks) : {}; } catch { data = { teks }; }
  if (!r.ok) throw new Error(data.error || `permintaan gagal (${r.status})`);
  return data;
}
const ambil = (jalan) => minta(jalan);
const kirim = (jalan, isi) => minta(jalan, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(isi || {}),
});

function pesanSingkat(teks, galat) {
  const kotak = el("pesan-singkat");
  kotak.textContent = teks;
  kotak.className = "pesan-singkat";
  if (galat) kotak.style.color = "var(--galat)";
  else kotak.style.color = "";
  clearTimeout(kotak._jam);
  kotak._jam = setTimeout(() => { kotak.textContent = ""; }, 4200);
}

function waktu(ts) {
  if (!ts) return "";
  const d = new Date(ts * 1000);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleTimeString("id-ID", { hour: "2-digit", minute: "2-digit" });
}

function tanggalPendek(ts) {
  if (!ts) return "";
  const d = new Date(ts * 1000);
  if (Number.isNaN(d.getTime())) return "";
  const hari = Math.floor((Date.now() / 1000 - ts) / 86400);
  if (hari <= 0) return waktu(ts);
  if (hari === 1) return "kemarin";
  return d.toLocaleDateString("id-ID", { day: "numeric", month: "short" });
}

function buat(tag, kelas, teks) {
  const n = document.createElement(tag);
  if (kelas) n.className = kelas;
  if (teks !== undefined && teks !== null) n.textContent = teks;
  return n;
}

/* -------------------------------------------------------------------- tema */

function pakaiTema(nama) {
  document.documentElement.dataset.tema = nama;
  try { localStorage.setItem("astroz-tema", nama); } catch {}
  for (const b of document.querySelectorAll("[data-pilih-tema]")) {
    b.setAttribute("aria-pressed", String(b.dataset.pilihTema === nama));
  }
  const gelap = nama === "gelap";
  const meta = document.querySelector('meta[name="theme-color"]');
  if (meta) meta.setAttribute("content", gelap ? "#262624" : "#FAF9F5");
}
try {
  const simpan = localStorage.getItem("astroz-tema");
  if (simpan) pakaiTema(simpan);
  else if (window.matchMedia("(prefers-color-scheme: dark)").matches) pakaiTema("gelap");
} catch {}
for (const b of document.querySelectorAll("[data-pilih-tema]")) {
  b.addEventListener("click", () => pakaiTema(b.dataset.pilihTema));
}

/* ------------------------------------------------------------------ lapisan */

function bukaLembar(id) {
  const l = el(id);
  l.classList.add("tampil");
  l.setAttribute("aria-hidden", "false");
  el("tirai").classList.add("tampil");
}
function tutupSemuaLembar() {
  for (const l of document.querySelectorAll(".lembar")) {
    l.classList.remove("tampil");
    l.setAttribute("aria-hidden", "true");
  }
  el("tirai").classList.remove("tampil");
}
el("tirai").addEventListener("click", tutupSemuaLembar);
for (const b of document.querySelectorAll("[data-tutup]")) b.addEventListener("click", tutupSemuaLembar);
document.addEventListener("keydown", (e) => { if (e.key === "Escape") tutupSemuaLembar(); });

/* Susunan: di layar lebar panel jadi kolom, di HP jadi lembar geser. Satu
   simpul dipindah, bukan digandakan, supaya isinya tidak pernah berbeda.
   Di 1000-1199px kolom tengah terlalu sempit untuk kolom alat, jadi alat
   dipindah ke lembar geser dan tombolnya dimunculkan lagi. */
const lebar = window.matchMedia("(min-width: 1000px)");
const cukup = window.matchMedia("(min-width: 1200px)");
function susun() {
  const isi = document.querySelector(".isi");
  const chat = document.querySelector(".chat");
  if (lebar.matches) {
    isi.insertBefore(el("rail-sesi"), chat);
    isi.appendChild(el("aktivitas"));
  } else {
    el("isi-lembar-sesi").appendChild(el("rail-sesi"));
    el("isi-lembar-alat").appendChild(el("aktivitas"));
  }
  document.body.classList.toggle("sempit-lebar", lebar.matches && !cukup.matches);
}
lebar.addEventListener("change", () => { tutupSemuaLembar(); susun(); });
cukup.addEventListener("change", () => { tutupSemuaLembar(); susun(); });
susun();

el("buka-sesi").addEventListener("click", () => bukaLembar("lembar-sesi"));
el("buka-alat").addEventListener("click", () => bukaLembar("lembar-alat"));

/* ------------------------------------------------------- panel alat: tab */

for (const b of document.querySelectorAll("#tab-alat [role=tab]")) {
  b.addEventListener("click", () => {
    for (const x of document.querySelectorAll("#tab-alat [role=tab]")) {
      x.setAttribute("aria-selected", String(x === b));
    }
    for (const p of document.querySelectorAll("#aktivitas .panel")) {
      p.hidden = p.id !== "panel-" + b.dataset.panel;
    }
  });
}

/* ------------------------------------------------------------------- chat */

function tambahEntri(entri) {
  entri.no = ++keadaan.nomor;
  keadaan.entri.push(entri);
  gambarEntri(entri);
  keDasar();
}

function gambarEntri(e) {
  const baris = buat("article", `entri ${e.peran} ${e.status || ""}`);
  baris.dataset.no = e.no;
  baris.appendChild(buat("span", "no", String(e.no).padStart(2, "0")));
  const badan = buat("div", "badan");

  if (e.lampiran) {
    badan.appendChild(buat("span", "lampiran", "gambar: " + e.lampiran.split("/").pop()));
  }
  const gelembung = buat("div", "gelembung", e.teks || (e.peran === "astroz" && e.status === "jalan" ? "sedang dikerjakan" : ""));
  if (e.peran === "astroz" && e.status === "jalan") gelembung.classList.add("shimmer");
  badan.appendChild(gelembung);

  const meta = buat("div", "meta");
  if (e.peran === "aku") {
    meta.appendChild(buat("span", null, waktu(e.ts)));
  } else {
    const cap = buat("span", "cap " + (e.status || ""));
    cap.textContent = e.status === "jalan" ? "sedang jalan"
      : e.status === "gagal" ? "gagal"
      : e.status === "selesai" ? "selesai" : "jawaban";
    meta.appendChild(cap);
    if (e.worker) meta.appendChild(buat("span", null, e.worker));
    if (e.size) meta.appendChild(buat("span", null, e.size));
    if (e.tes === true) meta.appendChild(buat("span", null, "tes lulus"));
    if (e.tes === false) meta.appendChild(buat("span", null, "tes gagal"));
    if (e.ts) meta.appendChild(buat("span", null, waktu(e.ts)));
    if (e.tugas) {
      const b = buat("button", null, "lihat proses");
      b.type = "button";
      b.addEventListener("click", () => bukaRincian(e.tugas));
      meta.appendChild(b);
    }
  }
  badan.appendChild(meta);
  baris.appendChild(badan);
  alur.appendChild(baris);
  return baris;
}

function keDasar() {
  alur.scrollTop = alur.scrollHeight;
}

function kosongkanChat(pesanKosong) {
  alur.replaceChildren();
  keadaan.entri = [];
  keadaan.nomor = 0;
  if (pesanKosong) {
    const p = buat("p", "kosong", pesanKosong);
    alur.appendChild(p);
  }
}

/* --------------------------------------------------------------- percakapan */

function gambarDaftarSesi(daftar) {
  const wadah = el("daftar-sesi");
  wadah.replaceChildren();
  if (!daftar.length) {
    wadah.appendChild(buat("p", "kosong", "Belum ada percakapan. Tulis perintah di kotak bawah, percakapan pertama dibuat sendiri."));
    return;
  }
  for (const s of daftar) {
    const baris = buat("div", "baris-sesi");
    const b = buat("button");
    b.type = "button";
    if (s.id === keadaan.sesi) b.setAttribute("aria-current", "true");
    b.appendChild(buat("div", "judul", s.title || "tanpa judul"));
    if (s.last) b.appendChild(buat("div", "cuplik", s.last));
    b.appendChild(buat("div", "waktu", `${tanggalPendek(s.updated || s.created)}  ${(s.tasks || []).length} tugas`));
    b.addEventListener("click", () => { bukaSesi(s.id); tutupSemuaLembar(); });
    const hapus = buat("button", "hapus", "hapus");
    hapus.type = "button";
    hapus.setAttribute("aria-label", "hapus percakapan " + (s.title || ""));
    hapus.addEventListener("click", async (ev) => {
      ev.stopPropagation();
      if (!confirm("Hapus percakapan ini dari daftar? Tugas dan berkasnya tetap ada.")) return;
      await minta(`/api/sessions/${s.id}`, { method: "DELETE" });
      if (s.id === keadaan.sesi) { keadaan.sesi = null; kosongkanChat("Belum ada percakapan yang dibuka."); }
      await muatSesi();
      pesanSingkat("Percakapan dihapus dari daftar.");
    });
    baris.append(b, hapus);
    wadah.appendChild(baris);
  }
}

async function muatSesi() {
  try {
    const d = await ambil("/api/sessions");
    gambarDaftarSesi(d.sessions || []);
  } catch (e) {
    el("daftar-sesi").replaceChildren(buat("p", "kosong", "Daftar percakapan tidak bisa dimuat: " + e.message));
  }
}

async function bukaSesi(id) {
  keadaan.sesi = id;
  try {
    const d = await ambil(`/api/sessions/${id}`);
    const s = d.session || {};
    keadaan.judul = s.title || "Percakapan";
    el("judul-sesi").textContent = keadaan.judul;
    kosongkanChat(null);
    const pesan = d.messages || [];
    if (!pesan.length) kosongkanChat("Percakapan ini masih kosong.");
    for (const m of pesan) {
      tambahEntri({
        peran: m.role === "user" ? "aku" : "astroz",
        teks: m.text,
        ts: m.ts,
        tugas: m.task,
        status: m.role === "user" ? "" : (m.status === "done" ? "selesai" : m.status === "failed" || m.status === "error" ? "gagal" : m.status === "running" ? "jalan" : ""),
        tes: m.tests === undefined ? undefined : m.tests,
        size: m.size,
      });
    }
    const jalan = pesan.filter((m) => m.role !== "user" && m.status === "running").map((m) => m.task);
    keadaan.tugasJalan = jalan.length ? jalan[jalan.length - 1] : null;
    gambarProses(s.tasks || [], d.activity || {});
    if (keadaan.tugasJalan) pantauTugas(keadaan.tugasJalan);
  } catch (e) {
    pesanSingkat("Percakapan tidak bisa dibuka: " + e.message, true);
  }
  await muatSesi();
}

el("sesi-baru").addEventListener("click", () => {
  keadaan.sesi = null;
  keadaan.judul = "Percakapan baru";
  el("judul-sesi").textContent = keadaan.judul;
  kosongkanChat("Percakapan baru. Tulis perintah pertama di kotak bawah.");
  el("daftar-proses").replaceChildren(buat("p", "kosong", "Belum ada pekerjaan di percakapan ini."));
  el("tulis").focus();
  muatSesi();
});

/* --------------------------------------------------------------- kirim tugas */

el("pilih-gambar").addEventListener("click", () => el("berkas-gambar").click());

el("berkas-gambar").addEventListener("change", async (ev) => {
  const berkas = ev.target.files && ev.target.files[0];
  if (!berkas) return;
  if (berkas.size > 12 * 1024 * 1024) { pesanSingkat("Gambar lebih dari 12 MB, perkecil dulu.", true); return; }
  const buf = await berkas.arrayBuffer();
  let biner = "";
  const bytes = new Uint8Array(buf);
  for (let i = 0; i < bytes.length; i += 8192) biner += String.fromCharCode.apply(null, bytes.subarray(i, i + 8192));
  try {
    const d = await kirim("/api/upload", { name: berkas.name, data: btoa(biner) });
    keadaan.lampiran = d.path;
    const wadah = el("lampiran");
    wadah.replaceChildren();
    wadah.hidden = false;
    wadah.appendChild(buat("span", "lampiran", "gambar siap dikirim: " + berkas.name));
    const batal = buat("button", "tombol kecil diam", "batalkan");
    batal.type = "button";
    batal.addEventListener("click", () => { keadaan.lampiran = null; wadah.hidden = true; wadah.replaceChildren(); });
    wadah.appendChild(batal);
    pesanSingkat("Gambar disimpan. Pekerja akan membacanya dengan perintah lihat.");
  } catch (e) {
    pesanSingkat("Gambar gagal disimpan: " + e.message, true);
  }
  ev.target.value = "";
});

el("form-tulis").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const kotak = el("tulis");
  const teks = kotak.value.trim();
  if (!teks) { pesanSingkat("Tulis dulu isi pesannya."); kotak.focus(); return; }
  const lampiran = keadaan.lampiran;
  let penuh = teks;
  if (lampiran) penuh += `\n\nGambar terlampir: ${lampiran}\nPakai perintah lihat untuk membacanya.`;

  el("kirim").disabled = true;
  tambahEntri({ peran: "aku", teks, ts: Date.now() / 1000, lampiran });
  kotak.value = "";
  keadaan.lampiran = null;
  el("lampiran").hidden = true;
  el("lampiran").replaceChildren();

  try {
    const d = await kirim("/api/chat", { text: penuh, session: keadaan.sesi, workflow: el("ukuran").value });
    keadaan.sesi = d.session;
    keadaan.judul = d.title || keadaan.judul;
    el("judul-sesi").textContent = keadaan.judul;
    const e = { peran: "astroz", teks: "sedang dikerjakan", ts: Date.now() / 1000, status: "jalan", tugas: d.task_id, no: ++keadaan.nomor };
    keadaan.entri.push(e);
    gambarEntri(e);
    keDasar();
    keadaan.tugasJalan = d.task_id;
    pantauTugas(d.task_id);
    muatSesi();
  } catch (err) {
    tambahEntri({ peran: "astroz", teks: "Pesan tidak terkirim: " + err.message, status: "gagal", ts: Date.now() / 1000 });
    pesanSingkat("Pesan tidak terkirim: " + err.message, true);
  } finally {
    el("kirim").disabled = false;
    kotak.focus();
  }
});

el("tulis").addEventListener("keydown", (ev) => {
  if (ev.key === "Enter" && !ev.shiftKey) {
    ev.preventDefault();
    el("form-tulis").requestSubmit();
  }
});

/* ------------------------------------------------------------------ pantau */

let jamPantau = null;

async function pantauTugas(tid) {
  clearInterval(jamPantau);
  let lewat = 0;
  ticker(true);
  jamPantau = setInterval(async () => {
    lewat += 3;
    try {
      const d = await ambil(`/api/tasks/${tid}`);
      const t = d.task || {};
      const entri = keadaan.entri.find((x) => x.tugas === tid && x.peran === "astroz");
      const status = t.status === "done" ? "selesai" : t.status === "failed" || t.status === "error" ? "gagal" : "jalan";
      const jawab = t.answer || "";
      if (entri && (entri.status !== status || (jawab && entri.teks !== jawab))) {
        entri.status = status;
        entri.teks = jawab || entri.teks;
        entri.ts = t.finished || entri.ts;
        entri.tes = (t.test || {}).ok;
        entri.worker = (t.workers || [])[0];
        gambarUlangSemua();
      }
      if (status !== "jalan") {
        clearInterval(jamPantau);
        ticker(false);
        keadaan.tugasJalan = null;
        if (keadaan.sesi) bukaSesiRingan(keadaan.sesi);
      }
    } catch {
      if (lewat > 900) { clearInterval(jamPantau); ticker(false); }
    }
  }, 3000);
}

function gambarUlangSemua() {
  const daftar = keadaan.entri.slice();
  alur.replaceChildren();
  for (const e of daftar) gambarEntri(e);
  keDasar();
}

async function bukaSesiRingan(id) {
  try {
    const d = await ambil(`/api/sessions/${id}`);
    gambarProses((d.session || {}).tasks || [], d.activity || {});
  } catch {}
  muatSesi();
}

/* Garis kilau di bawah bar: menyala hanya selama ada tugas berjalan. */
function ticker(aktif) {
  const t = el("ticker");
  if (t) t.classList.toggle("aktif", !!aktif);
}

/* -------------------------------------------------------- panel: proses */

function gambarProses(ids, aktivitas) {
  const wadah = el("daftar-proses");
  wadah.replaceChildren();
  if (!ids || !ids.length) {
    wadah.appendChild(buat("p", "kosong", "Belum ada pekerjaan di percakapan ini."));
    return;
  }
  for (const tid of ids.slice().reverse()) {
    const evs = aktivitas[tid] || [];
    const baris = buat("div", "baris-data");
    const atas = buat("div", "atas");
    atas.appendChild(buat("span", "nama", tid));
    const jalan = evs.some((e) => e.kind === "task" && e.phase === "created") && !evs.some((e) => e.phase === "done" || e.phase === "failed");
    atas.appendChild(buat("span", "tanda-cap " + (jalan ? "" : "ada"), jalan ? "jalan" : "tercatat"));
    baris.appendChild(atas);
    const terakhir = evs[evs.length - 1];
    if (terakhir) baris.appendChild(buat("div", "kecil", (terakhir.text || "").slice(0, 120)));
    const b = buat("button", "tombol kecil garis", "lihat rincian");
    b.type = "button";
    b.addEventListener("click", () => bukaRincian(tid));
    baris.appendChild(b);
    wadah.appendChild(baris);
  }
}

async function bukaRincian(tid) {
  el("judul-rincian").textContent = "Tugas " + tid;
  const isi = el("isi-rincian");
  isi.replaceChildren(buat("p", "kosong", "memuat"));
  bukaLembar("lembar-rincian");
  try {
    const d = await ambil(`/api/tasks/${tid}`);
    const t = d.task || {};
    isi.replaceChildren();
    const info = buat("div", "baris-data");
    info.appendChild(buat("div", "nama", "keadaan: " + (t.status || "?")));
    info.appendChild(buat("div", "kecil", "ukuran: " + (t.size || "otomatis") + "  model: " + (t.model || "bawaan") + "  pekerja: " + ((t.workers || []).join(", ") || "belum tercatat")));
    if (t.answer) info.appendChild(buat("div", "kecil", t.answer));
    isi.appendChild(info);
    for (const e of (d.events || []).slice().reverse()) {
      const baris = buat("div", "kejadian");
      baris.dataset.jenis = e.kind || "";
      baris.appendChild(buat("div", "waktu", waktu(e.ts)));
      const tengah = buat("div");
      tengah.appendChild(buat("div", "jenis", e.kind || ""));
      tengah.appendChild(buat("div", "pesan", e.text || e.message || ""));
      baris.appendChild(tengah);
      isi.appendChild(baris);
    }
    if (!(d.events || []).length) isi.appendChild(buat("p", "kosong", "Belum ada catatan untuk tugas ini."));
  } catch (e) {
    isi.replaceChildren(buat("p", "kosong", "Rincian tidak bisa dimuat: " + e.message));
  }
}

/* --------------------------------------------------------- panel: model */

let modelTersaring = { q: "", provider: "", hanyaHidup: false };

function tandaCap(ada, teks) {
  const n = buat("span", "tanda-cap " + (ada ? "ada" : "tidak"), teks);
  return n;
}

function gambarDaftarModel(d) {
  const wadah = el("daftar-model");
  wadah.replaceChildren();
  const daftar = d.models || [];
  if (!daftar.length) {
    wadah.appendChild(buat("p", "kosong", "Tidak ada model yang cocok. Coba muat dari gateway atau ubah kata kunci."));
    return;
  }
  wadah.appendChild(buat("p", "catatan", `${d.total} model cocok, ${daftar.length} ditampilkan.`));
  for (const m of daftar) {
    const caps = m.caps || {};
    const baris = buat("div", "baris-data");
    const atas = buat("div", "atas");
    atas.appendChild(buat("span", "nama", m.id));
    if (m.id === d.current) atas.appendChild(buat("span", "tanda-cap ada", "dipakai"));
    baris.appendChild(atas);
    const deret = buat("div", "meta");
    deret.appendChild(tandaCap(!!caps.vision, "gambar"));
    deret.appendChild(tandaCap(!!caps.search, "cari"));
    const sehat = (m.health || {}).ok;
    deret.appendChild(buat("span", null, sehat === true ? "sudah diuji hidup" : sehat === false ? "tidak menjawab" : "belum diuji"));
    if (m.provider) deret.appendChild(buat("span", null, m.provider));
    baris.appendChild(deret);
    const b = buat("button", "tombol kecil garis", m.id === d.current ? "sedang dipakai" : "pakai model ini");
    b.type = "button";
    b.disabled = m.id === d.current;
    b.addEventListener("click", () => pakaiModel(m.id));
    baris.appendChild(b);
    wadah.appendChild(baris);
  }
}

function gambarProvider(providers) {
  const wadah = el("daftar-provider");
  wadah.replaceChildren();
  const semua = buat("button", "tombol kecil" + (modelTersaring.provider ? " garis" : ""), "semua");
  semua.type = "button";
  semua.addEventListener("click", () => { modelTersaring.provider = ""; muatModel(); });
  wadah.appendChild(semua);
  for (const p of providers || []) {
    const b = buat("button", "tombol kecil" + (modelTersaring.provider === p.id ? "" : " garis"), `${p.id} ${p.count}`);
    b.type = "button";
    b.addEventListener("click", () => { modelTersaring.provider = p.id; muatModel(); });
    wadah.appendChild(b);
  }
}

async function muatModel() {
  const p = new URLSearchParams({ limit: "120", callable_only: "1" });
  if (modelTersaring.q) p.set("q", modelTersaring.q);
  if (modelTersaring.provider) p.set("provider", modelTersaring.provider);
  if (modelTersaring.hanyaHidup) p.set("only_healthy", "1");
  try {
    const d = await ambil("/api/gateway/models?" + p.toString());
    gambarDaftarModel(d);
    gambarProvider(d.providers);
    keadaan.modelSekarang = d.current || "";
    const gw = await ambil("/api/state");
    const caps = ((gw.gateway || {}).model_meta || {})[d.current] || {};
    const c = caps.caps || {};
    el("model-sekarang").textContent = `${d.current || "belum dipilih"}  |  ${c.vision ? "bisa melihat gambar" : "tidak bisa melihat gambar"}  |  ${c.search ? "bisa mencari sendiri" : "tidak mencari sendiri"}`;
    el("model-kini").textContent = d.current || "";
    el("keadaan-gateway").textContent = (gw.gateway || {}).online ? "gateway hidup" : "gateway tidak menjawab";
    el("keadaan-gateway").className = "keadaan " + ((gw.gateway || {}).online ? "hidup" : "mati");
  } catch (e) {
    el("daftar-model").replaceChildren(buat("p", "kosong", "Daftar model tidak bisa dimuat: " + e.message));
  }
}

el("cari-model").addEventListener("input", (ev) => {
  modelTersaring.q = ev.target.value.trim();
  clearTimeout(el("cari-model")._jam);
  el("cari-model")._jam = setTimeout(muatModel, 300);
});
el("hanya-hidup").addEventListener("change", (ev) => { modelTersaring.hanyaHidup = ev.target.checked; muatModel(); });
el("model-sinkron").addEventListener("click", async () => {
  el("model-sinkron").disabled = true;
  try { const d = await kirim("/api/gateway/sync"); pesanSingkat(`Katalog dimuat: ${d.count || d.model_count || 0} model.`); await muatModel(); }
  catch (e) { pesanSingkat("Gagal memuat katalog: " + e.message, true); }
  finally { el("model-sinkron").disabled = false; }
});
el("model-uji").addEventListener("click", async () => {
  el("model-uji").disabled = true;
  pesanSingkat("Menguji model, perlu beberapa detik.");
  try { const d = await kirim("/api/gateway/probe", {}); pesanSingkat(`${(d.healthy || []).length} dari ${(d.results || []).length} model menjawab.`); await muatModel(); }
  catch (e) { pesanSingkat("Uji model gagal: " + e.message, true); }
  finally { el("model-uji").disabled = false; }
});

async function pakaiModel(id) {
  el("catatan-model").textContent = "menerapkan " + id + " ...";
  try {
    await kirim("/api/gateway/model", { model: id, apply_workers: true });
    el("catatan-model").textContent = id + " dipakai di Hermes dan keempat pekerja.";
    pesanSingkat(id + " sekarang dipakai.");
    await muatModel();
    await muatPekerja();
  } catch (e) {
    el("catatan-model").textContent = "gagal: " + e.message;
    pesanSingkat("Gagal memakai model: " + e.message, true);
  }
}
el("pakai-model").addEventListener("click", () => {
  if (keadaan.modelSekarang) pakaiModel(keadaan.modelSekarang);
  else pesanSingkat("Pilih dulu satu model dari daftar.");
});

/* -------------------------------------------------------- panel: pekerja */

function gambarPekerja(daftar) {
  const wadah = el("daftar-pekerja");
  wadah.replaceChildren();
  keadaan.pekerja = daftar;
  for (const w of daftar) {
    const baris = buat("div", "baris-data");
    const atas = buat("div", "atas");
    atas.appendChild(buat("span", "nama", w.name));
    atas.appendChild(buat("span", "tanda-cap " + (w.available ? "ada" : ""), w.available ? "siap" : "tidak ada"));
    baris.appendChild(atas);
    baris.appendChild(buat("div", "kecil", w.version || w.error || "versi belum diperiksa"));
    if (w.model) baris.appendChild(buat("div", "kecil", "model: " + w.model));
    const deret = buat("div", "meta");
    const label = buat("label");
    label.style.display = "flex";
    label.style.gap = "8px";
    label.style.alignItems = "center";
    const cek = document.createElement("input");
    cek.type = "checkbox";
    cek.checked = w.enabled !== false;
    cek.addEventListener("change", async () => {
      await kirim(`/api/workers/${w.name}`, { enabled: cek.checked });
      pesanSingkat(`${w.name} ${cek.checked ? "dipakai" : "dimatikan"}.`);
    });
    label.append(cek, document.createTextNode("pakai pekerja ini"));
    deret.appendChild(label);
    const b = buat("button", null, "periksa");
    b.type = "button";
    b.addEventListener("click", async () => {
      b.textContent = "memeriksa";
      try { const d = await kirim(`/api/workers/${w.name}/probe`); pesanSingkat(`${w.name}: ${d.version || d.error || "selesai"}`); }
      catch (e) { pesanSingkat(`${w.name}: ${e.message}`, true); }
      finally { await muatPekerja(); }
    });
    deret.appendChild(b);
    baris.appendChild(deret);
    wadah.appendChild(baris);
  }
}

async function muatPekerja() {
  try {
    const d = await ambil("/api/workers");
    gambarPekerja(d.workers || []);
  } catch (e) {
    el("daftar-pekerja").replaceChildren(buat("p", "kosong", "Daftar pekerja tidak bisa dimuat: " + e.message));
  }
}

el("periksa-pekerja").addEventListener("click", async () => {
  el("periksa-pekerja").disabled = true;
  for (const w of keadaan.pekerja) {
    try { await kirim(`/api/workers/${w.name}/probe`); } catch {}
  }
  await muatPekerja();
  el("periksa-pekerja").disabled = false;
  pesanSingkat("Pemeriksaan pekerja selesai.");
});

el("terapkan-pekerja").addEventListener("click", async () => {
  try { await kirim("/api/apply", { model: keadaan.modelSekarang }); pesanSingkat("Model diterapkan ke pekerja."); await muatPekerja(); }
  catch (e) { pesanSingkat("Gagal menerapkan model: " + e.message, true); }
});

/* ---------------------------------------------------------- panel: berkas */

async function muatBerkas() {
  try {
    const d = await ambil("/api/project/tree");
    el("dir-kerja").textContent = "Folder kerja: " + d.dir;
    const wadah = el("pohon-berkas");
    wadah.replaceChildren();
    const entries = d.entries || [];
    if (!entries.length) wadah.appendChild(buat("p", "kosong", "Folder kerja masih kosong."));
    for (const b of entries) {
      const tombol = buat("button", null, `${b.type === "dir" ? "[folder] " : ""}${b.path}${b.size ? "  " + b.size + " b" : ""}`);
      tombol.type = "button";
      if (b.type === "dir") tombol.disabled = true;
      else tombol.addEventListener("click", () => bukaBerkas(b.path));
      wadah.appendChild(tombol);
    }
  } catch (e) {
    el("pohon-berkas").replaceChildren(buat("p", "kosong", "Daftar berkas tidak bisa dimuat: " + e.message));
  }
}

async function bukaBerkas(path) {
  el("nama-berkas").textContent = path;
  el("isi-berkas").textContent = "memuat";
  try {
    const d = await ambil("/api/project/file?path=" + encodeURIComponent(path));
    el("isi-berkas").textContent = d.content || "(berkas kosong)";
  } catch (e) {
    el("isi-berkas").textContent = "Berkas tidak bisa dibaca: " + e.message;
  }
}

async function muatGit() {
  try {
    const d = await ambil("/api/git");
    el("keadaan-git").textContent = [d.branch ? "cabang " + d.branch : "", d.clean ? "tidak ada perubahan tertunda" : "ada perubahan belum disimpan", d.out || ""].filter(Boolean).join("\n");
    const diff = await ambil("/api/git/diff");
    el("beda-git").textContent = (diff.diff || "(tidak ada perbedaan)").slice(0, 6000);
  } catch (e) {
    el("keadaan-git").textContent = "Keadaan git tidak bisa dibaca: " + e.message;
  }
}

el("muat-berkas").addEventListener("click", () => { muatBerkas(); muatGit(); });
el("simpan-commit").addEventListener("click", async () => {
  const pesan = el("pesan-commit").value.trim();
  if (!pesan) { pesanSingkat("Tulis dulu pesan commit-nya."); el("pesan-commit").focus(); return; }
  try {
    const d = await kirim("/api/git/commit", { message: pesan });
    pesanSingkat(d.noop ? "Tidak ada perubahan untuk disimpan." : "Commit tersimpan.");
    el("pesan-commit").value = "";
    muatGit();
  } catch (e) { pesanSingkat("Commit gagal: " + e.message, true); }
});
el("jalankan-tes").addEventListener("click", async () => {
  el("hasil-tes").textContent = "menjalankan";
  try {
    const d = await kirim("/api/test", { command: el("perintah-tes").value.trim() });
    const r = d.result || {};
    el("hasil-tes").textContent = `perintah: ${r.command || "-"}\nlulus: ${r.ok ? "ya" : "tidak"}\n\n${r.out || ""}`.slice(0, 8000);
  } catch (e) { el("hasil-tes").textContent = "Tes gagal dijalankan: " + e.message; }
});

/* --------------------------------------------------------- panel: catatan */

function tambahCatatan(e) {
  const wadah = el("isi-catatan");
  const saring = el("saring-catatan").value;
  if (saring && e.kind !== saring) return;
  const baris = buat("div", "kejadian");
  baris.dataset.jenis = e.kind || "";
  baris.appendChild(buat("div", "waktu", waktu(e.ts)));
  const tengah = buat("div");
  tengah.appendChild(buat("div", "jenis", e.kind || ""));
  tengah.appendChild(buat("div", "pesan", e.text || e.message || ""));
  baris.appendChild(tengah);
  wadah.prepend(baris);
  while (wadah.children.length > 400) wadah.lastChild.remove();
}

async function muatCatatan(ulang) {
  if (ulang) el("isi-catatan").replaceChildren();
  try {
    const d = await ambil("/api/events/recent?limit=200");
    const daftar = (d.events || []).slice().reverse();
    for (const e of daftar) tambahCatatan(e);
  } catch {}
}

el("saring-catatan").addEventListener("change", () => muatCatatan(true));
el("bersihkan-catatan").addEventListener("click", () => muatCatatan(true));

/* ------------------------------------------------------------------- mulai */

function sambungKejadian() {
  try {
    const sumber = new EventSource("/api/events");
    sumber.onmessage = (ev) => {
      try {
        const e = JSON.parse(ev.data);
        tambahCatatan(e);
        if (e.task && keadaan.tugasJalan === e.task && e.phase === "done") {
          clearInterval(jamPantau);
          pantauTugas(e.task);
        }
      } catch {}
    };
  } catch {}
}

async function mulai() {
  await Promise.all([muatSesi(), muatModel(), muatPekerja(), muatBerkas(), muatGit(), muatCatatan(false)]);
  sambungKejadian();
  const d = await ambil("/api/state").catch(() => null);
  if (d) {
    const gw = d.gateway || {};
    el("keadaan-gateway").textContent = gw.online ? "gateway hidup" : "gateway tidak menjawab";
    el("keadaan-gateway").className = "keadaan " + (gw.online ? "hidup" : "mati");
    el("model-kini").textContent = gw.model || "";
    el("dir-kerja").textContent = "Folder kerja: " + ((d.project || {}).dir || "");
    gambarAlat(gw);
  }
  const daftar = await ambil("/api/sessions").catch(() => ({ sessions: [] }));
  const sesi = (daftar.sessions || [])[0];
  if (sesi) bukaSesi(sesi.id);
  else kosongkanChat("Belum ada percakapan. Tulis perintah di kotak bawah, percakapan pertama dibuat sendiri.");
}

function gambarAlat(gw) {
  const wadah = el("daftar-alat");
  wadah.replaceChildren();
  const alat = [
    ["cari \"kata kunci\"", "mencari di web, hasilnya judul, tautan, dan ringkasan. Ada juga --berita untuk kepala berita terbaru."],
    ["buka <url>", "membuka satu halaman web dan mengembalikan isinya sebagai teks."],
    ["lihat <berkas>", "membaca berkas gambar jadi teks, memakai model " + (gw.vision_model || "yang bisa melihat gambar") + "."],
  ];
  for (const [nama, keterangan] of alat) {
    const baris = buat("div", "baris-data");
    baris.appendChild(buat("div", "nama", nama));
    baris.appendChild(buat("div", "kecil", keterangan));
    wadah.appendChild(baris);
  }
}

mulai();
