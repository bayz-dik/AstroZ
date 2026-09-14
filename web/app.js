/* AstroZ. Satu berkas, tanpa kerangka kerja. Lihat design-systems/claude-code/. */

const el = (id) => document.getElementById(id);
const kolom = () => el("kolom-chat");
const keadaan = {
  sesi: null,
  judul: "",
  pesan: [],
  tugasJalan: null,
  lampiran: null,
  modelSekarang: "",
  pekerja: [],
  modelTersaring: { q: "", hanyaHidup: false },
  modelLembar: { q: "", hanyaHidup: false },
  pindah: new Set(),        // id tugas yang sudah dipindah dari aktivitas ke chat
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
const kirim = (jalan, isi, metode = "POST") => minta(jalan, {
  method: metode,
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(isi || {}),
});

function pesanSingkat(teks, galat) {
  const kotak = el("pesan-singkat");
  kotak.textContent = teks;
  kotak.style.color = galat ? "#FFD9D6" : "";
  kotak.style.background = galat ? "var(--galat)" : "var(--tinta)";
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

function sapaanWaktu() {
  const j = new Date().getHours();
  if (j < 11) return "Selamat pagi";
  if (j < 15) return "Selamat siang";
  if (j < 19) return "Selamat sore";
  return "Selamat malam";
}

/* -------------------------------------------------------------------- tema */

function pakaiTema(nama) {
  document.documentElement.dataset.tema = nama;
  try { localStorage.setItem("astroz-tema", nama); } catch {}
  for (const b of document.querySelectorAll("[data-pilih-tema]")) {
    b.setAttribute("aria-pressed", String(b.dataset.pilihTema === nama));
  }
  const meta = document.querySelector('meta[name="theme-color"]');
  if (meta) meta.setAttribute("content", nama === "gelap" ? "#262624" : "#FAF9F5");
}
try {
  const simpan = localStorage.getItem("astroz-tema");
  if (simpan) pakaiTema(simpan);
  else if (window.matchMedia("(prefers-color-scheme: dark)").matches) pakaiTema("gelap");
} catch {}
for (const b of document.querySelectorAll("[data-pilih-tema]")) {
  b.addEventListener("click", () => { pakaiTema(b.dataset.pilihTema); tutupMenuTitik(); });
}
el("sapaan").textContent = sapaanWaktu();

/* ------------------------------------------------------------------ lapisan */

function bukaLembar(id) {
  const l = el(id);
  if (!l) return;
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
document.addEventListener("keydown", (e) => { if (e.key === "Escape") { tutupSemuaLembar(); tutupMenuTitik(); } });

function tutupMenuTitik() {
  el("menu-titik").hidden = true;
  el("buka-titik").setAttribute("aria-expanded", "false");
}
el("buka-titik").addEventListener("click", () => {
  const m = el("menu-titik");
  m.hidden = !m.hidden;
  el("buka-titik").setAttribute("aria-expanded", String(!m.hidden));
});
document.addEventListener("click", (e) => {
  if (!el("menu-titik").hidden && !e.target.closest("#menu-titik") && !e.target.closest("#buka-titik")) tutupMenuTitik();
});

/* susunan: 1280px ke atas tiga kolom; 1000-1279px dua kolom dengan panel
   pekerjaan sebagai lembar geser; di bawah 1000px semuanya lembar geser.
   Satu simpul dipindah, bukan digandakan. */
const layar = {
  alat: window.matchMedia("(min-width: 1000px)"),
  aktivitas: window.matchMedia("(min-width: 1280px)"),
};
function susun() {
  const isi = document.querySelector(".isi");
  const panel = el("aktivitas");
  if (layar.alat.matches) {
    // Di >=1280px ruangnya cukup untuk percakapan + panel pekerjaan
    // berdampingan. Di bawah itu panelnya masuk lembar alat lewat wadahnya,
    // yang tinggal di dalam lembar itu di HTML.
    if (layar.aktivitas.matches) {
      isi.appendChild(el("wadah-aktivitas"));
      isi.appendChild(panel);
    } else {
      el("wadah-aktivitas").appendChild(panel);
    }
  } else {
    el("wadah-aktivitas").appendChild(panel);
  }
  // Wadah disembunyikan hanya saat panelnya ada di kolom kanan: anak grid yang
  // display:none tidak ikut menghitung kolom, dan itu yang membuat grid dua
  // kolom tetap dua kolom. Di dalam lembar alat wadahnya harus hidup, kalau
  // tidak panel kerjanya tampil kosong.
  el("wadah-aktivitas").hidden = layar.aktivitas.matches;
}
for (const m of [layar.alat, layar.aktivitas]) m.addEventListener("change", () => { tutupSemuaLembar(); susun(); });
susun();

el("buka-alat").addEventListener("click", () => bukaLembar("lembar-alat"));
el("buka-sesi").addEventListener("click", () => { pindahAlat("obrolan"); bukaLembar("lembar-alat"); });
el("tombol-plus").addEventListener("click", () => bukaLembar("lembar-plus"));
el("pil-model").addEventListener("click", () => { bukaLembar("lembar-model"); muatModelLembar(); });
el("aksi-plugin").addEventListener("click", () => { tutupSemuaLembar(); pindahAlat("plugin"); bukaLembar("lembar-alat"); });
el("aksi-skill").addEventListener("click", () => { tutupSemuaLembar(); pindahAlat("skill"); bukaLembar("lembar-alat"); });
el("aksi-pekerja").addEventListener("click", () => { tutupSemuaLembar(); pindahAlat("pekerja"); bukaLembar("lembar-alat"); });
el("aksi-gambar").addEventListener("click", () => el("berkas-gambar").click());
el("aksi-berkas").addEventListener("click", () => el("berkas-apa").click());
el("buka-pasang-plugin").addEventListener("click", () => bukaLembar("lembar-plugin"));

/* Menu titik tiga: hal-hal yang tidak punya tempat lain. Menu garis tiga
   memegang daftar fitur, jadi di sini hanya aksi untuk percakapan yang
   sedang dibuka. */
for (const b of document.querySelectorAll("[data-aksi]")) {
  b.addEventListener("click", async () => {
    tutupMenuTitik();
    const aksi = b.dataset.aksi;
    if (aksi === "ganti-nama") return bukaLembar("lembar-nama");
    if (aksi === "kerja") return pindahAlat("kerja");
    if (aksi === "bagikan") return salinPercakapan();
    if (aksi === "tema-gelap") return pakaiTema("gelap");
    if (aksi === "tema-terang") return pakaiTema("terang");
  });
}

/* panel alat: satu bagian terlihat pada satu waktu */
function pindahAlat(nama) {
  for (const b of document.querySelectorAll("#nav-alat button")) {
    b.setAttribute("aria-current", String(b.dataset.alat === nama));
  }
  const judul = { obrolan: "Percakapan", plugin: "Plugin MCP", skill: "Skill dari GitHub",
                  pekerja: "Pekerja", berkas: "Berkas dan tes", catatan: "Catatan",
                  model: "Model", kerja: "Kerja" };
  el("judul-alat").textContent = judul[nama] || "Alat";

  const bagianAktivitas = { berkas: "berkas", catatan: "catatan", model: "model", kerja: "proses" }[nama];
  if (!bagianAktivitas) {
    for (const p of document.querySelectorAll("#badan-alat .panel")) p.hidden = true;
    const tujuan = el({ obrolan: "alat-obrolan", plugin: "alat-plugin", skill: "alat-skill",
                        pekerja: "alat-pekerja" }[nama] || "alat-obrolan");
    if (tujuan) tujuan.hidden = false;
    return;
  }
  // Berkas, catatan, model, dan kerja memakai panel aktivitas yang sama,
  // bukan salinan.
  pindahTab(bagianAktivitas);
  // Berkas, catatan, dan model hidup di kolom kanan pada layar lebar. Di bawah
  // itu panelnya dipindah ke dalam lembar ini oleh susun(), jadi bagian
  // aktivitas selalu ditampilkan lewat lembar: membuka lembar saat panelnya
  // ada di kolom kanan justru memperlihatkan lembar kosong.
  if (layar.aktivitas.matches) {
    tutupSemuaLembar();
    const panel = el("aktivitas");
    panel.classList.add("sorot");
    setTimeout(() => panel.classList.remove("sorot"), 900);
    return;
  }
  bukaLembar("lembar-alat");
  el("alat-aktivitas").hidden = false;
  // Hanya panel milik lembar ini yang disembunyikan. Selektor tanpa ">" ikut
  // mengenai panel-proses/berkas/catatan/model yang bersarang di dalam panel
  // kerja, jadi bagian yang baru saja dibuka lewat pindahTab() langsung
  // disembunyikan lagi dan panelnya tampak kosong.
  for (const p of document.querySelectorAll("#badan-alat > .panel")) {
    if (p.id !== "alat-aktivitas") p.hidden = true;
  }
  if (nama === "kerja") gambarKerja();
}
for (const b of document.querySelectorAll("#nav-alat button")) {
  b.addEventListener("click", () => pindahAlat(b.dataset.alat));
}
for (const b of document.querySelectorAll("#tab-alat [role=tab]")) {
  b.addEventListener("click", () => pindahTab(b.dataset.panel));
}

/* Aksi percakapan yang sedang dibuka: ganti nama dan salin isi. */
async function salinPercakapan() {
  const teks = keadaan.pesan.map((p) => `${p.peran === "aku" ? "Kamu" : "AstroZ"}: ${p.teks || ""}`).join("\n\n");
  if (!teks.trim()) { pesanSingkat("Percakapan ini masih kosong."); return; }
  try {
    await navigator.clipboard.writeText(teks);
    pesanSingkat("Percakapan disalin ke papan klip.");
  } catch {
    // peramban bisa menolak papan klip; sediakan jalan lain
    const ta = document.createElement("textarea");
    ta.value = teks;
    document.body.appendChild(ta);
    ta.select();
    try { document.execCommand("copy"); pesanSingkat("Percakapan disalin."); }
    catch { pesanSingkat("Papan klip tidak bisa dipakai di peramban ini.", true); }
    ta.remove();
  }
}

el("simpan-nama").addEventListener("click", async () => {
  const nama = el("nama-baru").value.trim();
  if (!nama) { pesanSingkat("Isi dulu namanya."); return; }
  if (!keadaan.sesi) { pesanSingkat("Belum ada percakapan yang dibuka.", true); return; }
  try {
    await kirim(`/api/sessions/${keadaan.sesi}`, { title: nama }, "POST");
    keadaan.judul = nama;
    el("nama-baru").value = "";
    tutupSemuaLembar();
    await muatSesi();
    pesanSingkat("Nama percakapan disimpan.");
  } catch (e) {
    pesanSingkat("Gagal menyimpan nama: " + e.message, true);
  }
});

/* --------------------------------------------------------------- percakapan */

function tampilkanKosong(ya) {
  el("kosong").hidden = !ya;
  el("alur").style.visibility = ya ? "hidden" : "visible";
}

function gambarSemuaPesan() {
  const wadah = kolom();
  wadah.replaceChildren();
  for (const p of keadaan.pesan) wadah.appendChild(gambarPesan(p));
  keDasar();
}

function gambarPesan(p) {
  const baris = buat("article", `pesan ${p.peran} ${p.status || ""}`);
  baris.dataset.no = p.no || "";
  baris.appendChild(buat("div", "dari", p.peran === "aku" ? "Kamu" : "AstroZ"));

  if (p.lampiran) baris.appendChild(buat("div", "lampiran", "lampiran: " + String(p.lampiran).split("/").pop()));

  const isi = buat("div", "isi-pesan", p.teks || (p.status === "jalan" ? "sedang dikerjakan" : ""));
  if (p.status === "jalan" && p.peran === "astroz") isi.classList.add("shimmer");
  baris.appendChild(isi);

  const aksi = buat("div", "baris-aksi-pesan");
  if (p.peran === "astroz") {
    if (p.status) {
      const cap = buat("span", "cap " + p.status,
        p.status === "jalan" ? "sedang jalan" : p.status === "gagal" ? "gagal" : p.status === "selesai" ? "selesai" : "jawaban");
      aksi.appendChild(cap);
    }
    if (p.pekerja) aksi.appendChild(buat("span", "waktu", p.pekerja));
    if (p.tes === true) aksi.appendChild(buat("span", "waktu", "tes lulus"));
    if (p.tes === false) aksi.appendChild(buat("span", "waktu", "tes gagal"));
    if (p.ts) aksi.appendChild(buat("span", "waktu", waktu(p.ts)));
    if (p.tugas) {
      // Progres kerja tidak ditulis di chat: satu tombol yang membuka panel
      // samping, supaya percakapan tetap bersih dan tidak menumpuk.
      const b = buat("button", "aksi-ikon", "▤");
      b.type = "button";
      b.title = "Lihat proses kerja";
      b.setAttribute("aria-label", "Lihat proses kerja");
      b.addEventListener("click", () => { tampilkanKerja(p.tugas); });
      aksi.appendChild(b);
    }
  } else if (p.ts) {
    aksi.appendChild(buat("span", "waktu", waktu(p.ts)));
  }
  baris.appendChild(aksi);
  return baris;
}

/* Baris kecil di bawah jawaban: apa yang dikerjakan tim, diambil dari catatan
   kejadian yang sudah ada. Ini yang membuat percakapan tidak perlu panel
   aktivitas terpisah untuk hal-hal pokok. */
function potongKata(teks, batas) {
  const t = (teks || "").replace(/\s+/g, " ").trim();
  if (t.length <= batas) return t;
  const potong = t.slice(0, batas);
  const spasi = potong.lastIndexOf(" ");
  return (spasi > batas * 0.6 ? potong.slice(0, spasi) : potong) + "…";
}

function keDasar() {
  const a = el("alur");
  const dekat = a.scrollHeight - a.scrollTop - a.clientHeight < 140;
  if (dekat || !a._pernah) a.scrollTop = a.scrollHeight;
  a._pernah = true;
}

function tambahPesan(p) {
  keadaan.pesan.push(p);
  kolom().appendChild(gambarPesan(p));
  tampilkanKosong(false);
  keDasar();
  return p;
}

function kosongkanChat(pesanKosong) {
  keadaan.pesan = [];
  kolom().replaceChildren();
  tampilkanKosong(!pesanKosong);
  if (pesanKosong) {
    el("sapaan-kecil").textContent = pesanKosong;
  }
}

function sesiBaru() {
  keadaan.sesi = null;
  keadaan.judul = "AstroZ";
  el("judul-bar").textContent = "AstroZ";
  kerjaTugas = null;
  kosongkanChat(null);
  el("sapaan").textContent = sapaanWaktu();
  el("sapaan-kecil").textContent = "Siap mengerjakan. Tulis perintah di kotak bawah.";
  el("judul-kerja").textContent = "Pekerjaan";
  el("catatan-kerja").textContent = "Belum ada pekerjaan di percakapan ini.";
  el("daftar-proses").replaceChildren();
  el("isi-kerja").replaceChildren();
  tutupSemuaLembar();
  el("tulis").focus();
  muatSesi();
}
el("sesi-baru").addEventListener("click", sesiBaru);

function gambarDaftarSesi(daftar) {
  const wadah = el("daftar-sesi");
  wadah.replaceChildren();
  if (!daftar.length) {
    wadah.appendChild(buat("p", "kosong", "Belum ada percakapan."));
    return;
  }
  for (const s of daftar) {
    const baris = buat("div", "baris-sesi");
    const b = buat("button");
    b.type = "button";
    if (s.id === keadaan.sesi) b.setAttribute("aria-current", "true");
    // Hanya judul percakapan. Cuplikan jawaban tidak ditampilkan supaya daftar
    // tetap ringkas dan mudah dipindai.
    b.appendChild(buat("div", "judul", s.title || "Percakapan baru"));
    b.appendChild(buat("div", "waktu", `${tanggalPendek(s.updated || s.created)}  ${(s.tasks || []).length} tugas`));
    b.addEventListener("click", () => { bukaSesi(s.id); tutupSemuaLembar(); });
    const hapus = buat("button", "hapus", "hapus");
    hapus.type = "button";
    hapus.setAttribute("aria-label", "hapus percakapan " + (s.title || ""));
    hapus.addEventListener("click", async (ev) => {
      ev.stopPropagation();
      if (!confirm("Hapus percakapan ini dari daftar? Tugas dan berkasnya tetap ada.")) return;
      await minta(`/api/sessions/${s.id}`, { method: "DELETE" });
      if (s.id === keadaan.sesi) sesiBaru();
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
    keadaan.judul = s.title || "AstroZ";
    // Judul bar selalu nama aplikasi. Judul percakapan ada di riwayat, jadi
    // chat tidak pernah berganti nama sendiri.
    el("judul-bar").textContent = "AstroZ";
    keadaan.aktivitas = d.activity || {};
    keadaan.pesan = [];
    kolom().replaceChildren();
    const pesan = d.messages || [];
    if (!pesan.length) kosongkanChat("Percakapan ini masih kosong.");
    else {
      tampilkanKosong(false);
      for (const m of pesan) {
        tambahPesan({
          peran: m.role === "user" ? "aku" : "astroz",
          teks: m.text,
          ts: m.ts,
          tugas: m.task,
          status: m.role === "user" ? "" : (m.status === "done" ? "selesai" : m.status === "failed" || m.status === "error" ? "gagal" : m.status === "running" ? "jalan" : ""),
          tes: m.tests,
          pekerja: (m.workers || [])[0],
        });
      }
    }
    const jalan = pesan.filter((m) => m.role !== "user" && m.status === "running").map((m) => m.task);
    keadaan.tugasJalan = jalan.length ? jalan[jalan.length - 1] : null;
    // Panel kerja menampilkan tugas terakhir di percakapan ini.
    const semua = s.tasks || [];
    kerjaTugas = keadaan.tugasJalan || (semua.length ? semua[semua.length - 1] : null);
    gambarKerja();
    if (keadaan.tugasJalan) pantauTugas(keadaan.tugasJalan);
  } catch (e) {
    pesanSingkat("Percakapan tidak bisa dibuka: " + e.message, true);
  }
  await muatSesi();
}

/* --------------------------------------------------------------- kirim tugas */

async function unggah(berkas) {
  const buf = await berkas.arrayBuffer();
  let biner = "";
  const bytes = new Uint8Array(buf);
  for (let i = 0; i < bytes.length; i += 8192) biner += String.fromCharCode.apply(null, bytes.subarray(i, i + 8192));
  return kirim("/api/upload", { name: berkas.name, data: btoa(biner) });
}

function pasangLampiran(nama, path) {
  keadaan.lampiran = path;
  const wadah = el("lampiran");
  wadah.replaceChildren();
  wadah.hidden = false;
  wadah.appendChild(buat("span", "lampiran", nama));
  const batal = buat("button", "tombol kecil diam", "batalkan");
  batal.type = "button";
  batal.addEventListener("click", () => { keadaan.lampiran = null; wadah.hidden = true; wadah.replaceChildren(); });
  wadah.appendChild(batal);
}

el("berkas-gambar").addEventListener("change", async (ev) => {
  const berkas = ev.target.files && ev.target.files[0];
  ev.target.value = "";
  if (!berkas) return;
  if (berkas.size > 12 * 1024 * 1024) { pesanSingkat("Gambar lebih dari 12 MB, perkecil dulu.", true); return; }
  try {
    const d = await unggah(berkas);
    pasangLampiran("gambar siap dikirim: " + berkas.name, d.path);
    tutupSemuaLembar();
    pesanSingkat("Gambar disimpan. Pekerja bisa membacanya.");
  } catch (e) {
    pesanSingkat("Gambar gagal disimpan: " + e.message, true);
  }
});

el("berkas-apa").addEventListener("change", async (ev) => {
  const berkas = ev.target.files && ev.target.files[0];
  ev.target.value = "";
  if (!berkas) return;
  if (berkas.size > 12 * 1024 * 1024) { pesanSingkat("Berkas lebih dari 12 MB, perkecil dulu.", true); return; }
  try {
    const d = await unggah(berkas);
    pasangLampiran("berkas siap dikirim: " + berkas.name, d.path);
    tutupSemuaLembar();
    pesanSingkat("Berkas disimpan di folder kerja.");
  } catch (e) {
    pesanSingkat("Berkas gagal disimpan: " + e.message, true);
  }
});

function tumbuh() {
  const t = el("tulis");
  t.style.height = "auto";
  t.style.height = Math.min(200, t.scrollHeight) + "px";
}
el("tulis").addEventListener("input", tumbuh);

el("form-tulis").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const kotak = el("tulis");
  const teks = kotak.value.trim();
  if (!teks) { pesanSingkat("Tulis dulu isi pesannya."); kotak.focus(); return; }
  const lampiran = keadaan.lampiran;
  let penuh = teks;
  if (lampiran) penuh += `\n\nBerkas terlampir: ${lampiran}\nBaca dulu berkas itu sebelum menjawab.`;

  el("kirim").disabled = true;
  const pesanAku = tambahPesan({ peran: "aku", teks, ts: Date.now() / 1000, lampiran });
  kotak.value = "";
  tumbuh();
  keadaan.lampiran = null;
  el("lampiran").hidden = true;
  el("lampiran").replaceChildren();

  try {
    const d = await kirim("/api/chat", {
      text: penuh,
      session: keadaan.sesi,
      baru: !keadaan.sesi,
      workflow: el("ukuran").value,
    });
    keadaan.sesi = d.session;
    keadaan.judul = d.title || keadaan.judul;
    pesanAku.tugas = d.task_id;
    const p = tambahPesan({ peran: "astroz", teks: "sedang dikerjakan", ts: Date.now() / 1000, status: "jalan", tugas: d.task_id });
    keadaan.tugasJalan = d.task_id;
    kerjaTugas = d.task_id;
    gambarKerja();
    pantauTugas(d.task_id);
    muatSesi();
  } catch (err) {
    tambahPesan({ peran: "astroz", teks: "Pesan tidak terkirim: " + err.message, status: "gagal", ts: Date.now() / 1000 });
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

/* ------------------------------------------------------------------ kerja */

/* Progres kerja tampil di panel latar belakang (kolom kanan di layar lebar,
   lembar geser di layar sempit), bukan di dalam chat. Chat hanya memuat pesan
   dan jawaban; kalau kerjanya panjang, angkanya yang berjalan, bukan
   percakapannya yang menumpuk. */
let kerjaTugas = null;
let jamKerja = null;

function pindahTab(panel) {
  for (const b of document.querySelectorAll("#tab-alat [role=tab]")) {
    b.setAttribute("aria-selected", String(b.dataset.panel === panel));
  }
  for (const p of document.querySelectorAll("#aktivitas .panel")) {
    p.hidden = p.id !== "panel-" + panel;
  }
}

function tampilkanKerja(tid) {
  kerjaTugas = tid;
  pindahTab("proses");
  if (!layar.aktivitas.matches) {
    // layar sempit: panelnya hidup di dalam lembar alat
    pindahAlat("kerja");
    bukaLembar("lembar-alat");
  } else {
    const panel = el("aktivitas");
    panel.classList.add("sorot");
    setTimeout(() => panel.classList.remove("sorot"), 900);
  }
  gambarKerja();
  if (jamKerja) clearInterval(jamKerja);
  jamKerja = setInterval(gambarKerja, 2500);
}

async function gambarKerja() {
  const wadah = el("isi-kerja");
  const daftar = el("daftar-proses");
  if (!wadah) return;
  if (!kerjaTugas) {
    daftar.replaceChildren();
    wadah.replaceChildren();
    el("judul-kerja").textContent = "Pekerjaan";
    el("catatan-kerja").textContent = "Belum ada pekerjaan di percakapan ini.";
    return;
  }
  try {
    const d = await ambil(`/api/tasks/${kerjaTugas}`);
    const t = d.task || {};
    const ringan = (t.size || "") === "chat";
    el("judul-kerja").textContent = ringan ? "Dijawab langsung" : "Pekerjaan " + kerjaTugas;
    el("catatan-kerja").textContent = ringan
      ? "Pesan ini dijawab langsung oleh model, tanpa pekerja dan tanpa folder kerja."
      : "Keadaan: " + (t.status || "?") + (t.workers && t.workers.length ? "  |  pekerja: " + t.workers.join(", ") : "");
    daftar.replaceChildren();

    const evs = (d.events || []).filter((e) => ["plan", "worker", "test", "review", "task", "git"].includes(e.kind));
    const jalan = t.status === "running";
    const kotak = buat("div", "kotak-kerja");
    kotak.appendChild(buat("div", "nama", "keadaan: " + (t.status || "?")));
    kotak.appendChild(buat("div", "baris-kecil",
      "ukuran: " + (t.size || "otomatis") + "  |  model: " + (t.model || "bawaan")));
    if (t.workers && t.workers.length) kotak.appendChild(buat("div", "baris-kecil", "pekerja: " + t.workers.join(", ")));
    daftar.appendChild(kotak);

    const berkas = await ambil(`/api/tasks/${kerjaTugas}/berkas`).catch(() => null);
    if (berkas && berkas.jumlah) {
      const bk = buat("div", "kotak-kerja");
      bk.appendChild(buat("div", "nama", berkas.jumlah + " berkas berubah"));
      for (const f of berkas.berkas.slice(0, 12)) {
        bk.appendChild(buat("div", "baris-kecil", f.path + "  " + f.size + " b"));
      }
      daftar.appendChild(bk);
    }

    wadah.replaceChildren();
    if (!evs.length) {
      wadah.appendChild(buat("p", "kosong", jalan ? "Menunggu langkah pertama." : "Tidak ada catatan langkah."));
    }
    for (const e of evs.slice(-60)) {
      const baris = buat("div", "kejadian");
      baris.dataset.jenis = e.kind || "";
      baris.appendChild(buat("div", "waktu", waktu(e.ts)));
      const tengah = buat("div");
      tengah.appendChild(buat("div", "jenis", e.kind || ""));
      tengah.appendChild(buat("div", "pesan-log", e.text || e.message || ""));
      baris.appendChild(tengah);
      wadah.appendChild(baris);
    }
    if (!jalan && jamKerja) { clearInterval(jamKerja); jamKerja = null; }
  } catch {
    /* panel samping bukan jalur penting; biarkan tampilan terakhir */
  }
}

/* ------------------------------------------------------------------ pantau */

let jamPantau = null;
function ticker(aktif) {
  const t = el("ticker");
  if (t) t.classList.toggle("aktif", !!aktif);
}

async function pantauTugas(tid) {
  clearInterval(jamPantau);
  let lewat = 0;
  ticker(true);
  jamPantau = setInterval(async () => {
    lewat += 3;
    try {
      const d = await ambil(`/api/tasks/${tid}`);
      const t = d.task || {};
      keadaan.aktivitas = keadaan.aktivitas || {};
      keadaan.aktivitas[tid] = d.events || [];
      const p = keadaan.pesan.find((x) => x.tugas === tid && x.peran === "astroz");
      const status = t.status === "done" ? "selesai" : t.status === "failed" || t.status === "error" ? "gagal" : "jalan";
      const jawab = t.answer || "";
      if (p && (p.status !== status || (jawab && p.teks !== jawab))) {
        p.status = status;
        p.teks = jawab || p.teks;
        p.ts = t.finished || p.ts;
        p.tes = (t.test || {}).ok;
        p.pekerja = (t.workers || [])[0];
        gambarSemuaPesan();
      }
      if (kerjaTugas === tid) gambarKerja();
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

async function bukaSesiRingan(id) {
  try {
    const d = await ambil(`/api/sessions/${id}`);
    keadaan.aktivitas = d.activity || {};
    if (kerjaTugas) gambarKerja();
  } catch {}
  muatSesi();
}

/* ---------------------------------------------------- panel: kerja dulu */

/* --------------------------------------------------------- panel: model */

function tandaCap(ada, teks) {
  return buat("span", "tanda-cap " + (ada ? "ada" : "tidak"), teks);
}

function barisModel(m, saatKlik) {
  const baris = buat("div", "baris-data");
  const atas = buat("div", "atas");
  atas.appendChild(buat("span", "nama", m.id));
  if (m.id === keadaan.modelSekarang) atas.appendChild(buat("span", "tanda-cap ada", "dipakai"));
  baris.appendChild(atas);
  const deret = buat("div", "baris-aksi-pesan");
  deret.appendChild(tandaCap(!!(m.caps || {}).vision, "gambar"));
  deret.appendChild(tandaCap(!!(m.caps || {}).search, "cari"));
  const sehat = (m.health || {}).ok;
  deret.appendChild(buat("span", "waktu", sehat === true ? "sudah diuji hidup" : sehat === false ? "tidak menjawab" : "belum diuji"));
  if (m.provider) deret.appendChild(buat("span", "waktu", m.provider));
  baris.appendChild(deret);
  const b = buat("button", "tombol kecil garis", m.id === keadaan.modelSekarang ? "sedang dipakai" : "pakai model ini");
  b.type = "button";
  b.disabled = m.id === keadaan.modelSekarang;
  b.addEventListener("click", () => saatKlik(m.id));
  baris.appendChild(b);
  return baris;
}

async function pakaiModel(id) {
  el("catatan-model").textContent = "menerapkan " + id + " ...";
  try {
    await kirim("/api/gateway/model", { model: id, apply_workers: true });
    el("catatan-model").textContent = id + " dipakai di Hermes dan keempat pekerja.";
    pesanSingkat(id + " sekarang dipakai.");
    await muatModel();
    await muatModelLembar();
    await muatPekerja();
  } catch (e) {
    el("catatan-model").textContent = "gagal: " + e.message;
    pesanSingkat("Gagal memakai model: " + e.message, true);
  }
}

function gambarDaftarModel(wadah, d) {
  wadah.replaceChildren();
  const daftar = d.models || [];
  if (!daftar.length) {
    wadah.appendChild(buat("p", "kosong", "Tidak ada model yang cocok. Coba muat dari gateway atau ubah kata kunci."));
    return;
  }
  wadah.appendChild(buat("p", "catatan", `${d.total} model cocok, ${daftar.length} ditampilkan.`));
  for (const m of daftar) wadah.appendChild(barisModel(m, pakaiModel));
}

async function muatModel() {
  const p = new URLSearchParams({ limit: "120", callable_only: "1" });
  if (keadaan.modelTersaring.q) p.set("q", keadaan.modelTersaring.q);
  if (keadaan.modelTersaring.hanyaHidup) p.set("only_healthy", "1");
  try {
    const d = await ambil("/api/gateway/models?" + p.toString());
    gambarDaftarModel(el("daftar-model"), d);
    gambarProvider(d.providers);
    keadaan.modelSekarang = d.current || "";
    el("pil-model-teks").textContent = namaPendek(d.current) || "pilih model";
    el("model-kini-lembar").textContent = d.current || "belum dipilih";
    el("model-sekarang").textContent = d.current || "belum dipilih";
    el("cip-model").textContent = namaPendek(d.current) || "AstroZ";
    const gw = await ambil("/api/state");
    const caps = ((gw.gateway || {}).model_meta || {})[d.current] || {};
    const c = caps.caps || {};
    el("model-sekarang").textContent = `${d.current || "belum dipilih"}  |  ${c.vision ? "bisa melihat gambar" : "tidak bisa melihat gambar"}  |  ${c.search ? "bisa mencari sendiri" : "tidak mencari sendiri"}`;
  } catch (e) {
    el("daftar-model").replaceChildren(buat("p", "kosong", "Daftar model tidak bisa dimuat: " + e.message));
  }
}

/* Nama pendek untuk pil: buang bagian penyedia supaya kotaknya tetap kecil. */
function namaPendek(id) {
  if (!id) return "";
  const ekor = String(id).split("/").pop() || id;
  return ekor.length > 26 ? ekor.slice(0, 25) + "…" : ekor;
}

async function muatModelLembar() {
  const p = new URLSearchParams({ limit: "60", callable_only: "1" });
  if (keadaan.modelLembar.q) p.set("q", keadaan.modelLembar.q);
  if (keadaan.modelLembar.hanyaHidup) p.set("only_healthy", "1");
  try {
    const d = await ambil("/api/gateway/models?" + p.toString());
    gambarDaftarModel(el("daftar-model-2"), d);
    el("model-kini-lembar").textContent = "sekarang: " + (d.current || "belum dipilih");
  } catch (e) {
    el("daftar-model-2").replaceChildren(buat("p", "kosong", "Daftar model tidak bisa dimuat: " + e.message));
  }
}

el("cari-model").addEventListener("input", (ev) => {
  keadaan.modelTersaring.q = ev.target.value.trim();
  clearTimeout(el("cari-model")._jam);
  el("cari-model")._jam = setTimeout(muatModel, 300);
});
el("hanya-hidup").addEventListener("change", (ev) => { keadaan.modelTersaring.hanyaHidup = ev.target.checked; muatModel(); });
el("cari-model-2").addEventListener("input", (ev) => {
  keadaan.modelLembar.q = ev.target.value.trim();
  clearTimeout(el("cari-model-2")._jam);
  el("cari-model-2")._jam = setTimeout(muatModelLembar, 300);
});
el("hanya-hidup-2").addEventListener("change", (ev) => { keadaan.modelLembar.hanyaHidup = ev.target.checked; muatModelLembar(); });
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

function gambarProvider(providers) {
  const wadah = el("daftar-provider");
  wadah.replaceChildren();
  const semua = buat("button", "tombol kecil" + (keadaan.modelTersaring.provider ? " garis" : ""), "semua");
  semua.type = "button";
  semua.addEventListener("click", () => { keadaan.modelTersaring.provider = ""; muatModel(); });
  wadah.appendChild(semua);
  for (const p of providers || []) {
    const b = buat("button", "tombol kecil" + (keadaan.modelTersaring.provider === p.id ? "" : " garis"), `${p.id} ${p.count}`);
    b.type = "button";
    b.addEventListener("click", () => { keadaan.modelTersaring.provider = p.id; muatModel(); });
    wadah.appendChild(b);
  }
}

/* -------------------------------------------------------- panel: pekerja */

function gambarPekerja(daftar) {
  const wadah = el("daftar-pekerja");
  wadah.replaceChildren();
  keadaan.pekerja = daftar;
  for (const w of daftar) {
    const baris = buat("div", "baris-data");
    const atas = buat("div", "atas");
    atas.appendChild(buat("span", "nama", w.label || w.name));
    atas.appendChild(buat("span", "tanda-cap " + (w.installed ? "ada" : ""), w.installed ? "siap" : "tidak ada"));
    baris.appendChild(atas);
    baris.appendChild(buat("div", "teks-kecil", w.version || w.error || "versi belum diperiksa"));
    if (w.model) baris.appendChild(buat("div", "teks-kecil", "model: " + w.model));
    const deret = buat("div", "baris-aksi-pesan");
    const label = buat("label", "teks-kecil");
    label.style.display = "flex"; label.style.gap = "8px"; label.style.alignItems = "center";
    const cek = document.createElement("input");
    cek.type = "checkbox";
    cek.checked = w.enabled !== false;
    cek.addEventListener("change", async () => {
      await kirim(`/api/workers/${w.key}`, { enabled: cek.checked });
      pesanSingkat(`${w.label || w.key} ${cek.checked ? "dipakai" : "dimatikan"}.`);
    });
    label.append(cek, document.createTextNode("pakai pekerja ini"));
    deret.appendChild(label);
    const b = buat("button", "tombol kecil garis", "periksa");
    b.type = "button";
    b.addEventListener("click", async () => {
      b.textContent = "memeriksa";
      try { const d = await kirim(`/api/workers/${w.key}/probe`, {}); pesanSingkat(`${w.label || w.key}: ${d.version || d.error || "selesai"}`); }
      catch (e) { pesanSingkat(`${w.key}: ${e.message}`, true); }
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
    // /api/workers memisahkan status (versi, terpasang) dari setelan
    // (model, dipakai). Tanpa digabung, baris model tidak pernah muncul dan
    // centang "pakai pekerja ini" selalu terlihat aktif walau dimatikan.
    const cfg = d.cfg || {};
    const daftar = (d.workers || []).map((w) => ({
      ...w,
      model: (cfg[w.key] || {}).model || "",
      enabled: (cfg[w.key] || {}).enabled !== false,
    }));
    gambarPekerja(daftar);
  } catch (e) {
    el("daftar-pekerja").replaceChildren(buat("p", "kosong", "Daftar pekerja tidak bisa dimuat: " + e.message));
  }
}

el("periksa-pekerja").addEventListener("click", async () => {
  el("periksa-pekerja").disabled = true;
  for (const w of keadaan.pekerja) {
    try { await kirim(`/api/workers/${w.key}/probe`, {}); } catch {}
  }
  await muatPekerja();
  el("periksa-pekerja").disabled = false;
  pesanSingkat("Pemeriksaan pekerja selesai.");
});

el("terapkan-pekerja").addEventListener("click", async () => {
  try { await kirim("/api/apply", { model: keadaan.modelSekarang }); pesanSingkat("Model diterapkan ke pekerja."); await muatPekerja(); }
  catch (e) { pesanSingkat("Gagal menerapkan model: " + e.message, true); }
});

/* ---------------------------------------------------- panel: pekerja baru */

/* Daftar pekerja: mana yang terpasang, dan tombol pasang untuk yang belum.
   Tujuannya satu clone bisa langsung jalan tanpa terminal. */
async function muatPekerjaPasang() {
  const wadah = el("daftar-pasang");
  if (!wadah) return;
  try {
    const d = await ambil("/api/workers/paket");
    wadah.replaceChildren();
    if (!d.npm) {
      wadah.appendChild(buat("p", "catatan", "npm tidak ada di PATH. Pasang Node.js 20 atau lebih baru dulu, lalu muat ulang halaman ini."));
    }
    // Kemajuan pemasangan tampil di sini, tepat di bawah tombolnya.
    const catatan = buat("pre", "isi-berkas");
    catatan.id = "log-pasang";
    catatan.textContent = "Belum ada pemasangan.";
    for (const p of d.pekerja || []) {
      const baris = buat("div", "baris-data");
      const atas = buat("div", "atas");
      atas.appendChild(buat("span", "nama", p.label));
      atas.appendChild(buat("span", "tanda-cap " + (p.installed ? "ada" : ""), p.installed ? "terpasang" : "belum ada"));
      baris.appendChild(atas);
      baris.appendChild(buat("div", "teks-kecil", p.paket));
      if (p.version) baris.appendChild(buat("div", "teks-kecil", p.version));
      if (p.sumber) {
        const a = buat("a", "teks-kecil", p.sumber);
        a.href = p.sumber;
        a.target = "_blank";
        a.rel = "noreferrer";
        baris.appendChild(a);
      }
      if (!p.installed && d.npm) {
        // Hanya yang belum terpasang yang bisa dipasang. Pemasangan ulang tidak
        // disediakan dari sini: `npm install -g` untuk paket besar bisa
        // menggantung lama, dan satu klik yang berjalan berjam-jam lebih buruk
        // daripada tidak ada tombolnya.
        const b = buat("button", "tombol kecil", "Pasang sekarang");
        b.type = "button";
        b.addEventListener("click", async () => {
          b.disabled = true;
          b.textContent = "memasang";
          catatan.textContent = "memasang " + p.paket + ", perlu beberapa menit";
          try {
            const r = await kirim(`/api/workers/${p.key}/pasang`, {});
            await pantauJob(r.job, "log-pasang");
            await muatPekerjaPasang();
            await muatPekerja();
          } catch (e) {
            pesanSingkat("Gagal memasang: " + e.message, true);
          } finally {
            b.disabled = false;
            b.textContent = "Pasang sekarang";
          }
        });
        baris.appendChild(b);
      }
      wadah.appendChild(baris);
    }
    wadah.appendChild(catatan);
  } catch (e) {
    wadah.replaceChildren(buat("p", "kosong", "Daftar pekerja tidak bisa dimuat: " + e.message));
  }
}

/* -------------------------------------------------------- panel: berkas */

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

function tambahCatatan(e, wadahId = "isi-catatan") {
  const wadah = el(wadahId);
  if (!wadah) return;
  const baris = buat("div", "kejadian");
  baris.dataset.jenis = e.kind || "";
  baris.appendChild(buat("div", "waktu", waktu(e.ts)));
  const tengah = buat("div");
  tengah.appendChild(buat("div", "jenis", e.kind || ""));
  tengah.appendChild(buat("div", "pesan-log", e.text || e.message || ""));
  baris.appendChild(tengah);
  wadah.prepend(baris);
  while (wadah.children.length > 300) wadah.lastChild.remove();
}

async function muatCatatan(ulang) {
  if (ulang) { el("isi-catatan").replaceChildren(); }
  try {
    const d = await ambil("/api/events/recent?limit=200");
    const daftar = (d.events || []).slice().reverse();
    for (const e of daftar) tambahCatatan(e);
  } catch {}
}

el("saring-catatan").addEventListener("change", () => muatCatatan(true));
el("bersihkan-catatan").addEventListener("click", () => muatCatatan(true));

/* --------------------------------------------------- panel: plugin MCP */

function gambarMcp(servers, siap) {
  const wadah = el("daftar-mcp");
  wadah.replaceChildren();
  if (!servers.length) wadah.appendChild(buat("p", "kosong", "Belum ada plugin. Pasang dari daftar di bawah atau dari perintah sendiri."));
  for (const s of servers) {
    const baris = buat("div", "baris-data");
    const atas = buat("div", "atas");
    atas.appendChild(buat("span", "nama", s.nama));
    atas.appendChild(buat("span", "tanda-cap ada", s.transport));
    baris.appendChild(atas);
    baris.appendChild(buat("div", "teks-kecil", s.detail || ""));
    baris.appendChild(buat("div", "teks-kecil", "terpasang di: " + (s.pekerja || []).join(", ")));
    const b = buat("button", "tombol kecil garis", "lepas");
    b.type = "button";
    b.addEventListener("click", async () => {
      b.disabled = true;
      try { await kirim(`/api/mcp/${encodeURIComponent(s.nama)}`, {}, "DELETE"); pesanSingkat(s.nama + " dilepas."); await muatMcp(); }
      catch (e) { pesanSingkat("Gagal melepas: " + e.message, true); }
      finally { b.disabled = false; }
    });
    baris.appendChild(b);
    wadah.appendChild(baris);
  }
  const wadah2 = el("daftar-mcp-siap");
  wadah2.replaceChildren();
  for (const s of siap || []) {
    const baris = buat("div", "baris-data");
    const atas = buat("div", "atas");
    atas.appendChild(buat("span", "nama", s.nama));
    atas.appendChild(buat("span", "tanda-cap tidak", "siap"));
    baris.appendChild(atas);
    baris.appendChild(buat("div", "teks-kecil", s.keterangan || ""));
    const b = buat("button", "tombol kecil", "pasang ke semua pekerja");
    b.type = "button";
    b.addEventListener("click", async () => {
      b.disabled = true;
      b.textContent = "memasang";
      try {
        const d = await kirim("/api/mcp", s);
        pesanSingkat("Memasang " + s.nama + " ...");
        await pantauJob(d.job);
        await muatMcp();
      } catch (e) { pesanSingkat("Gagal memasang: " + e.message, true); }
      finally { b.disabled = false; b.textContent = "pasang ke semua pekerja"; }
    });
    baris.appendChild(b);
    wadah2.appendChild(baris);
  }
}

async function muatMcp() {
  try {
    const d = await ambil("/api/mcp");
    gambarMcp(d.servers || [], d.siap || []);
  } catch (e) {
    el("daftar-mcp").replaceChildren(buat("p", "kosong", "Daftar plugin tidak bisa dimuat: " + e.message));
  }
}

el("muat-mcp").addEventListener("click", muatMcp);
el("pasang-plugin").addEventListener("click", async () => {
  const nama = el("mcp-nama").value.trim();
  const target = el("mcp-target").value.trim();
  if (!nama || !target) { pesanSingkat("Nama dan perintahnya harus diisi.", true); return; }
  el("log-plugin").textContent = "memasang " + nama + " ...";
  try {
    const d = await kirim("/api/mcp", {
      nama, target,
      args: el("mcp-args").value.trim(),
      env: el("mcp-env").value.trim(),
    });
    await pantauJob(d.job);
    el("mcp-nama").value = ""; el("mcp-target").value = ""; el("mcp-args").value = ""; el("mcp-env").value = "";
    await muatMcp();
  } catch (e) {
    el("log-plugin").textContent = "gagal: " + e.message;
    pesanSingkat("Gagal memasang plugin: " + e.message, true);
  }
});

/* Job di latar belakang: clone repo atau unduh paket plugin. */
async function pantauJob(jid, ke) {
  if (!jid) return;
  const kotak = ke ? el(ke) : el("log-plugin");
  let terakhir = null;
  for (let i = 0; i < 240; i++) {
    try {
      const d = await ambil(`/api/jobs/${jid}`);
      const j = d.job || {};
      // Baris kemajuan pemasangan ditulis di tempat aksinya berada, bukan di
      // kotak log plugin MCP: mengirimnya ke sana membuat pemasangan pekerja
      // tampak tidak melakukan apa pun.
      if (kotak) { terakhir = j; kotak.textContent = [j.judul, ...(j.baris || []).slice(-6), j.hasil].filter(Boolean).join("\n"); }
      if (j.status !== "jalan") {
        pesanSingkat(j.hasil || (j.status === "selesai" ? "Selesai." : "Gagal."), j.status === "gagal");
        return j;
      }
    } catch {}
    await new Promise((r) => setTimeout(r, 2500));
  }
  // Pemanggilnya memuat ulang daftar, dan itu menghapus kotak log ini. Simpan
  // baris terakhir supaya pemasangan yang panjang tidak berakhir tanpa jejak.
  if (kotak && terakhir) kotak.textContent = [terakhir.judul, ...(terakhir.baris || []).slice(-6)].filter(Boolean).join("\n");
  return terakhir;
}

/* --------------------------------------------------- panel: skill GitHub */

function gambarSkill(paket, siap) {
  const wadah = el("daftar-skill");
  wadah.replaceChildren();
  if (!paket.length) wadah.appendChild(buat("p", "kosong", "Belum ada paket skill yang dipasang."));
  for (const p of paket) {
    const baris = buat("div", "baris-data");
    const atas = buat("div", "atas");
    atas.appendChild(buat("span", "nama", p.nama));
    atas.appendChild(buat("span", "tanda-cap ada", p.jumlah + " skill"));
    baris.appendChild(atas);
    baris.appendChild(buat("div", "teks-kecil", (p.contoh || []).join(", ")));
    baris.appendChild(buat("div", "teks-kecil", p.ukuran + "  " + p.path));
    const b = buat("button", "tombol kecil garis", "lepas");
    b.type = "button";
    b.addEventListener("click", async () => {
      b.disabled = true;
      try { await kirim(`/api/skills/${encodeURIComponent(p.nama)}`, {}, "DELETE"); pesanSingkat(p.nama + " dilepas."); await muatSkill(); }
      catch (e) { pesanSingkat("Gagal melepas: " + e.message, true); }
      finally { b.disabled = false; }
    });
    baris.appendChild(b);
    wadah.appendChild(baris);
  }
  if (siap && siap.length) {
    const baris = buat("div", "baris-data");
    baris.appendChild(buat("div", "nama", "siap dipakai pekerja"));
    baris.appendChild(buat("div", "teks-kecil", siap.join(", ")));
    wadah.appendChild(baris);
  }
}

async function muatSkill() {
  try {
    const d = await ambil("/api/skills");
    gambarSkill(d.paket || [], d.siap || []);
  } catch (e) {
    el("daftar-skill").replaceChildren(buat("p", "kosong", "Daftar skill tidak bisa dimuat: " + e.message));
  }
}

el("pasang-skill").addEventListener("click", async () => {
  const url = el("repo-skill").value.trim();
  if (!url) { pesanSingkat("Isi dulu repo skill-nya.", true); return; }
  el("log-plugin").textContent = "mengkloning " + url + " ...";
  try {
    const d = await kirim("/api/skills", { url });
    pesanSingkat("Mengkloning " + url + " ...");
    await pantauJob(d.job);
    el("repo-skill").value = "";
    await muatSkill();
  } catch (e) {
    pesanSingkat("Gagal memasang skill: " + e.message, true);
  }
});

async function muatMarketplace() {
  const wadah = el("daftar-marketplace");
  try {
    const d = await ambil("/api/marketplace");
    wadah.replaceChildren();
    for (const m of d.daftar || []) {
      const baris = buat("div", "baris-data");
      const atas = buat("div", "atas");
      atas.appendChild(buat("span", "nama", m.nama));
      atas.appendChild(buat("span", "tanda-cap tidak", m.jenis));
      baris.appendChild(atas);
      baris.appendChild(buat("div", "teks-kecil", m.keterangan));
      const b = buat("button", "tombol kecil", "pasang");
      b.type = "button";
      b.addEventListener("click", async () => {
        b.disabled = true;
        try {
          const d2 = await kirim("/api/skills", { url: m.url });
          pesanSingkat("Mengkloning " + m.nama + " ...");
          await pantauJob(d2.job);
          await muatSkill();
        } catch (e) { pesanSingkat("Gagal: " + e.message, true); }
        finally { b.disabled = false; }
      });
      baris.appendChild(b);
      wadah.appendChild(baris);
    }
  } catch (e) {
    wadah.replaceChildren(buat("p", "kosong", "Daftar sumber tidak bisa dimuat: " + e.message));
  }
}

/* ------------------------------------------------------------ alat bantu */

function gambarAlatBantu(gw) {
  const wadah = el("daftar-alat-bantu");
  if (!wadah) return;
  wadah.replaceChildren();
  const alat = [
    ["cari \"kata kunci\"", "mencari di web, hasilnya judul, tautan, dan ringkasan."],
    ["buka <url>", "membuka satu halaman web dan mengembalikan isinya sebagai teks."],
    ["lihat <berkas>", "membaca berkas gambar jadi teks, memakai model " + (gw.vision_model || "yang bisa melihat gambar") + "."],
  ];
  for (const [nama, keterangan] of alat) {
    const baris = buat("div", "baris-data");
    baris.appendChild(buat("div", "nama", nama));
    baris.appendChild(buat("div", "teks-kecil", keterangan));
    wadah.appendChild(baris);
  }
}

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
  await Promise.all([muatSesi(), muatModel(), muatPekerja(), muatBerkas(), muatGit(), muatCatatan(false), muatMcp(), muatSkill(), muatMarketplace(), muatPekerjaPasang()]);
  // Percakapan kosong yang belum pernah dipakai dibuang supaya riwayat tidak
  // penuh baris "Percakapan baru".
  await kirim("/api/sessions/kosong", {}, "DELETE").catch(() => null);
  await muatSesi();
  sambungKejadian();
  const d = await ambil("/api/state").catch(() => null);
  if (d) gambarAlatBantu(d.gateway || {});
  const daftar = await ambil("/api/sessions").catch(() => ({ sessions: [] }));
  const sesi = (daftar.sessions || [])[0];
  if (sesi) bukaSesi(sesi.id);
  else sesiBaru();
}

mulai();
