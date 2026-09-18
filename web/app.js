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
  peran: "user",            // dari /api/saya; menentukan apa yang boleh tampil
  saya: "",
  modelTersaring: { q: "", hanyaHidup: false },
  modelLembar: { q: "", hanyaHidup: false },
  pindah: new Set(),        // id tugas yang sudah dipindah dari aktivitas ke chat
  berkas: [],               // daftar berkas folder kerja, untuk disaring tanpa memuat ulang
};

/* ------------------------------------------------------------------ masuk */

/* Gerbang masuk. Halaman terbuka tanpa token supaya form ini bisa dimuat, dan
   seluruh data baru mengalir setelah /api/masuk menerima tokennya. */
function tampilkanGerbang(tampil) {
  const g = el("gerbang");
  if (!g) return;
  g.hidden = !tampil;
  el("app")?.setAttribute("aria-hidden", tampil ? "true" : "false");
  if (tampil) {
    // Isi halaman disembunyikan, bukan dihapus: setelah masuk, semuanya kembali
    // seperti semula tanpa perlu memuat ulang.
    const app = document.querySelector(".app");
    if (app) app.style.display = "none";
    setTimeout(() => el("token-masuk")?.focus(), 60);
  } else {
    const app = document.querySelector(".app");
    if (app) app.style.display = "";
  }
}

async function kirimToken(token) {
  const d = await minta("/api/masuk", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ token }),
  });
  return d.pengguna || {};
}

function pasangFormMasuk() {
  const f = el("form-masuk");
  if (!f) return;

  // Tab: masuk atau daftar. Yang ditampilkan hanya satu, supaya layar masuk
  // tidak menumpuk dua formulir sekaligus di layar HP.
  function tabmana(nama) {
    const masuk = nama === "masuk";
    el("tab-masuk").setAttribute("aria-selected", String(masuk));
    el("tab-daftar").setAttribute("aria-selected", String(!masuk));
    el("form-masuk").hidden = !masuk;
    el("form-daftar").hidden = masuk;
    el("hasil-daftar").hidden = true;
    setTimeout(() => (masuk ? el("token-masuk") : el("kode-undangan"))?.focus(), 60);
  }
  el("tab-masuk").addEventListener("click", () => tabmana("masuk"));
  el("tab-daftar").addEventListener("click", () => tabmana("daftar"));

  f.addEventListener("submit", async (e) => {
    e.preventDefault();
    const token = el("token-masuk").value.trim();
    const pesan = el("pesan-masuk");
    const tombol = el("tombol-masuk");
    if (!token) { pesan.textContent = "Isi tokennya dulu."; return; }
    tombol.disabled = true;
    tombol.textContent = "memeriksa";
    pesan.textContent = "";
    try {
      const u = await kirimToken(token);
      el("token-masuk").value = "";
      tampilkanGerbang(false);
      keadaan.peran = u.peran || "user";
      keadaan.saya = u.nama || "";
      sembunyikanKhususAdmin();
      await mulai();
    } catch (err) {
      // Token yang salah tidak dibiarkan mengendap di kolom isian.
      el("token-masuk").value = "";
      pesan.textContent = err.message || "tidak bisa masuk";
    } finally {
      tombol.disabled = false;
      tombol.textContent = "Masuk";
    }
  });

  // Daftar dengan kode undangan: akun dan token dibuat server, pendaftar
  // menyalin tokennya sendiri. Admin tidak menyentuh token sama sekali.
  const fd = el("form-daftar");
  if (fd) {
    fd.addEventListener("submit", async (e) => {
      e.preventDefault();
      const pesan = el("pesan-daftar");
      const tombol = el("tombol-daftar");
      const kode = el("kode-undangan").value.trim().toUpperCase();
      const nama = el("nama-daftar").value.trim().toLowerCase();
      if (!kode || !nama) { pesan.textContent = "Isi kode dan namanya."; return; }
      tombol.disabled = true;
      tombol.textContent = "membuat akun";
      pesan.textContent = "";
      try {
        const d = await minta("/api/undangan/pakai", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ kode, nama }),
        });
        const token = (d.akun || {}).token || "";
        el("token-baru").value = token;
        el("form-daftar").hidden = true;
        el("hasil-daftar").hidden = false;
        el("kode-undangan").value = "";
        el("nama-daftar").value = "";
      } catch (err) {
        pesan.textContent = err.message || "tidak bisa mendaftar";
      } finally {
        tombol.disabled = false;
        tombol.textContent = "Buat akun";
      }
    });
  }

  const salin = el("salin-token");
  if (salin) {
    salin.addEventListener("click", async () => {
      const t = el("token-baru").value;
      try {
        await navigator.clipboard.writeText(t);
        pesanSingkat("Token disalin.");
      } catch {
        // Clipboard bisa ditolak peramban; pilih teksnya supaya bisa disalin manual.
        el("token-baru").select();
        pesanSingkat("Tekan lama untuk menyalin tokennya.", true);
      }
    });
  }

  const langsung = el("masuk-sekarang");
  if (langsung) {
    langsung.addEventListener("click", async () => {
      const t = el("token-baru").value;
      langsung.disabled = true;
      try {
        const u = await kirimToken(t);
        tampilkanGerbang(false);
        keadaan.peran = u.peran || "user";
        keadaan.saya = u.nama || "";
        sembunyikanKhususAdmin();
        await mulai();
      } catch (err) {
        el("pesan-daftar").textContent = err.message || "tidak bisa masuk";
        el("hasil-daftar").hidden = true;
        el("form-daftar").hidden = false;
      } finally {
        langsung.disabled = false;
      }
    });
  }
}

/* Menu yang menyangkut mesin pemilik (kunci API, pekerja, setelan) tidak
   ditampilkan ke pengguna biasa: menampilkannya hanya menghasilkan pesan
   "hanya admin" saat ditekan. Pengaturan ada di kaki menu, bukan di daftar nav,
   jadi keduanya harus ditangani. */
function sembunyikanKhususAdmin() {
  const admin = keadaan.peran === "admin";
  const kaki = el("kaki-pengaturan");
  if (kaki) kaki.hidden = !admin;
  const blok = el("blok-admin");
  if (blok) blok.hidden = !admin;
  // Pil model hanya berguna kalau daftar model boleh dibaca.
  const pil = el("pil-model");
  if (pil) pil.hidden = !admin;
  if (keadaan.saya) {
    const j = el("judul-bar");
    if (j) j.textContent = "AstroZ · " + keadaan.saya;
  }
  // Bagian admin dimuat setelah perannya diketahui, bukan saat halaman dibuka.
  if (admin) {
    muatUndangan().catch(() => {});
    muatAkun().catch(() => {});
    muatStorage().catch(() => {});
  }
}

/* ------------------------------------------------------------------ admin */

/* Kelola undangan dan akun. Hanya tampil untuk admin; pengguna biasa tidak
   melihat bloknya sama sekali, dan server tetap menolak kalau dipaksa. */
async function muatUndangan() {
  const wadah = el("daftar-undangan");
  if (!wadah) return;
  try {
    const d = await ambil("/api/undangan");
    wadah.replaceChildren();
    const u = d.undangan || [];
    if (!u.length) {
      wadah.appendChild(buat("p", "kosong", "Belum ada kode undangan yang berlaku."));
      return;
    }
    for (const k of u) {
      const baris = buat("div", "baris-data");
      const atas = buat("div", "atas");
      atas.appendChild(buat("span", "nama", k.kode));
      atas.appendChild(buat("span", "tanda-cap ada", k.peran));
      baris.appendChild(atas);
      const sisa = Math.max(0, Math.round(((k.kedaluwarsa || 0) * 1000 - Date.now()) / 1000));
      const jam = Math.floor(sisa / 3600);
      baris.appendChild(buat("div", "teks-kecil",
        `dipakai ${k.dipakai}/${k.maks} · berlaku ${jam > 0 ? jam + " jam lagi" : Math.floor(sisa / 60) + " menit lagi"}`));
      const b = buat("button", "tombol kecil garis", "batalkan");
      b.type = "button";
      b.addEventListener("click", async () => {
        b.disabled = true;
        try {
          await kirim(`/api/undangan/${encodeURIComponent(k.kode)}`, {}, "DELETE");
          pesanSingkat(`Kode ${k.kode} dibatalkan.`);
          await muatUndangan();
        } catch (e) {
          pesanSingkat("Gagal membatalkan: " + e.message, true);
        } finally {
          b.disabled = false;
        }
      });
      baris.appendChild(b);
      wadah.appendChild(baris);
    }
  } catch (e) {
    wadah.replaceChildren(buat("p", "kosong", "Daftar undangan tidak bisa dimuat: " + e.message));
  }
}

async function muatAkun() {
  const wadah = el("daftar-akun");
  if (!wadah) return;
  try {
    const d = await ambil("/api/akun");
    wadah.replaceChildren();
    for (const a of d.akun || []) {
      const baris = buat("div", "baris-data");
      const atas = buat("div", "atas");
      atas.appendChild(buat("span", "nama", a.nama));
      atas.appendChild(buat("span", "tanda-cap " + (a.peran === "admin" ? "ada" : "tidak"), a.peran));
      if (!a.aktif) atas.appendChild(buat("span", "tanda-cap tidak", "nonaktif"));
      baris.appendChild(atas);
      const deret = buat("div", "baris-aksi-pesan");
      const bt = buat("button", "tombol kecil garis", "token baru");
      bt.type = "button";
      bt.addEventListener("click", async () => {
        bt.disabled = true;
        try {
          const r = await kirim(`/api/akun/${encodeURIComponent(a.nama)}/token`, {});
          // Token baru ditampilkan sekali di sini, lalu bisa disalin.
          baris.querySelector(".token-baru")?.remove();
          const kotak = buat("input", "token-baru");
          kotak.readOnly = true;
          kotak.value = (r.akun || {}).token || "";
          kotak.style.marginTop = "6px";
          baris.appendChild(kotak);
          kotak.select();
          pesanSingkat(`Token baru untuk ${a.nama} ditampilkan. Salin sekarang.`);
        } catch (e) {
          pesanSingkat("Gagal: " + e.message, true);
        } finally {
          bt.disabled = false;
        }
      });
      deret.appendChild(bt);
      baris.appendChild(deret);
      wadah.appendChild(baris);
    }
  } catch (e) {
    wadah.replaceChildren(buat("p", "kosong", "Daftar akun tidak bisa dimuat: " + e.message));
  }
}

function ukuranManusia(n) {
  const b = Number(n) || 0;
  if (b < 1024) return b + " B";
  if (b < 1024 * 1024) return (b / 1024).toFixed(1) + " KB";
  if (b < 1024 * 1024 * 1024) return (b / 1048576).toFixed(2) + " MB";
  return (b / 1073741824).toFixed(2) + " GB";
}

async function muatStorage() {
  const wadah = el("daftar-storage");
  if (!wadah) return;
  try {
    const d = await ambil("/api/storage");
    wadah.replaceChildren();
    const baris = Object.entries(d.pemakaian || {})
      .sort((a, b) => (b[1].total || 0) - (a[1].total || 0));
    if (!baris.length) {
      wadah.appendChild(buat("p", "kosong", "Belum ada penyimpanan pengguna."));
      return;
    }
    for (const [nama, r] of baris) {
      const b = buat("div", "baris-data");
      const atas = buat("div", "atas");
      atas.appendChild(buat("span", "nama", nama));
      atas.appendChild(buat("span", "teks-kecil", ukuranManusia(r.total)));
      b.appendChild(atas);
      // Rincian per bagian: supaya terlihat BAGIAN mana yang besar, bukan cuma
      // jumlahnya. Tanpa ini angka total tidak bisa ditindaklanjuti.
      const rinci = buat("div", "teks-kecil");
      rinci.textContent = `kerja ${ukuranManusia(r.workspace)} · kejadian ${ukuranManusia(r.events)} · tugas ${ukuranManusia(r.tasks)} · percakapan ${ukuranManusia(r.sessions)} · cadangan ${ukuranManusia(r.cadangan)}`;
      b.appendChild(rinci);
      wadah.appendChild(b);
    }
    const total = buat("p", "catatan", `Jumlah semua akun: ${ukuranManusia(d.total)}. Tidak ada batas ukuran; tiap akun menanggung berkasnya sendiri di ${d.akar}.`);
    wadah.appendChild(total);
  } catch (e) {
    wadah.replaceChildren(buat("p", "kosong", "Pemakaian penyimpanan tidak bisa dimuat: " + e.message));
  }
}

function pasangAdmin() {
  const b = el("buat-undangan");
  if (b) {
    b.addEventListener("click", async () => {
      b.disabled = true;
      try {
        const maks = Math.max(1, Math.min(50, Number(el("undangan-maks").value) || 1));
        const d = await kirim("/api/undangan", { peran: "user", maks });
        const kode = (d.undangan || {}).kode || "";
        pesanSingkat(`Kode undangan: ${kode} — kirim ke orangnya.`);
        await muatUndangan();
      } catch (e) {
        pesanSingkat("Gagal membuat kode: " + e.message, true);
      } finally {
        b.disabled = false;
      }
    });
  }
  const m = el("muat-undangan");
  if (m) {
    m.addEventListener("click", async () => {
      await Promise.all([muatUndangan(), muatAkun(), muatStorage()]);
    });
  }
}

pasangAdmin();

/* ------------------------------------------------------------------ bantuan */

async function minta(jalan, opsi) {
  const r = await fetch(jalan, opsi);
  const teks = await r.text();
  let data = {};
  try { data = teks ? JSON.parse(teks) : {}; } catch { data = { teks }; }
  if (r.status === 401) {
    // Sesi habis atau token belum ada: tampilkan layar masuk, bukan pesan galat
    // yang membingungkan di tengah halaman.
    tampilkanGerbang(true);
    throw new Error(data.error || "belum masuk");
  }
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
  // Kelas ini yang menampilkannya. Tanpa itu pesannya tidak punya gaya dan
  // tidak terlihat sama sekali, karena aturan tampilnya menuntut kelas ini.
  kotak.classList.toggle("tampil", Boolean(teks));
  clearTimeout(kotak._jam);
  kotak._jam = setTimeout(() => { kotak.textContent = ""; kotak.classList.remove("tampil"); }, 4200);
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

/* Ikon digambar sendiri sebagai SVG kecil: font sistem tidak menyediakan ikon
   yang seragam, dan huruf pengganti terlihat berbeda-beda di tiap perangkat.
   Satu jalur, warna ikut `currentColor` supaya tema tetap berlaku.

   Tiap lambang dipilih karena artinya, bukan karena bentuknya rapi: gerigi
   untuk pengaturan, peniti untuk sematkan, gambar untuk berkas gambar, file
   untuk berkas lain, medal untuk skill, terminal untuk pekerja. Pengguna yang
   belum tahu aplikasinya tetap bisa menebak dari lambangnya. */
const JALUR_IKON = {
  salin: "M9 9V6a2 2 0 0 1 2-2h7a2 2 0 0 1 2 2v7a2 2 0 0 1-2 2h-3M6 9h7a2 2 0 0 1 2 2v7a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2z",
  ulang: "M20 12a8 8 0 1 1-2.6-5.9M20 4v4.5h-4.5",
  sumber: "M12 3v18M12 3l3.5 3.5M12 3 8.5 6.5M12 21l3.5-3.5M12 21l-3.5-3.5M3 12h18M3 12l3.5-3.5M3 12l3.5 3.5M21 12l-3.5-3.5M21 12l-3.5 3.5",
  chat: "M4 12a8 8 0 0 1 8-8h4a4 4 0 0 1 0 8h-2l-4 4v-4H8a4 4 0 0 1-4-4z",
  bubble: "M20.5 11.6a7.7 7.7 0 0 1-7.7 7.7H8.4L4 22.2v-4.4a7.7 7.7 0 0 1 4.4-14.1h4.4a7.7 7.7 0 0 1 7.7 7.9ZM12 8.4v6M9 11.4h6",
  riwayat: "M12 7.6v4.6l3 1.8M3.6 12a8.4 8.4 0 1 0 2.7-6.1M3 4.4v4.4h4.4",
  pensil: "M4 20v-3.6L14.2 6.2a2.1 2.1 0 0 1 3 3L7.6 19.6H4zM12.6 8.2l3.2 3.2",
  sematkan: "M9.4 3h5.2M12 3v6.2M12 9.2a4 4 0 0 0-4 4h8a4 4 0 0 0-4-4ZM12 13.2V21",
  kerja: "M3 12h3.6l2.4-6 4 12 2.4-6H21",
  kembali: "M15 5l-7 7 7 7",
  gerigi: "M12 15.4a3.4 3.4 0 1 0 0-6.8 3.4 3.4 0 0 0 0 6.8ZM19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-2.9 1.2 2 2 0 1 1-4 0 1.7 1.7 0 0 0-2.9-1.2l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1A1.7 1.7 0 0 0 3 15a2 2 0 1 1 0-4 1.7 1.7 0 0 0 1.5-2.7l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1A1.7 1.7 0 0 0 10 4.3a2 2 0 1 1 4 0 1.7 1.7 0 0 0 2.7 1.2l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1A1.7 1.7 0 0 0 21 11a2 2 0 1 1 0 4Z",
  keluar: "M15 4h3.5A1.5 1.5 0 0 1 20 5.5v13a1.5 1.5 0 0 1-1.5 1.5H15M10.5 8 6.5 12l4 4M6.5 12H15",
  gambar: "M4 5h16a1 1 0 0 1 1 1v12a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1ZM3 16.4l4.6-4.6 4 4 3-3 6 6M9.4 9.6h.01",
  file: "M13 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V9l-6-6m0 0v6h6",
  berkas: "M3 6.5h6.2l1.8 2H21v9.5a1.5 1.5 0 0 1-1.5 1.5h-15A1.5 1.5 0 0 1 3 18V6.5Z",
  plugin: "M9 3v4M15 3v4M7 7h10v4.2a5 5 0 0 1-5 5 5 5 0 0 1-5-5V7ZM12 16.2V21",
  skill: "M12 3a4.6 4.6 0 1 1 0 9.2 4.6 4.6 0 0 1 0-9.2ZM8.4 11.6 6.9 21l5.1-2.6 5.1 2.6-1.5-9.4",
  pekerja: "M3.5 5.5h17v13h-17zM7.2 10l2.6 2.6L7.2 15.2M12.8 15.4h4",
  catatan: "M4 6.5h16M4 12h16M4 17.5h10",
  model: "M8.5 8.5h7v7h-7zM12 3.5V8.5M12 15.5v5M3.5 12h5M15.5 12h5M5.6 5.6 8.5 8.5M15.5 15.5l2.9 2.9M18.4 5.6 15.5 8.5M8.5 15.5l-2.9 2.9",
  terminal: "M4 5.5h16a1.5 1.5 0 0 1 1.5 1.5v10a1.5 1.5 0 0 1-1.5 1.5H4A1.5 1.5 0 0 1 2.5 17V7A1.5 1.5 0 0 1 4 5.5ZM6.5 10l2.5 2.5L6.5 15M11.5 15.2h5",
  "titik-tiga": "M12 6.4h.01M12 12h.01M12 17.6h.01",
  hapus: "M5 7h14M9.5 7V5.2h5V7M7 7l.9 12.1h8.2L17 7M10.4 10.6v5.6M13.6 10.6v5.6",
  lain: "M12 6.4h.01M12 12h.01M12 17.6h.01",
};

function ikon(nama, ukuran = 16) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("width", ukuran);
  svg.setAttribute("height", ukuran);
  svg.setAttribute("fill", "none");
  svg.setAttribute("stroke", "currentColor");
  svg.setAttribute("stroke-width", "1.7");
  svg.setAttribute("stroke-linecap", "round");
  svg.setAttribute("stroke-linejoin", "round");
  svg.setAttribute("aria-hidden", "true");
  const p = document.createElementNS("http://www.w3.org/2000/svg", "path");
  p.setAttribute("d", JALUR_IKON[nama] || JALUR_IKON.lain);
  svg.appendChild(p);
  return svg;
}

/* Lambang di markup: satu tempat menyebut nama lambangnya lewat data-ikon,
   lalu diisi di sini. Tombol dan menu jadi tidak menyimpan jalur SVG panjang
   di HTML, dan lambangnya ikut berubah kalau jalurnya diperbaiki. */
function pasangIkon(akar = document) {
  for (const s of akar.querySelectorAll("[data-ikon]")) {
    const nama = s.dataset.ikon;
    const ukuran = Number(s.dataset.ukuran || 18);
    if (!JALUR_IKON[nama]) continue;
    s.replaceChildren(ikon(nama, ukuran));
  }
}

function tombolAksi(nama, label, saatKlik) {
  const b = buat("button", "aksi-ikon");
  b.type = "button";
  b.title = label;
  b.setAttribute("aria-label", label);
  b.appendChild(ikon(nama));
  if (saatKlik) b.addEventListener("click", saatKlik);
  return b;
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
// Tombol tema ada di halaman Pengaturan, bukan lagi di menu titik tiga.
for (const b of document.querySelectorAll("[data-pilih-tema]")) {
  b.addEventListener("click", () => {
    pakaiTema(b.dataset.pilihTema);
    pesanSingkat(b.dataset.pilihTema === "gelap" ? "Tema gelap dipakai." : "Tema terang dipakai.");
  });
}
el("sapaan").textContent = sapaanWaktu();

/* ------------------------------------------------------------------ lapisan */

function bukaLembar(id) {
  const l = el(id);
  if (!l) return;
  // Halaman satu layar menutup lembar dari atas, jadi lembar yang baru dibuka
  // akan tersembunyi di belakangnya. Tutup dulu halamannya.
  if (el("halaman") && !el("halaman").hidden) tutupHalaman();
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
document.addEventListener("keydown", (e) => {
  if (e.key !== "Escape") return;
  // Urutan tutup: halaman dulu, lalu lembar, lalu menu titik tiga, lalu menu
  // aksi baris riwayat. Halaman menumpuk di atas lembar, jadi menutupnya lebih
  // dulu sesuai yang terlihat.
  if (el("halaman") && !el("halaman").hidden) { tutupHalaman(); return; }
  if (tutupMenuSesi()) return;
  tutupSemuaLembar();
  tutupMenuTitik();
});

/* Menu aksi satu baris riwayat (semat, hapus). Satu yang terbuka pada satu
   waktu: menu yang tertinggal terbuka di baris lain membuat daftar terlihat
   penuh dan pengguna tidak tahu mana yang sedang aktif. */
function tutupMenuSesi() {
  let ada = false;
  for (const m of document.querySelectorAll(".menu-sesi")) {
    if (!m.hidden) ada = true;
    m.hidden = true;
    const a = m.parentElement && m.parentElement.querySelector(".aksi-sesi");
    if (a) a.setAttribute("aria-expanded", "false");
  }
  return ada;
}
document.addEventListener("click", (e) => {
  if (!e.target.closest(".menu-sesi") && !e.target.closest(".aksi-sesi")) tutupMenuSesi();
});

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

el("buka-alat").addEventListener("click", () => { bukaMenu(); });
el("buka-sesi").addEventListener("click", () => { bukaMenu("obrolan"); });
el("tombol-plus").addEventListener("click", () => bukaLembar("lembar-plus"));
el("pil-model").addEventListener("click", () => { bukaLembar("lembar-model"); muatModelLembar(); });
el("aksi-gambar").addEventListener("click", () => el("berkas-gambar").click());
el("aksi-berkas").addEventListener("click", () => el("berkas-apa").click());

/* Ukuran tugas punya dua kontrol: select di baris kotak tulis (layar lebar)
   dan tombol di lembar "+" (layar sempit). Keduanya menulis ke select yang
   sama, jadi tidak ada dua nilai yang bisa berbeda. */
function gambarPilihUkuran() {
  const nilai = el("ukuran").value;
  for (const b of document.querySelectorAll("[data-ukuran-tugas]")) {
    b.setAttribute("aria-pressed", String(b.dataset.ukuranTugas === nilai));
  }
}
for (const b of document.querySelectorAll("[data-ukuran-tugas]")) {
  b.addEventListener("click", () => {
    el("ukuran").value = b.dataset.ukuranTugas;
    gambarPilihUkuran();
  });
}
el("ukuran").addEventListener("change", gambarPilihUkuran);
gambarPilihUkuran();
el("buka-pasang-plugin").addEventListener("click", () => bukaLembar("lembar-plugin"));

/* Menu titik tiga: hal-hal yang tidak punya tempat lain. Menu garis tiga
   memegang daftar fitur, jadi di sini hanya aksi untuk percakapan yang
   sedang dibuka. Tema terang/gelap ada di halaman Pengaturan. */
for (const b of document.querySelectorAll("[data-aksi]")) {
  b.addEventListener("click", async () => {
    tutupMenuTitik();
    const aksi = b.dataset.aksi;
    if (aksi === "ganti-nama") return bukaLembar("lembar-nama");
    if (aksi === "bagikan") return salinPercakapan();
    if (aksi === "sematkan") return sematkanPercakapan();
    if (aksi === "kerja") {
      const tid = stripData[0] ? stripData[0].id : kerjaTugas;
      if (!tid) { pesanSingkat("Belum ada pekerjaan di percakapan ini."); return; }
      return bukaKotakKerja(tid);
    }
  });
}

/* ------------------------------------------------------------ menu garis tiga */

/* Menu garis tiga memuat daftar saja. Riwayat dibuka di dalam lembar ini
   karena daftarnya pendek; yang lain membuka halaman satu layar sendiri, jadi
   daftar menu tidak pernah menumpuk panjang ke bawah. */
const DAFTAR_MENU = [
  { alat: "obrolan", judul: "Riwayat percakapan", ikon: "riwayat" },
  { alat: "terminal", judul: "Terminal", ikon: "terminal" },
  { alat: "skill", judul: "Skill", ikon: "skill" },
  { alat: "plugin", judul: "Plugin MCP", ikon: "plugin" },
  { alat: "capability", judul: "Pasang dari URL", ikon: "plugin" },
  { alat: "pekerja", judul: "Pekerja", ikon: "pekerja" },
  { alat: "berkas", judul: "Berkas dan tes", ikon: "berkas" },
  { alat: "catatan", judul: "Catatan kejadian", ikon: "catatan" },
  { alat: "model", judul: "Model", ikon: "model" },
];
const HALAMAN = {
  obrolan: "alat-obrolan",
  terminal: "alat-terminal",
  skill: "alat-skill",
  plugin: "alat-plugin",
  capability: "alat-capability",
  pekerja: "alat-pekerja",
  berkas: "alat-aktivitas",
  catatan: "alat-aktivitas",
  model: "alat-aktivitas",
  pengaturan: "alat-pengaturan",
};
const JUDUL_HALAMAN = {
  obrolan: "Riwayat percakapan",
  terminal: "Terminal",
  skill: "Skill",
  plugin: "Plugin MCP",
  capability: "Pasang dari URL",
  pekerja: "Pekerja",
  berkas: "Berkas dan tes",
  catatan: "Catatan kejadian",
  model: "Model",
  pengaturan: "Pengaturan",
};

function gambarMenu() {
  const nav = el("nav-alat");
  nav.replaceChildren();
  for (const m of DAFTAR_MENU) {
    const b = buat("button");
    b.type = "button";
    b.dataset.alat = m.alat;
    const l = buat("span", "ikon-nav");
    l.dataset.ikon = m.ikon;
    l.dataset.ukuran = "20";
    l.setAttribute("aria-hidden", "true");
    b.append(l, document.createTextNode(m.judul));
    b.addEventListener("click", () => bukaMenu(m.alat));
    nav.appendChild(b);
  }
  pasangIkon(nav);
}

function bukaMenu(nama) {
  const nav = el("nav-alat");
  for (const b of nav.querySelectorAll("button")) {
    b.setAttribute("aria-current", String(b.dataset.alat === nama));
  }
  // Riwayat tinggal di lembar ini; sisanya membuka halaman sendiri.
  const diLembar = !nama || nama === "obrolan";
  el("alat-menu").hidden = nama === "obrolan";
  el("alat-obrolan").hidden = nama !== "obrolan";
  el("judul-alat").textContent = nama === "obrolan" ? "Riwayat percakapan" : "Menu";
  el("kembali-alat").hidden = nama !== "obrolan";
  // Lambang aplikasi hanya di halaman daftar menu. Di halaman riwayat, tombol
  // kembali sudah ada di posisi yang sama, dan dua hal di satu tempat membuat
  // judulnya bergeser saat berpindah halaman.
  el("lembar-alat").classList.toggle("mode-isi", nama === "obrolan");
  if (!diLembar) { bukaHalaman(nama); return; }
  bukaLembar("lembar-alat");
  if (nama === "obrolan") muatSesi();
}

/* Halaman satu layar: panel yang sama dipindah ke sini, bukan disalin. */
let halamanSekarang = "";

function bukaHalaman(nama) {
  const id = HALAMAN[nama];
  if (!id) return;
  // Halaman lain sedang terbuka: kembalikan panelnya dulu, jangan sampai
  // simpulnya terbuang oleh replaceChildren di bawah.
  if (!el("halaman").hidden) tutupHalaman();
  // Berkas, catatan, dan model sudah terlihat di kolom kanan pada layar lebar.
  // Membuka halaman untuknya justru menyembunyikan panel yang sedang tampil.
  if (["berkas", "catatan", "model"].includes(nama) && layar.aktivitas.matches) {
    pindahTab(nama);
    tutupSemuaLembar();
    const panel = el("aktivitas");
    panel.classList.add("sorot");
    setTimeout(() => panel.classList.remove("sorot"), 900);
    return;
  }
  if (["berkas", "catatan", "model"].includes(nama)) pindahTab(nama);
  tutupSemuaLembar();
  const badan = el("badan-halaman");
  badan.replaceChildren();
  const panel = el(id);
  panel.hidden = false;
  badan.appendChild(panel);
  el("judul-halaman").textContent = JUDUL_HALAMAN[nama] || "Menu";
  el("halaman").hidden = false;
  el("halaman").setAttribute("aria-hidden", "false");
  halamanSekarang = nama;
  pasangIkon(el("halaman"));
  if (nama === "skill") muatSkill();
  if (nama === "terminal") muatTerminal();
  if (nama === "plugin") muatMcp();
  if (nama === "capability") muatCapability();
  if (nama === "pekerja") { muatPekerja(); muatPekerjaPasang(); }
  if (nama === "berkas") { muatBerkas(); muatGit(); }
  if (nama === "model") muatModel();
  el("tutup-halaman").focus();
}

function tutupHalaman() {
  const badan = el("badan-halaman");
  for (const p of badan.querySelectorAll(":scope > .panel")) {
    // Panel kembali ke tempat parkirnya, siap dipakai halaman lain.
    p.hidden = true;
    el("badan-alat").appendChild(p);
  }
  badan.replaceChildren();
  el("halaman").hidden = true;
  el("halaman").setAttribute("aria-hidden", "true");
  halamanSekarang = "";
  // Panel aktivitas dikembalikan ke tempatnya oleh susun(): di >=1280px ia
  // kolom kanan, di bawah itu ia di dalam lembar menu.
  susun();
}

el("tutup-halaman").addEventListener("click", tutupHalaman);
el("kembali-alat").addEventListener("click", () => bukaMenu());
for (const b of document.querySelectorAll("[data-tutup-halaman]")) b.addEventListener("click", tutupHalaman);
for (const b of document.querySelectorAll("#kaki-alat [data-alat]")) {
  b.addEventListener("click", () => bukaHalaman(b.dataset.alat));
}
for (const b of document.querySelectorAll("#tab-alat [role=tab]")) {
  b.addEventListener("click", () => pindahTab(b.dataset.panel));
}
gambarMenu();

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
  isi.dataset.no = p.no || "";
  // Jawaban yang masih dikerjakan bisa diketuk: kotak aktivitas pekerja
  // terbuka, jadi "sedang dikerjakan" bukan teks mati.
  if (p.peran === "astroz" && (p.bisaKlikKerja || p.status === "jalan") && p.tugas) {
    isi.classList.add("bisa-diketuk");
    isi.setAttribute("role", "button");
    isi.setAttribute("tabindex", "0");
    isi.setAttribute("aria-label", "sedang dikerjakan, buka aktivitas pekerja");
    const buka = () => bukaKotakKerja(p.tugas);
    isi.addEventListener("click", buka);
    isi.addEventListener("keydown", (ev) => { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); buka(); } });
  }
  baris.appendChild(isi);

  const aksi = buat("div", "baris-aksi-pesan");
  if (p.peran === "astroz") {
    if (p.status === "jalan") {
      // Sumber yang sedang dibaca pekerja: lambangnya muncul selagi mencari,
      // bukan baru di akhir.
      const chipJalan = chipSumber(p.sumberSementara, "sumber-jalan");
      if (chipJalan) aksi.appendChild(chipJalan);
    }
    if (p.status) {
      const cap = buat("span", "cap " + p.status,
        p.status === "jalan" ? "sedang jalan" : p.status === "gagal" ? "gagal" : p.status === "batal" ? "dihentikan" : p.status === "selesai" ? "selesai" : "jawaban");
      aksi.appendChild(cap);
    }
    if (p.pekerja) aksi.appendChild(buat("span", "waktu", p.pekerja));
    if (p.tes === true) aksi.appendChild(buat("span", "waktu", "tes lulus"));
    if (p.tes === false) aksi.appendChild(buat("span", "waktu", "tes gagal"));
    if (p.ts) aksi.appendChild(buat("span", "waktu", waktu(p.ts)));

    /* Baris aksi jawaban: salin, tanya ulang, sumber. Suka, tidak suka, dan
       bacakan dihapus: ketiganya fitur umpan balik untuk pengembang model,
       bukan untuk pengguna aplikasi ini. */
    const aksiKiri = buat("div", "aksi-deret");
    aksiKiri.appendChild(tombolAksi("salin", "Salin jawaban ini", () => salinJawaban(p.teks || "")));
    aksiKiri.appendChild(tombolAksi("ulang", "Tanya ulang pesan ini", () => tanyaUlang(p)));
    if (p.tugas) aksiKiri.appendChild(tombolAksi("berkas", "Lihat proses kerja", () => { tampilkanKerja(p.tugas); }));
    aksi.appendChild(aksiKiri);
    const chip = chipSumber(p.sumber);
    if (chip) aksi.appendChild(chip);
  } else if (p.ts) {
    aksi.appendChild(buat("span", "waktu", waktu(p.ts)));
  }
  baris.appendChild(aksi);
  return baris;
}

/* ------------------------------------------------- chip sumber jawaban */

/* Satu lambang per sumber, berderet rapat tanpa kotak. Sebelumnya tiap sumber
   dibungkus pil berisi lambang dan namanya: satu jawaban dengan empat sumber
   memakan hampir satu baris penuh di layar HP. Sekarang yang tampil cuma
   lambangnya, dan namanya muncul sebagai judul ketukan. Satu alamat hanya
   muncul sekali, jadi satu sumber tidak pernah dapat dua lambang. */
function chipSumber(daftar, kelas) {
  const sumber = gabungSumber(daftar, [], 8);
  if (!sumber.length) return null;
  const baris = buat("div", "sumber-baris" + (kelas ? " " + kelas : ""));
  const kotak = buat("div", "sumber-chip");
  kotak.setAttribute("role", "group");
  kotak.setAttribute("aria-label", "Sumber jawaban");
  for (const s of sumber) {
    const c = buat("button", "sumber");
    c.type = "button";
    c.title = namaSumber(s) + " · " + s.url;
    c.setAttribute("aria-label", "Sumber: " + namaSumber(s));
    c.appendChild(lambangSumber(s.url));
    c.addEventListener("click", () => daftarSumber(sumber, c));
    kotak.appendChild(c);
  }
  baris.appendChild(kotak);
  return baris;
}

/* Lambang sumber: jalur ikon merek yang sudah disimpan di web/sumber.js, jadi
   lambangnya benar-benar logo OpenAI, Facebook, Instagram, dan seterusnya.
   Tidak ada permintaan ke situs aslinya saat percakapan dibuka: berkasnya
   lokal. Kalau mereknya tidak ada di peta, jatuh ke inisial domain. */
const _hostMerek = new Map();   // host -> kunci merek, supaya pemetaan tidak diulang

/* Kunci merek dari sebuah host. Dua langkah: cocokkan label domain langsung
   (openai.com -> openai), lalu cocokkan potongan nama (help.openai.com,
   anthropic.com -> anthropic). Yang lebih spesifik menang: "news.ycombinator.com"
   tidak boleh jadi "news". */
function kunciMerek(host) {
  if (_hostMerek.has(host)) return _hostMerek.get(host);
  const bagian = host.split(".").filter((x) => x && x !== "www");
  let kunci = "";
  if (bagian.length) {
    const label = bagian[0].toLowerCase().replace(/[^a-z0-9]/g, "");
    if (label && LAMBANG_MEREK[label]) kunci = label;
    else {
      const gabung = bagian.join("").toLowerCase().replace(/[^a-z0-9]/g, "");
      const nama = bagian[0].toLowerCase().replace(/[^a-z0-9]/g, "");
      for (const k of Object.keys(LAMBANG_MEREK)) {
        if (gabung.includes(k) || (nama.length > 3 && k.includes(nama))) { kunci = k; break; }
      }
    }
  }
  _hostMerek.set(host, kunci);
  return kunci;
}

/* Nama merek yang enak dibaca dari host: "openai.com" -> "OpenAI". */
function namaMerek(host) {
  const kunci = kunciMerek(host);
  if (kunci) return LAMBANG_MEREK[kunci].nama;
  const label = (host.split(".")[0] || host).replace(/[^a-z0-9-]/gi, " ");
  return label.replace(/(^|\s|-)([a-z])/g, (_, a, b) => a + b.toUpperCase()).trim() || host;
}

function hostDari(url) {
  try { return new URL(url).hostname.replace(/^www\./, "").toLowerCase(); } catch { return ""; }
}

function lambangSumber(url) {
  const host = hostDari(url) || String(url || "");
  const kunci = kunciMerek(host);
  if (kunci) {
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("width", "14");
    svg.setAttribute("height", "14");
    svg.setAttribute("fill", "currentColor");
    svg.setAttribute("aria-hidden", "true");
    const p = document.createElementNS("http://www.w3.org/2000/svg", "path");
    p.setAttribute("d", LAMBANG_MEREK[kunci].d);
    svg.appendChild(p);
    const l = buat("span", "lambang-sumber");
    l.appendChild(svg);
    l.setAttribute("aria-hidden", "true");
    return l;
  }
  const l = buat("span", "lambang-sumber huruf", (host[0] || "?").toUpperCase());
  l.setAttribute("aria-hidden", "true");
  return l;
}

/* Nama sumber yang ditampilkan: merek kalau dikenal, domain kalau tidak. */
function namaSumber(s) {
  const host = hostDari(s.url);
  const nama = (s.nama || "").trim();
  const merek = namaMerek(host);
  if (!nama || nama === host || nama === s.url) return merek || nama || host;
  return nama;
}

/* Domain resmi merek yang paling sering muncul di percakapan. Dipakai untuk
   chip "sedang mencari", karena saat itu yang ada cuma nama merek di dalam
   perintah, belum ada tautan yang bisa dibaca. Merek di luar peta ini baru
   muncul lambangnya begitu pekerja membuka tautan sungguhan. */
const HOST_MEREK = {
  openai: "openai.com", anthropic: "anthropic.com", github: "github.com",
  google: "google.com", googlegemini: "gemini.google.com", youtube: "youtube.com",
  facebook: "facebook.com", instagram: "instagram.com", whatsapp: "whatsapp.com",
  telegram: "telegram.org", x: "x.com", tiktok: "tiktok.com", linkedin: "linkedin.com",
  reddit: "reddit.com", pinterest: "pinterest.com", threads: "threads.net",
  discord: "discord.com", slack: "slack.com", medium: "medium.com",
  wikipedia: "wikipedia.org", wikimediafoundation: "wikimediafoundation.org",
  stackoverflow: "stackoverflow.com", stackexchange: "stackexchange.com",
  microsoft: "microsoft.com", apple: "apple.com", amazon: "amazon.com",
  netflix: "netflix.com", spotify: "spotify.com", zoom: "zoom.us",
  dropbox: "dropbox.com", notion: "notion.so", figma: "figma.com",
  cloudflare: "cloudflare.com", docker: "docker.com", gitlab: "gitlab.com",
  bitbucket: "bitbucket.org", npm: "npmjs.com", python: "python.org",
  javascript: "javascript.com", typescript: "typescriptlang.org", react: "react.dev",
  vue: "vuejs.org", angular: "angular.dev", svelte: "svelte.dev", node: "nodejs.org",
  mongodb: "mongodb.com", postgresql: "postgresql.org", mysql: "mysql.com",
  redis: "redis.io", stripe: "stripe.com", paypal: "paypal.com", visa: "visa.com",
  mastercard: "mastercard.com", gojek: "gojek.com", grab: "grab.com",
  tokopedia: "tokopedia.com", shopee: "shopee.co.id", bukalapak: "bukalapak.com",
  traveloka: "traveloka.com", bca: "bca.co.id", dana: "dana.id", ovo: "ovo.id",
  detik: "detik.com", kompas: "kompas.com", cnbc: "cnbc.com", cnn: "cnn.com",
  bbc: "bbc.com", reuters: "reuters.com", nytimes: "nytimes.com",
  bloomberg: "bloomberg.com", forbes: "forbes.com", tempo: "tempo.co",
  kaggle: "kaggle.com", huggingface: "huggingface.co", arxiv: "arxiv.org",
  springer: "springer.com", sciencedirect: "sciencedirect.com", nature: "nature.com",
  gmail: "mail.google.com", googledrive: "drive.google.com", googledocs: "docs.google.com",
  googlesheets: "sheets.google.com", googlecalendar: "calendar.google.com",
  googlemaps: "maps.google.com", googleplay: "play.google.com", googlecloud: "cloud.google.com",
  googlescholar: "scholar.google.com", ebay: "ebay.com", alibaba: "alibaba.com",
  aliexpress: "aliexpress.com", bing: "bing.com", duckduckgo: "duckduckgo.com",
  yahoo: "yahoo.com", firefox: "mozilla.org", chrome: "google.com",
  ubuntu: "ubuntu.com", linux: "linux.org", archlinux: "archlinux.org",
  debian: "debian.org", termux: "termux.dev", android: "android.com",
  steam: "steampowered.com", epicgames: "epicgames.com", playstation: "playstation.com",
  nintendo: "nintendo.com", xbox: "xbox.com", nvidia: "nvidia.com", amd: "amd.com",
  intel: "intel.com", samsung: "samsung.com", xiaomi: "mi.com", oppo: "oppo.com",
  vivo: "vivo.com", huawei: "huawei.com", asus: "asus.com", lenovo: "lenovo.com",
  dell: "dell.com", hp: "hp.com", adobe: "adobe.com", canva: "canva.com",
  blender: "blender.org", unity: "unity.com", unrealengine: "unrealengine.com",
  godotengine: "godotengine.org", wordpress: "wordpress.com", wix: "wix.com",
  shopify: "shopify.com", airbnb: "airbnb.com", uber: "uber.com", booking: "booking.com",
  agoda: "agoda.com", tripadvisor: "tripadvisor.com", googlefonts: "fonts.google.com",
  buymeacoffee: "buymeacoffee.com", patreon: "patreon.com", substack: "substack.com",
};

/* Merek yang disebut di dalam perintah atau di catatan pencarian pekerja.
   Pekerja sering mencari dulu sebelum sempat membuka tautan apa pun, jadi tanpa
   ini lambangnya baru muncul di akhir padahal merek yang dicari sudah jelas
   sejak awal ("carikan info tentang OpenAI"). */
function merekDariTeks(teks, maks = 4) {
  const t = " " + String(teks || "").toLowerCase().replace(/[^a-z0-9]+/g, " ") + " ";
  const out = [];
  const ada = new Set();
  for (const kunci of Object.keys(HOST_MEREK)) {
    if (kunci.length < 3) continue;
    if (!t.includes(" " + kunci + " ")) continue;
    const host = HOST_MEREK[kunci];
    if (ada.has(host)) continue;
    ada.add(host);
    out.push({ nama: namaMerek(host), url: "https://" + host + "/" });
    if (out.length >= maks) break;
  }
  return out;
}

/* Gabung dua daftar sumber tanpa duplikat host, yang pertama menang. */
function gabungSumber(utama, tambahan, maks = 4) {
  const out = [];
  const ada = new Set();
  for (const s of [...(utama || []), ...(tambahan || [])]) {
    if (!s || !s.url) continue;
    const host = hostDari(s.url) || s.url;
    if (ada.has(host)) continue;
    ada.add(host);
    out.push(s);
    if (out.length >= maks) break;
  }
  return out;
}


/* Sumber sementara dari catatan pekerja: pekerja memakai alat `cari` dan `buka`,
   dan tautan yang dibukanya muncul di keluaran pekerja. Selama tugas berjalan,
   tautan itu ditampilkan sebagai lambang kecil di bawah "sedang dikerjakan",
   jadi terlihat sumber apa yang sedang dibaca. Sesudah selesai, yang tampil
   adalah sumber yang benar-benar dipakai jawaban. */
const _URL_RX = /https?:\/\/[^\s<>"'`)\]}]+/g;

function sumberDariTeks(teks, maks = 4) {
  const out = [];
  const ada = new Set();
  for (const m of String(teks || "").matchAll(_URL_RX)) {
    const url = m[0].replace(/[.,;:]+$/, "");
    const host = hostDari(url);
    if (!host || host === "127.0.0.1" || host === "localhost") continue;
    if (ada.has(host)) continue;
    ada.add(host);
    out.push({ nama: namaMerek(host), url });
    if (out.length >= maks) break;
  }
  return out;
}

function sumberSementaraDari(evs, maks = 4, perintah = "") {
  const teks = (evs || [])
    .filter((e) => e.kind === "worker" || e.kind === "plan")
    .map((e) => e.text || e.message || "")
    .join("\n");
  // Tautan yang benar-benar dibuka pekerja lebih kuat daripada nama merek di
  // dalam perintah, jadi urutannya begitu.
  return gabungSumber(sumberDariTeks(teks, maks), merekDariTeks(perintah, maks), maks);
}

function daftarSumber(sumber, jangkar) {
  const lama = el("menu-sumber");
  if (lama) lama.remove();
  const kotak = buat("div", "menu-sumber");
  kotak.id = "menu-sumber";
  kotak.setAttribute("role", "menu");
  for (const s of sumber) {
    const b = buat("a", null);
    b.href = s.url;
    b.target = "_blank";
    b.rel = "noreferrer noopener";
    b.setAttribute("role", "menuitem");
    b.appendChild(lambangSumber(s.url));
    const teks = buat("span", "teks");
    teks.appendChild(buat("span", "nama", namaSumber(s)));
    teks.appendChild(buat("span", "tautan", s.url));
    b.appendChild(teks);
    kotak.appendChild(b);
  }
  document.body.appendChild(kotak);
  const r = jangkar.getBoundingClientRect();
  const lebar = Math.min(320, Math.max(220, window.innerWidth - 24));
  kotak.style.width = lebar + "px";
  kotak.style.left = Math.max(12, Math.min(r.left, window.innerWidth - lebar - 12)) + "px";
  kotak.style.top = Math.min(window.innerHeight - kotak.offsetHeight - 12, r.bottom + 6) + "px";
  const tutup = (ev) => {
    if (!kotak.contains(ev.target)) {
      kotak.remove();
      document.removeEventListener("click", tutup);
      window.removeEventListener("keydown", esc);
    }
  };
  const esc = (ev) => { if (ev.key === "Escape") { kotak.remove(); document.removeEventListener("click", tutup); } };
  setTimeout(() => document.addEventListener("click", tutup), 0);
  window.addEventListener("keydown", esc);
}

/* ------------------------------------------------- aksi per jawaban */

async function salinJawaban(teks) {
  const isi = (teks || "").trim();
  if (!isi) return;
  try {
    await navigator.clipboard.writeText(isi);
    pesanSingkat("Jawaban disalin.");
  } catch {
    // clipboard API butuh konteks aman (https atau localhost); di alamat LAN
    // lewat http, jalan pintas lama ini yang dipakai.
    const t = buat("textarea");
    t.value = isi;
    t.style.position = "fixed";
    t.style.opacity = "0";
    document.body.appendChild(t);
    t.select();
    try { document.execCommand("copy"); pesanSingkat("Jawaban disalin."); }
    catch { pesanSingkat("Tidak bisa menyalin di peramban ini.", true); }
    t.remove();
  }
}

/* Tanya ulang: satu pesan saja, bukan seluruh percakapan. Teks pesan pengguna
   di atasnya dipakai lagi sebagai perintah baru. */
function tanyaUlang(p) {
  const daftar = keadaan.pesan;
  const i = daftar.indexOf(p);
  let teks = "";
  for (let j = (i < 0 ? daftar.length : i) - 1; j >= 0; j--) {
    if (daftar[j].peran === "aku" && daftar[j].teks) { teks = daftar[j].teks; break; }
  }
  if (!teks) { pesanSingkat("Pesan asalnya tidak ada lagi di percakapan ini.", true); return; }
  const kotak = el("tulis");
  kotak.value = teks;
  tumbuh();
  kotak.focus();
  pesanSingkat("Pesan ini dikembalikan ke kotak tulis. Ubah kalau perlu, lalu kirim.");
}

/* Baris kecil di bawah jawaban: apa yang dikerjakan tim, diambil dari catatan
   kejadian yang sudah ada. Ini yang membuat percakapan tidak perlu panel
   aktivitas terpisah untuk hal-hal pokok. */

function keDasar(paksa = false) {
  const a = el("alur");
  // Paksa: saat percakapan baru dibuka atau digambar ulang. Tanpa paksa, satu
  // catatan lama yang posisi gulirnya tidak di dasar membuat percakapan yang
  // baru dibuka tampil di tengah, dan pengguna harus menggulir sendiri untuk
  // melihat pesan terakhir.
  const dekat = a.scrollHeight - a.scrollTop - a.clientHeight < 140;
  if (paksa || dekat || !a._pernah) a.scrollTop = a.scrollHeight;
  a._pernah = true;
}

function tambahPesan(p) {
  keadaan.pesan.push(p);
  const baris = gambarPesan(p);
  p.baris = baris;
  kolom().appendChild(baris);
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
  kerjaTugas = null;
  tutupKotakKerja();
  tutupSemuaLembar();
  el("tulis").focus();
  muatSesi();
}
el("sesi-baru").addEventListener("click", sesiBaru);

/* Keluar: hapus cookie token di server, lalu tampilkan layar masuk lagi.
   Sebelumnya endpoint /api/keluar ada di server tetapi tidak ada tombolnya,
   jadi satu-satunya cara berhenti memakai token adalah menghapus cookie
   sendiri lewat pengaturan peramban.

   Halaman dimuat ulang setelah cookie dihapus, bukan sekadar membersihkan
   sebagian keadaan di memori. Terukur: tanpa muat ulang, panel yang sudah
   tergambar (daftar skill berikut jalur paketnya) masih menampilkan isi milik
   pengguna sebelumnya sampai halaman disegarkan sendiri. */
el("kaki-keluar").addEventListener("click", async () => {
  const b = el("kaki-keluar");
  b.disabled = true;
  try {
    await kirim("/api/keluar", {});
  } catch {
    // Cookie mungkin sudah tidak ada; yang penting sesinya diakhiri.
  }
  // Tanpa token, halaman memuat layar masuk sendiri lewat /api/saya.
  location.replace(location.pathname);
});

/* ----------------------------------------------------------- riwayat sesi */

/* Riwayat percakapan.
   Satu baris = satu tombol penuh (judul di atas, waktu di bawah) plus satu
   tombol titik tiga. Sebelumnya tiap baris punya DUA tombol ikon tetap, semat
   dan hapus: di lembar selebar 232px keduanya memakan hampir separuh lebar,
   judulnya terpotong jadi satu kata, dan barisnya terlihat menumpuk. Aksi yang
   jarang dipakai sekarang ada di dalam menu, jadi lebar baris tetap dan judul
   dapat ruang. */
function gambarDaftarSesi(daftar) {
  const wadah = el("daftar-sesi");
  wadah.replaceChildren();
  if (!daftar.length) {
    wadah.appendChild(buat("p", "kosong", "Belum ada percakapan. Kirim satu pesan untuk memulai."));
    return;
  }
  for (const s of daftar) {
    const baris = buat("div", "baris-sesi" + (s.pinned ? " disematkan" : ""));
    const b = buat("button", "buka");
    b.type = "button";
    if (s.id === keadaan.sesi) b.setAttribute("aria-current", "true");
    const atas = buat("div", "atas");
    if (s.pinned) {
      const l = buat("span", "lambang-semat");
      l.setAttribute("aria-hidden", "true");
      l.appendChild(ikon("sematkan", 14));
      atas.appendChild(l);
    }
    atas.appendChild(buat("div", "judul" + ((s.title || "").length <= 28 ? " pendek" : ""), s.title || "Percakapan baru"));
    b.appendChild(atas);
    // Waktu dan jumlah tugas tidak ditulis sebagai baris kedua. Dua baris per
    // percakapan membuat daftar terlihat menumpuk, dan itu yang dikeluhkan.
    // Informasinya tetap ada sebagai judul ketukan (tooltip), jadi tidak ada
    // yang hilang, hanya tidak lagi memakan tinggi.
    b.title = `${s.title || "Percakapan baru"} · ${tanggalPendek(s.updated || s.created)} · ${(s.tasks || []).length} tugas`;
    b.addEventListener("click", () => { bukaSesi(s.id); tutupSemuaLembar(); });

    const aksi = buat("button", "aksi-sesi");
    aksi.type = "button";
    aksi.setAttribute("aria-label", "Aksi untuk percakapan " + (s.title || ""));
    aksi.setAttribute("aria-haspopup", "menu");
    aksi.setAttribute("aria-expanded", "false");
    aksi.appendChild(ikon("titik-tiga", 18));
    const menu = buat("div", "menu-sesi");
    menu.setAttribute("role", "menu");
    menu.hidden = true;

    const tombolSemat = buat("button");
    tombolSemat.type = "button";
    tombolSemat.setAttribute("role", "menuitem");
    tombolSemat.appendChild(ikon("sematkan", 16));
    tombolSemat.appendChild(buat("span", "", s.pinned ? "Lepas sematan" : "Sematkan"));
    tombolSemat.addEventListener("click", async () => {
      menu.hidden = true;
      aksi.setAttribute("aria-expanded", "false");
      await kirim(`/api/sessions/${s.id}/sematkan`, { pinned: !s.pinned });
      await muatSesi();
      pesanSingkat(s.pinned ? "Sematan dilepas." : "Percakapan disematkan di atas.");
    });

    const tombolHapus = buat("button", "bahaya");
    tombolHapus.type = "button";
    tombolHapus.setAttribute("role", "menuitem");
    tombolHapus.appendChild(ikon("hapus", 16));
    tombolHapus.appendChild(buat("span", "", "Hapus"));
    tombolHapus.addEventListener("click", async () => {
      menu.hidden = true;
      aksi.setAttribute("aria-expanded", "false");
      if (!confirm("Hapus percakapan ini dari daftar? Tugas dan berkasnya tetap ada.")) return;
      await minta(`/api/sessions/${s.id}`, { method: "DELETE" });
      if (s.id === keadaan.sesi) sesiBaru();
      await muatSesi();
      pesanSingkat("Percakapan dihapus dari daftar.");
    });

    menu.append(tombolSemat, tombolHapus);
    aksi.addEventListener("click", (ev) => {
      ev.stopPropagation();
      const buka = menu.hidden;
      // Hanya satu menu riwayat yang boleh terbuka: menu yang tertinggal
      // terbuka di baris lain membuat daftar terlihat penuh dan tidak rapi.
      for (const lain of wadah.querySelectorAll(".menu-sesi")) lain.hidden = true;
      for (const lain of wadah.querySelectorAll(".aksi-sesi")) lain.setAttribute("aria-expanded", "false");
      menu.hidden = !buka;
      aksi.setAttribute("aria-expanded", String(buka));
    });
    baris.append(b, aksi, menu);
    wadah.appendChild(baris);
  }
}

/* Sematkan percakapan yang sedang dibuka, dari menu titik tiga. */
async function sematkanPercakapan() {
  if (!keadaan.sesi) { pesanSingkat("Belum ada percakapan yang dibuka.", true); return; }
  try {
    const d = await kirim(`/api/sessions/${keadaan.sesi}/sematkan`, {});
    await muatSesi();
    pesanSingkat(d.pinned ? "Percakapan disematkan di atas daftar." : "Sematan dilepas.");
  } catch (e) {
    pesanSingkat("Gagal menyematkan: " + e.message, true);
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
    let noPesan = 0;
    const pesan = d.messages || [];
    if (!pesan.length) kosongkanChat("Percakapan ini masih kosong.");
    else {
      tampilkanKosong(false);
      for (const m of pesan) {
        noPesan += 1;
        tambahPesan({
          peran: m.role === "user" ? "aku" : "astroz",
          no: noPesan,
          teks: m.text,
          ts: m.ts,
          tugas: m.task,
          status: m.role === "user" ? "" : (m.status === "done" ? "selesai" : m.status === "failed" || m.status === "error" ? "gagal" : m.status === "cancelled" ? "batal" : m.status === "running" ? "jalan" : ""),
          tes: m.tests,
          pekerja: (m.workers || [])[0],
          sumber: m.sources || [],
        });
      }
    }
    const jalan = pesan.filter((m) => m.role !== "user" && m.status === "running").map((m) => m.task);
    keadaan.tugasJalan = jalan.length ? jalan[jalan.length - 1] : null;
    // Percakapan yang baru dibuka selalu tampil dari pesan terakhir. Posisi
    // gulir .alur dipakai bersama semua percakapan, jadi tanpa paksa, membuka
    // percakapan panjang setelah menggulir di percakapan lain menampilkan
    // bagian tengah percakapan.
    keDasar(true);
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
  // Batasnya dibaca dari CSS, bukan angka mati di sini. Kalau keduanya
  // berbeda, tinggi yang dipasang JS menang dan batas CSS tidak berlaku.
  const batas = parseFloat(getComputedStyle(t).maxHeight) || 200;
  t.style.height = "auto";
  t.style.height = Math.min(batas, t.scrollHeight) + "px";
}
el("tulis").addEventListener("input", tumbuh);
// Layar berputar atau tinggi berubah (papan ketik terbuka): batasnya berubah,
// jadi tingginya dihitung ulang. Tanpa ini, kotak bisa tertinggal terlalu
// tinggi setelah papan ketik ditutup.
addEventListener("resize", () => { tumbuh(); });
if (window.visualViewport) visualViewport.addEventListener("resize", () => { tumbuh(); });

/* Satu kiriman pada satu waktu. Tombol kirim dinonaktifkan selama pengiriman,
   tapi itu tidak menahan Enter: requestSubmit tetap memicu submit walau
   tombolnya disabled. Tanpa penjaga ini, menekan Enter dua kali cepat
   mengirim dua tugas untuk satu pesan. */
let sedangKirim = false;

el("form-tulis").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const kotak = el("tulis");
  const teks = kotak.value.trim();
  if (!teks) { pesanSingkat("Tulis dulu isi pesannya."); kotak.focus(); return; }
  if (sedangKirim) return;
  sedangKirim = true;
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
    const p = tambahPesan({ peran: "astroz", teks: "sedang dikerjakan", ts: Date.now() / 1000, status: "jalan", tugas: d.task_id, bisaKlikKerja: true });
    keadaan.tugasJalan = d.task_id;
    kerjaTugas = d.task_id;
    gambarKerja();
    pantauTugas(d.task_id);
    muatSesi();
  } catch (err) {
    // Pesannya tidak sampai ke server, jadi teksnya dikembalikan ke kotak
    // tulis. Sebelumnya kotaknya sudah dikosongkan dan teksnya hilang, jadi
    // pengguna harus menulis ulang dari nol.
    kotak.value = teks;
    tumbuh();
    if (lampiran) pasangLampiran(String(lampiran).split("/").pop(), lampiran);
    tambahPesan({ peran: "astroz", teks: "Pesan tidak terkirim: " + err.message, status: "gagal", ts: Date.now() / 1000 });
    pesanSingkat("Pesan tidak terkirim: " + err.message, true);
  } finally {
    sedangKirim = false;
    el("kirim").disabled = false;
    kotak.focus();
  }
});

el("tulis").addEventListener("keydown", (ev) => {
  // Enter saat memilih huruf di IME (masukan bahasa Asia) hanya menutup daftar
  // pilihan, bukan mengirim pesan. Tanpa penjaga ini, pesan terkirim separuh
  // jalan di tengah kata.
  if (ev.isComposing || ev.keyCode === 229) return;
  if (ev.key === "Enter" && !ev.shiftKey) {
    ev.preventDefault();
    el("form-tulis").requestSubmit();
  }
});

/* ------------------------------------------------------------------ kerja */

/* Aktivitas pekerja tinggal di dalam kotak "sedang dikerjakan" (dan di kolom
   kanan pada layar lebar untuk berkas/catatan/model). Menu garis tiga tidak
   lagi punya bagian proses kerja. */
let kerjaTugas = null;
let jamKerja = null;

function pindahTab(panel) {
  for (const b of document.querySelectorAll("#tab-alat [role=tab]")) {
    b.setAttribute("aria-selected", String(b.dataset.panel === panel));
  }
  for (const p of document.querySelectorAll("#aktivitas .panel")) {
    p.hidden = p.id !== "panel-" + panel;
  }
  // Di dalam halaman satu layar, judul halamannya ikut berganti supaya
  // pengguna tahu bagian mana yang sedang dibaca.
  if (["berkas", "catatan", "model"].includes(halamanSekarang)) {
    halamanSekarang = panel;
    el("judul-halaman").textContent = JUDUL_HALAMAN[panel];
  }
}

/* Buka proses kerja: di layar lebar panelnya jadi kolom kanan, di layar sempit
   isinya tampil di kotak aktivitas pekerja. */
function tampilkanKerja(tid) {
  kerjaTugas = tid;
  if (layar.aktivitas.matches) {
    pindahTab("catatan");
    const panel = el("aktivitas");
    panel.classList.add("sorot");
    setTimeout(() => panel.classList.remove("sorot"), 900);
    gambarKerja();
    return;
  }
  bukaKotakKerja(tid);
}

/* ------------------------------------------------------------------ tahap */

/* Tahap pekerjaan, dihitung dari kejadian yang SUDAH ADA, bukan dari data
   baru. Orchestrator memancarkan kind plan/worker/test/review/discuss/git/task
   dan phase start/end/stall/error; dari situ tahapnya bisa disimpulkan tanpa
   menambah apa pun di backend.

   Kenapa perlu: sebelumnya pengguna hanya melihat daftar kejadian mentah
   ("worker · codex · start") dan harus menyimpulkan sendiri sedang di tahap
   apa. Dengan label tahap, satu pandangan sudah cukup. */
const TAHAP = [
  { kunci: "plan", label: "Perencanaan" },
  { kunci: "worker", label: "Pengerjaan" },
  { kunci: "discuss", label: "Diskusi" },
  { kunci: "test", label: "Pengujian" },
  { kunci: "review", label: "Peninjauan" },
  { kunci: "git", label: "Simpan perubahan" },
  { kunci: "task", label: "Penutup" },
];

function tahapDari(evs, t) {
  const terpakai = new Set(evs.map((e) => e.kind));
  const aktif = [...evs].reverse().find((e) => !["end"].includes(e.phase || ""));
  const sekarang = aktif ? aktif.kind : "";
  const hasil = TAHAP.map((s) => ({
    ...s,
    aktif: s.kunci === sekarang,
    selesai: terpakai.has(s.kunci) && s.kunci !== sekarang,
  }));
  if (t.status === "failed" || t.status === "error") {
    // Tandai tahap tempat kegagalan terjadi, supaya terlihat di mana berhentinya.
    for (const s of hasil) if (s.aktif) s.gagal = true;
  }
  return hasil.filter((s) => s.aktif || s.selesai);
}

/* Satu langkah kejadian: waktu, tahap, pekerja, lalu pesan. Pesan dirapikan
   (baris kosong dibuang, dipotong di batas yang wajar) supaya tidak ada blok
   teks mentah yang mengacak-acak tata letak. */
function barisLangkah(e) {
  const baris = buat("div", "kejadian");
  baris.dataset.jenis = e.kind || "";
  const fase = String(e.phase || "");
  if (fase) baris.dataset.fase = fase;
  baris.appendChild(buat("div", "waktu", waktu(e.ts)));
  const tengah = buat("div", "isi-langkah");
  const judul = [TAHAP.find((s) => s.kunci === e.kind)?.label || e.kind, e.worker, fase]
    .filter(Boolean).join(" · ");
  tengah.appendChild(buat("div", "jenis", judul));
  const pesan = String(e.text || e.message || "")
    .split("\n").map((x) => x.trimEnd()).filter((x) => x.trim()).join("\n");
  if (pesan) tengah.appendChild(buat("div", "pesan-log", pesan));
  baris.appendChild(tengah);
  return baris;
}

/* Isi kotak aktivitas: keadaan tugas, pekerja mana yang aktif, berkas yang
   berubah, lalu langkah terakhir. Semuanya dari endpoint yang sudah ada. */
async function gambarKerja() {
  const wadah = el("badan-kotak-kerja");
  if (!wadah || el("tirai-kerja").hidden) return;
  const tid = kerjaTugas;
  if (!tid) { wadah.replaceChildren(buat("p", "kosong", "Tidak ada pekerjaan berjalan.")); return; }
  let d;
  try {
    d = await ambil(`/api/tasks/${tid}`);
  } catch {
    return; // biarkan tampilan terakhir
  }
  const t = d.task || {};
  const jalan = t.status === "running";
  wadah.replaceChildren();

  const kepala = buat("div", "kotak-kerja");
  const labelStatus = t.status === "cancelled" ? "dihentikan"
    : t.status === "failed" || t.status === "error" ? "gagal"
    : t.status === "done" ? "selesai" : "sedang dikerjakan";
  kepala.appendChild(buat("div", "nama", labelStatus));
  kepala.appendChild(buat("div", "baris-kecil",
    "tugas " + tid + "  ·  ukuran " + (t.size || "otomatis") + "  ·  model " + (t.model || "bawaan")));
  if (t.workers && t.workers.length) {
    kepala.appendChild(buat("div", "baris-kecil", "pekerja: " + t.workers.join(", ")));
  }
  if (t.prompt) kepala.appendChild(buat("div", "baris-kecil perintah", String(t.prompt).slice(0, 200)));
  wadah.appendChild(kepala);

  // Kind yang benar-benar dipancarkan orchestrator: plan, worker, test, review,
  // discuss, git, task. "catatan" (log panel) tidak dipakai di sini: kalau ikut,
  // langkah terakhir penuh baris log dan bukan langkah kerja.
  const evs = (d.events || []).filter((e) => ["plan", "worker", "test", "review", "discuss", "git", "task"].includes(e.kind));

  // Tahap: dihitung dari kejadian yang ada, jadi pengguna tahu posisinya.
  const tahap = tahapDari(evs, t);
  if (tahap.length) {
    const kotak = buat("div", "kotak-kerja");
    kotak.appendChild(buat("div", "nama", "tahap"));
    const deret = buat("div", "deret-tahap");
    for (const s of tahap) {
      const c = buat("span", "tahap" + (s.aktif ? " aktif" : "") + (s.selesai ? " selesai" : "") + (s.gagal ? " gagal" : ""));
      c.appendChild(buat("span", "tahap-titik"));
      c.appendChild(document.createTextNode(s.label));
      deret.appendChild(c);
    }
    kotak.appendChild(deret);
    wadah.appendChild(kotak);
  }

  // Pekerja yang sedang aktif, dihitung dari kejadian terakhirnya: daftar
  // penugasan saja tidak tahu siapa yang sudah selesai.
  const akhir = {};
  for (const e of evs) if (e.worker) akhir[e.worker] = e.phase || "";
  const pekerja = (t.workers || []).map((w) => ({ nama: w, aktif: !["end", "stall", "error"].includes(akhir[w] || "") }));
  if (pekerja.length) {
    const baris = buat("div", "kotak-kerja");
    baris.appendChild(buat("div", "nama", "pekerja saat ini"));
    const deret = buat("div", "strip-pekerja");
    deret.style.marginTop = "6px";
    for (const p of pekerja) deret.appendChild(buat("span", "p" + (p.aktif ? "" : " selesai"), p.nama));
    baris.appendChild(deret);
    wadah.appendChild(baris);
  }

  const berkas = await ambil(`/api/tasks/${tid}/berkas`).catch(() => null);
  if (berkas && berkas.jumlah) {
    const bk = buat("div", "kotak-kerja");
    bk.appendChild(buat("div", "nama", berkas.jumlah + " berkas berubah"));
    for (const f of berkas.berkas.slice(0, 8)) {
      bk.appendChild(buat("div", "baris-kecil berkas-baris", f.path + "  " + f.size + " b"));
    }
    wadah.appendChild(bk);
  }

  const langkah = buat("div", "kotak-kerja");
  langkah.appendChild(buat("div", "nama", "langkah terakhir"));
  const isiLangkah = buat("div", "daftar-langkah");
  isiLangkah.id = "isi-kerja";
  if (!evs.length) {
    isiLangkah.appendChild(buat("p", "kosong", jalan ? "Menunggu langkah pertama." : "Tidak ada catatan langkah."));
  }
  for (const e of evs.slice(-40)) isiLangkah.appendChild(barisLangkah(e));
  langkah.appendChild(isiLangkah);
  wadah.appendChild(langkah);

  if (jalan) {
    const h = buat("button", "tombol kecil diam", "hentikan tugas ini");
    h.type = "button";
    h.addEventListener("click", () => hentikanTugas(tid, h));
    wadah.appendChild(h);
  }
  if (!jalan && jamKerja) { clearInterval(jamKerja); jamKerja = null; }
}

/* Kotak aktivitas: tidak memenuhi layar percakapan, hanya bagian tengahnya. */
function bukaKotakKerja(tid) {
  if (tid) kerjaTugas = tid;
  el("tirai-kerja").hidden = false;
  el("tirai").classList.add("tampil");
  gambarKerja();
  if (jamKerja) clearInterval(jamKerja);
  jamKerja = setInterval(gambarKerja, 2500);
}

function tutupKotakKerja() {
  el("tirai-kerja").hidden = true;
  if (!document.querySelector(".lembar.tampil")) el("tirai").classList.remove("tampil");
  if (jamKerja) { clearInterval(jamKerja); jamKerja = null; }
}

for (const b of document.querySelectorAll("[data-tutup-kerja]")) b.addEventListener("click", tutupKotakKerja);
el("tirai-kerja").addEventListener("click", (ev) => { if (ev.target === el("tirai-kerja")) tutupKotakKerja(); });

/* ------------------------------------------------------------ strip kerja */

/* Kotak kecil di bawah bar yang muncul sendiri selama ada tugas berjalan.
   Sebelumnya satu-satunya cara melihat progres adalah membuka menu alat lalu
   memilih Proses kerja, jadi pekerja yang sedang bekerja tidak terlihat sama
   sekali. Strip ini menanyakannya sendiri ke server dan membuka kotak aktivitas
   di tempat, tanpa pindah halaman. */
let stripJam = null;
let stripData = [];
let stripTanyaTerakhir = 0;

function stripMulai() {
  if (stripJam) return;
  stripJam = setInterval(async () => {
    // jam berjalan tiap detik; isinya ditanya berkala saja
    if (stripData.length) {
      const t = stripData[0];
      const jam = el("strip-jam");
      if (jam) jam.textContent = `${lamaDetik(Math.max(0, Date.now() / 1000 - (t.created || Date.now() / 1000)))} · ${t.id}`;
    }
    const jeda = stripData.length ? 2500 : 6000;
    if (Date.now() - stripTanyaTerakhir < jeda) return;
    stripTanyaTerakhir = Date.now();
    await muatStrip();
  }, 1000);
  muatStrip();
}

async function muatStrip() {
  let d;
  try {
    d = await ambil("/api/tasks/running");
  } catch {
    return; // jaringan sedang putus: biarkan tampilan terakhir
  }
  stripData = d.running || [];
  gambarStrip();
  // Kotak aktivitas yang sedang terbuka ikut disegarkan kalau tugasnya berakhir.
  if (!el("tirai-kerja").hidden && kerjaTugas) {
    const t = stripData.find((x) => x.id === kerjaTugas);
    if (!t && jamKerja) { gambarKerja(); }
  }
}

function lamaDetik(detik) {
  const m = Math.floor(detik / 60);
  const s = Math.round(detik % 60);
  return m ? `${m}m ${String(s).padStart(2, "0")}s` : `${s}s`;
}

function gambarStrip() {
  const kotak = el("strip-kerja");
  if (!kotak) return;
  const ada = stripData.length > 0;
  kotak.hidden = !ada;
  if (!ada) {
    if (!el("tirai-kerja").hidden) tutupKotakKerja();
    return;
  }
  const t = stripData[0];
  el("strip-judul").textContent = stripData.length > 1 ? `${stripData.length} tugas berjalan` : "sedang dikerjakan";

  // Pekerja mana yang sedang mengerjakan: ini yang tadi tidak terlihat.
  const wadah = el("strip-pekerja");
  wadah.replaceChildren();
  for (const p of t.pekerja) {
    const b = buat("span", "p" + (p.aktif ? "" : " selesai"), p.label);
    if (p.text) b.title = p.text;
    wadah.appendChild(b);
  }
  if (!t.pekerja.length) wadah.appendChild(buat("span", "p selesai", "menyiapkan"));

  const mulai = t.created || Date.now() / 1000;
  el("strip-jam").textContent = `${lamaDetik(Math.max(0, Date.now() / 1000 - mulai))} · ${t.id}`;
  el("strip-dot").classList.toggle("istirahat", !t.pekerja.some((p) => p.aktif));
}

async function hentikanTugas(tid, tombol) {
  if (tombol) { tombol.disabled = true; tombol.textContent = "menghentikan…"; }
  try {
    await kirim(`/api/tasks/${tid}/hentikan`, {});
    pesanSingkat("Tugas dihentikan.");
    if (keadaan.tugasJalan === tid) keadaan.tugasJalan = null;
    clearInterval(jamPantau);
    ticker(false);
    await muatStrip();
    if (keadaan.sesi) bukaSesiRingan(keadaan.sesi);
    if (kerjaTugas === tid) gambarKerja();
  } catch (e) {
    pesanSingkat("Tidak bisa menghentikan: " + e.message, true);
    if (tombol) { tombol.disabled = false; tombol.textContent = "hentikan tugas ini"; }
  }
}

/* Satu ketukan di strip membuka kotak aktivitas pekerja: pekerjaan yang sedang
   berjalan pindah ke situ, jadi menu garis tiga tidak lagi memuatnya. */
el("strip-kepala").addEventListener("click", () => {
  const t = stripData[0];
  if (!t) return;
  bukaKotakKerja(t.id);
});

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
      const status = t.status === "done" ? "selesai" : t.status === "failed" || t.status === "error" ? "gagal" : t.status === "cancelled" ? "batal" : "jalan";
      const jawab = t.answer || "";
      if (p && (p.status !== status || (jawab && p.teks !== jawab))) {
        p.status = status;
        p.teks = jawab || p.teks;
        p.ts = t.finished || p.ts;
        p.tes = (t.test || {}).ok;
        p.pekerja = (t.workers || [])[0];
        // Sumber hanya muncul kalau jawabannya sudah ada: menampilkannya di
        // tengah tugas berarti chip untuk jawaban yang belum selesai.
        if (t.sources) p.sumber = t.sources;
        gambarSemuaPesan();
      }
      // Lambang sumber yang sedang dibaca, selagi pekerja masih bekerja.
      if (p && status === "jalan") {
        const sementara = sumberSementaraDari(d.events, 4, t.prompt || p.teks || "");
        if (JSON.stringify(sementara) !== JSON.stringify(p.sumberSementara || [])) {
          p.sumberSementara = sementara;
          gambarSemuaPesan();
        }
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
    el("model-sekarang").textContent = d.current || "belum dipilih";
    // Keterangan kemampuan model diambil dari daftar model yang baru saja
    // dimuat, bukan dari /api/state: endpoint itu ikut mengirim seluruh daftar
    // id model (ratusan kB), dan memanggilnya lagi hanya untuk satu baris teks
    // membuat panel model terasa berat.
    const caps = ((d.models || []).find((m) => m.id === d.current) || {}).caps || {};
    el("model-sekarang").textContent = `${d.current || "belum dipilih"}  |  ${caps.vision ? "bisa melihat gambar" : "tidak bisa melihat gambar"}  |  ${caps.search ? "bisa mencari sendiri" : "tidak mencari sendiri"}`;
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
  if (!wadah) return;
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
    // Pengguna biasa tidak boleh mengubah setelan pekerja; barisnya tetap
    // menampilkan status supaya tahu CLI mana yang siap.
    if (keadaan.peran === "admin") {
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
    }
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
    // Setelannya hanya dikirim ke admin; pengguna biasa melihat statusnya saja.
    const cfg = d.cfg || {};
    const admin = keadaan.peran === "admin";
    const daftar = (d.workers || []).map((w) => ({
      ...w,
      model: (cfg[w.key] || {}).model || "",
      enabled: (cfg[w.key] || {}).enabled !== false,
    }));
    gambarPekerja(daftar);
  } catch (e) {
    const w = el("daftar-pekerja");
    // Daftar pekerja sekarang tinggal di halaman Pekerja. Kalau panelnya tidak
    // ada di DOM (halaman lain sedang terbuka), galatnya cukup dilaporkan lewat
    // pesan singkat -- bukan berhenti karena elemennya tidak ditemukan.
    if (w) w.replaceChildren(buat("p", "kosong", "Daftar pekerja tidak bisa dimuat: " + e.message));
    else pesanSingkat("Daftar pekerja tidak bisa dimuat: " + e.message, true);
  }
}

function pada2(id, kejadian, fn) {
  const n = el(id);
  if (n) n.addEventListener(kejadian, fn);
}

pada2("periksa-pekerja", "click", async (ev) => {
  ev.target.disabled = true;
  for (const w of keadaan.pekerja) {
    try { await kirim(`/api/workers/${w.key}/probe`, {}); } catch {}
  }
  await muatPekerja();
  ev.target.disabled = false;
  pesanSingkat("Pemeriksaan pekerja selesai.");
});

pada2("terapkan-pekerja", "click", async () => {
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
    // Kemajuan pemasangan tampil di sini, tepat di bawah tombolnya. Kotaknya
    // kosong disembunyikan sampai ada baris, jadi halaman tidak memuat tulisan
    // pengantar yang tidak berguna.
    const catatan = buat("pre", "isi-berkas");
    catatan.id = "log-pasang";
    catatan.hidden = true;
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

/* Daftar berkas dipotong, bukan ditampilkan seluruhnya.
   Terukur di mesin ini: folder kerja berisi 108 berkas, dan daftar penuh
   setinggi 4320px di dalam panel yang hanya 784px. Gulirannya tetap ada, tapi
   menelusuri 108 baris untuk mencari satu berkas tidak masuk akal di layar HP.
   Yang ditampilkan 60 baris pertama plus satu baris keterangan berapa yang
   disembunyikan; pencarian berkas dilakukan lewat kotak cari di bawahnya. */
const BATAS_BARIS_BERKAS = 60;

let saringBerkas = "";

function gambarPohonBerkas(entries) {
  const wadah = el("pohon-berkas");
  wadah.replaceChildren();
  const kata = saringBerkas.trim().toLowerCase();
  const cocok = kata ? entries.filter((b) => b.path.toLowerCase().includes(kata)) : entries;
  if (!cocok.length) {
    wadah.appendChild(buat("p", "kosong", kata ? "Tidak ada berkas yang cocok." : "Folder kerja masih kosong."));
    return;
  }
  const tampil = cocok.slice(0, BATAS_BARIS_BERKAS);
  for (const b of tampil) {
    const tombol = buat("button", null, `${b.type === "dir" ? "[folder] " : ""}${b.path}${b.size ? "  " + b.size + " b" : ""}`);
    tombol.type = "button";
    if (b.type === "dir") tombol.disabled = true;
    else tombol.addEventListener("click", () => bukaBerkas(b.path));
    wadah.appendChild(tombol);
  }
  if (cocok.length > tampil.length) {
    wadah.appendChild(buat("p", "kosong",
      `Menampilkan ${tampil.length} dari ${cocok.length} berkas. Pakai kotak cari untuk menyaring.`));
  }
}

async function muatBerkas() {
  try {
    const d = await ambil("/api/project/tree");
    el("dir-kerja").textContent = "Folder kerja: " + d.dir;
    keadaan.berkas = d.entries || [];
    gambarPohonBerkas(keadaan.berkas);
  } catch (e) {
    el("pohon-berkas").replaceChildren(buat("p", "kosong", "Daftar berkas tidak bisa dimuat: " + e.message));
  }
}

el("cari-berkas").addEventListener("input", (ev) => {
  saringBerkas = ev.target.value;
  gambarPohonBerkas(keadaan.berkas || []);
});

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

/* --------------------------------------------------- panel: pasang dari URL */

/* Satu halaman untuk semua ekosistem: plugin Claude, skill/plugin Codex,
   skill/plugin Hermes, dan server MCP. Alurnya selalu dua langkah: pratinjau
   dulu (tidak menulis apa pun), baru pasang. Yang tidak kompatibel muncul di
   pratinjau dengan status dan alasannya, bukan menghilang diam-diam. */

const CAP_JENIS_LABEL = {
  skill: "Skill", agent: "Agen", command: "Perintah",
  hook: "Hook", mcp: "MCP", rule: "Aturan",
};
const CAP_STATUS_LABEL = {
  supported: { teks: "dipakai langsung", kelas: "ada" },
  converted: { teks: "diterjemahkan", kelas: "tidak" },
  skipped: { teks: "dilewati", kelas: "tidak" },
  requires: { teks: "perlu alat lain", kelas: "tidak" },
};

function gambarPratinjau(d) {
  const wadah = el("cap-hasil");
  wadah.replaceChildren();
  if (!d || !d.ok) {
    wadah.appendChild(buat("p", "kosong", (d && d.error) || "Pratinjau gagal."));
    return;
  }

  const kepala = buat("div", "baris-data");
  const atas = buat("div", "atas");
  atas.appendChild(buat("span", "nama", d.nama || "tanpa nama"));
  atas.appendChild(buat("span", "tanda-cap ada", d.jenis_paket || "?"));
  if (d.versi) atas.appendChild(buat("span", "tanda-cap tidak", d.versi));
  kepala.appendChild(atas);
  if (d.keterangan) kepala.appendChild(buat("div", "teks-kecil", d.keterangan));
  const h = d.hitung || {};
  kepala.appendChild(buat("div", "teks-kecil",
    `${h.total || 0} capability: ${h.supported || 0} langsung, ${h.converted || 0} diterjemahkan, `
    + `${h.skipped || 0} dilewati, ${h.requires || 0} perlu alat lain`));
  if (d.deteksi && (d.deteksi.penanda || []).length) {
    kepala.appendChild(buat("div", "teks-kecil", "penanda: " + d.deteksi.penanda.join(", ")));
  }
  for (const c of (d.catatan || [])) {
    kepala.appendChild(buat("div", "teks-kecil", c));
  }
  wadah.appendChild(kepala);

  // Plugin yang ada di dalam repo besar: bisa dipilih satu per satu.
  const dalam = d.plugin_dalam || [];
  if (dalam.length > 1) {
    const k = buat("div", "baris-data");
    k.appendChild(buat("div", "atas", ""));
    k.querySelector(".atas").appendChild(buat("span", "nama", `${dalam.length} plugin di dalam repo ini`));
    k.appendChild(buat("div", "teks-kecil", "pilih satu untuk dipratinjau sendiri"));
    for (const p of dalam) {
      const b = buat("button", "tombol kecil garis", `${p.jenis}: ${p.nama}${p.folder !== "." ? " (" + p.folder + ")" : ""}`);
      b.type = "button";
      b.addEventListener("click", () => {
        el("cap-url").value = d.sumber_url || el("cap-url").value;
        el("cap-sub").value = p.folder;
        pratinjauCapability();
      });
      k.appendChild(b);
    }
    wadah.appendChild(k);
  }

  // Kelompokkan per jenis supaya daftar panjang tetap bisa dibaca.
  const per = {};
  for (const c of (d.capabilities || [])) (per[c.jenis] = per[c.jenis] || []).push(c);
  for (const jenis of ["skill", "agent", "command", "hook", "mcp", "rule"]) {
    const isi = per[jenis];
    if (!isi || !isi.length) continue;
    const blok = buat("div", "baris-data");
    const t = buat("div", "atas");
    t.appendChild(buat("span", "nama", `${CAP_JENIS_LABEL[jenis] || jenis} (${isi.length})`));
    blok.appendChild(t);

    // Untuk skill yang banyak, tampilkan beberapa dulu supaya panel tidak
    // setinggi ratusan baris. Sisanya lewat tombol.
    const batas = 8;
    const tampil = isi.slice(0, batas);
    for (const c of tampil) blok.appendChild(barisCapability(c));
    if (isi.length > batas) {
      const sisa = buat("button", "tombol kecil garis", `tampilkan ${isi.length - batas} lainnya`);
      sisa.type = "button";
      sisa.addEventListener("click", () => {
        for (const c of isi.slice(batas)) blok.insertBefore(barisCapability(c), sisa);
        sisa.remove();
      });
      blok.appendChild(sisa);
    }
    wadah.appendChild(blok);
  }

  // Tombol pasang: jenis yang punya isi bisa dipilih, default semuanya.
  const ada = Object.keys(per).filter((k) => per[k].some((c) => c.status === "supported" || c.status === "converted"));
  if (!ada.length) {
    wadah.appendChild(buat("p", "catatan", "Tidak ada yang bisa dipasang dari paket ini."));
    return;
  }
  const pilih = buat("div", "kelompok");
  const kotak = {};
  for (const jenis of ada) {
    const l = document.createElement("label");
    l.className = "teks-kecil";
    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.checked = true;
    cb.dataset.jenis = jenis;
    kotak[jenis] = cb;
    l.append(cb, document.createTextNode(" " + (CAP_JENIS_LABEL[jenis] || jenis)));
    pilih.appendChild(l);
  }
  wadah.appendChild(pilih);

  const b = buat("button", "tombol penuh", "Pasang ke pekerja yang kompatibel");
  b.type = "button";
  b.addEventListener("click", async () => {
    const jenis = Object.values(kotak).filter((c) => c.checked).map((c) => c.dataset.jenis);
    if (!jenis.length) { pesanSingkat("Pilih minimal satu jenis.", true); return; }
    b.disabled = true;
    b.textContent = "memasang";
    try {
      const r = await kirim("/api/capability/pasang", {
        url: el("cap-url").value.trim(),
        sub: el("cap-sub").value.trim(),
        pilih: jenis,
      });
      pesanSingkat("Pemasangan berjalan. Lihat Catatan kejadian untuk hasilnya.");
      await pantauJob(r.job);
      await muatCapability();
    } catch (e) {
      pesanSingkat("Gagal memasang: " + e.message, true);
    } finally {
      b.disabled = false;
      b.textContent = "Pasang ke pekerja yang kompatibel";
    }
  });
  wadah.appendChild(b);
}

function barisCapability(c) {
  const baris = buat("div", "baris-data");
  const atas = buat("div", "atas");
  atas.appendChild(buat("span", "nama", c.nama));
  const st = CAP_STATUS_LABEL[c.status] || { teks: c.status, kelas: "tidak" };
  atas.appendChild(buat("span", "tanda-cap " + st.kelas, st.teks));
  baris.appendChild(atas);
  if (c.keterangan) baris.appendChild(buat("div", "teks-kecil", c.keterangan));
  if (c.pekerja && c.pekerja.length) {
    baris.appendChild(buat("div", "teks-kecil", "pekerja: " + c.pekerja.join(", ")));
  }
  if (c.alasan) baris.appendChild(buat("div", "teks-kecil", c.alasan));
  return baris;
}

async function pratinjauCapability() {
  const url = el("cap-url").value.trim();
  if (!url) { pesanSingkat("Isi tautan atau jalur paket dulu.", true); return; }
  el("cap-status").textContent = "mengunduh dan membaca...";
  el("cap-hasil").replaceChildren();
  el("cap-pratinjau").disabled = true;
  try {
    const d = await kirim("/api/capability/pratinjau", { url, sub: el("cap-sub").value.trim() });
    el("cap-status").textContent = "";
    gambarPratinjau(d);
  } catch (e) {
    el("cap-status").textContent = "";
    el("cap-hasil").replaceChildren(buat("p", "kosong", "Pratinjau gagal: " + e.message));
  } finally {
    el("cap-pratinjau").disabled = false;
  }
}

async function muatCapability() {
  el("cap-pratinjau").disabled = false;
  try {
    // GET memakai `ambil`, bukan `kirim`: fetch menolak permintaan GET yang
    // membawa badan, jadi daftarnya selalu tampak gagal dimuat.
    const d = await ambil("/api/capability");
    const wadah = el("cap-terpasang");
    wadah.replaceChildren();
    if (!d.terpasang || !d.terpasang.length) {
      wadah.appendChild(buat("p", "kosong", "Belum ada paket yang dipasang dari sini."));
      return;
    }
    for (const p of d.terpasang) {
      const baris = buat("div", "baris-data");
      const atas = buat("div", "atas");
      atas.appendChild(buat("span", "nama", p.nama));
      atas.appendChild(buat("span", "tanda-cap ada", p.jenis_paket || "?"));
      if (!p.ada) atas.appendChild(buat("span", "tanda-cap tidak", "folder hilang"));
      baris.appendChild(atas);
      const h = p.hitung || {};
      baris.appendChild(buat("div", "teks-kecil",
        `${h.total || 0} capability: ${h.supported || 0} langsung, ${h.converted || 0} diterjemahkan, `
        + `${h.skipped || 0} dilewati, ${h.requires || 0} perlu alat lain`));
      if (p.url) baris.appendChild(buat("div", "teks-kecil", p.url));
      const b = buat("button", "tombol kecil garis", "lepas tautan");
      b.type = "button";
      b.addEventListener("click", async () => {
        b.disabled = true;
        try {
          const r = await kirim(`/api/capability/${encodeURIComponent(p.nama)}`, {}, "DELETE");
          pesanSingkat(`${p.nama} dilepas (${r.tautan_dilepas || 0} tautan).`);
          await muatCapability();
        } catch (e) {
          pesanSingkat("Gagal melepas: " + e.message, true);
        } finally {
          b.disabled = false;
        }
      });
      baris.appendChild(b);
      wadah.appendChild(baris);
    }
  } catch (e) {
    el("cap-terpasang").replaceChildren(buat("p", "kosong", "Daftar tidak bisa dimuat: " + e.message));
  }
}

el("cap-pratinjau").addEventListener("click", () => pratinjauCapability());
el("cap-muat").addEventListener("click", () => muatCapability());
el("cap-url").addEventListener("keydown", (e) => {
  if (e.key === "Enter") { e.preventDefault(); pratinjauCapability(); }
});

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
  // Kotak log kosong disembunyikan sampai ada barisnya, jadi halaman tidak
  // menampilkan tulisan "belum ada" yang tidak berguna.
  if (kotak) kotak.hidden = false;
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
  const judul = el("judul-paket-skill");
  wadah.replaceChildren();
  // Bagian yang kosong beserta judulnya disembunyikan: halaman skill sudah
  // panjang, dan judul di atas daftar kosong hanya menambah baris yang dibaca
  // tanpa memberi apa pun.
  if (judul) judul.hidden = !paket.length;
  for (const p of paket) {
    const baris = buat("div", "baris-data");
    const atas = buat("div", "atas");
    atas.appendChild(buat("span", "nama", p.nama));
    atas.appendChild(buat("span", "tanda-cap ada", p.jumlah + " skill"));
    baris.appendChild(atas);
    baris.appendChild(buat("div", "teks-kecil", (p.contoh || []).join(", ")));
    // `path` hanya dikirim ke admin. Tanpa pemeriksaan ini, pengguna biasa
    // melihat "186 KB undefined" di tiap baris paket.
    baris.appendChild(buat("div", "teks-kecil", p.path ? p.ukuran + "  " + p.path : p.ukuran));
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

/* -------------------------------------------------- panel: skill terpasang */

/* Halaman baru: semua skill yang sudah terpasang, termasuk yang baru selesai
   dikloning. Dipisah dari halaman pasang supaya daftarnya tidak menumpuk ke
   bawah setiap kali ada paket baru. */
let skillTerpasang = [];

function gambarSkillTerpasang() {
  const wadah = el("daftar-skill-terpasang");
  if (!wadah) return;
  const q = (el("cari-skill-terpasang").value || "").trim().toLowerCase();
  wadah.replaceChildren();
  const cocok = q
    ? skillTerpasang.filter((s) => (s.nama + " " + (s.paket || "") + " " + (s.keterangan || "")).toLowerCase().includes(q))
    : skillTerpasang;
  el("jumlah-skill-terpasang").textContent = q
    ? `${cocok.length} dari ${skillTerpasang.length} skill cocok`
    : `${skillTerpasang.length} skill siap dipakai pekerja.`;
  if (!cocok.length) {
    wadah.appendChild(buat("p", "kosong", skillTerpasang.length ? "Tidak ada yang cocok dengan kata kunci itu." : "Belum ada skill tambahan. Pekerja tetap memakai skill bawaan yang tertera di bawah."));
    return;
  }
  for (const s of cocok) {
    const baris = buat("div", "baris-data");
    const atas = buat("div", "atas");
    atas.appendChild(buat("span", "nama", s.nama));
    if (s.paket) atas.appendChild(buat("span", "tanda-cap ada", s.paket));
    baris.appendChild(atas);
    if (s.keterangan) baris.appendChild(buat("div", "teks-kecil", s.keterangan));
    // `tautan` hanya dikirim ke admin. Kalau tidak ada, barisnya dihilangkan:
    // menulis "belum tertaut ke pekerja" untuk pengguna biasa itu bohong, karena
    // skill itu memang tertaut, hanya daftar foldernya yang tidak dikirim.
    if (s.tautan) {
      baris.appendChild(buat("div", "teks-kecil", (s.tautan || []).join(", ") || "belum tertaut ke pekerja"));
    }
    wadah.appendChild(baris);
  }
}

async function muatSkillTerpasang() {
  try {
    const d = await ambil("/api/skills");
    skillTerpasang = d.daftar || [];
    gambarSkillTerpasang();
  } catch (e) {
    el("daftar-skill-terpasang").replaceChildren(buat("p", "kosong", "Daftar skill tidak bisa dimuat: " + e.message));
  }
}

el("cari-skill-terpasang").addEventListener("input", gambarSkillTerpasang);

async function muatSkill() {
  try {
    const d = await ambil("/api/skills");
    gambarSkill(d.paket || [], d.siap || []);
    skillTerpasang = d.daftar || [];
    gambarSkillTerpasang();
    gambarSkillBawaan(d.bawaan || []);
  } catch (e) {
    el("daftar-skill").replaceChildren(buat("p", "kosong", "Daftar skill tidak bisa dimuat: " + e.message));
  }
}

/* Skill bawaan repo: yang ikut ter-clone bersama AstroZ. Pekerja memakainya
   sendiri, dan tombolnya menautkan ulang kalau folder skill di mesin ini
   terhapus. */
function gambarSkillBawaan(daftar) {
  const wadah = el("daftar-skill-bawaan");
  if (!wadah) return;
  wadah.replaceChildren();
  if (!daftar.length) {
    wadah.appendChild(buat("p", "kosong", "Repo ini tidak membawa folder skills/."));
    return;
  }
  const perlu = daftar.filter((x) => x.perlu).length;
  const baris = buat("div", "baris-data");
  baris.appendChild(buat("div", "nama", daftar.length + " paket bawaan, " + perlu + " belum tertaut"));
  baris.appendChild(buat("div", "teks-kecil", daftar.map((x) => x.nama + " (" + x.jumlah + ")").join(", ")));
  const b = buat("button", "tombol kecil" + (perlu ? "" : " garis"), perlu ? "Pasang sekarang" : "Tautkan ulang");
  b.type = "button";
  b.addEventListener("click", async () => {
    b.disabled = true;
    b.textContent = "memasang";
    try {
      const d = await kirim("/api/skills/bawaan", {});
      pesanSingkat((d.paket || []).length + " paket skill bawaan ditautkan.");
      await muatSkill();
    } catch (e) { pesanSingkat("Gagal memasang skill bawaan: " + e.message, true); }
    finally { b.disabled = false; }
  });
  baris.appendChild(b);
  wadah.appendChild(baris);
}

el("pasang-skill").addEventListener("click", async () => {
  const url = el("repo-skill").value.trim();
  if (!url) { pesanSingkat("Isi dulu repo skill-nya.", true); return; }
  el("log-skill").hidden = false;
  el("log-skill").textContent = "mengkloning " + url + " ...";
  try {
    const d = await kirim("/api/skills", { url });
    pesanSingkat("Mengkloning " + url + " ...");
    await pantauJob(d.job, "log-skill");
    el("repo-skill").value = "";
    // Daftar di halaman yang sama langsung disegarkan, jadi hasil clone
    // kelihatan tanpa pindah halaman.
    await muatSkill();
  } catch (e) {
    el("log-skill").textContent = "gagal: " + e.message;
    pesanSingkat("Gagal memasang skill: " + e.message, true);
  }
});

async function muatMarketplace() {
  const wadah = el("daftar-marketplace");
  try {
    const d = await ambil("/api/marketplace");
    wadah.replaceChildren();
    const judul = el("judul-sumber-skill");
    const daftar = d.daftar || [];
    if (judul) judul.hidden = !daftar.length;
    for (const m of daftar) {
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
          await pantauJob(d2.job, "log-skill");
          // Hasilnya muncul di daftar terpasang di atas halaman ini juga.
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

/* ---------------------------------------------------- lambang merek di UI */

/* Lambang GitHub dan Instagram di halaman Pengaturan memakai jalur ikon yang
   sama dengan lambang sumber, jadi tidak ada permintaan ke luar. */
function pasangLambangMerek() {
  for (const s of document.querySelectorAll("[data-merek]")) {
    const kunci = s.dataset.merek;
    const m = (typeof LAMBANG_MEREK !== "undefined" && LAMBANG_MEREK[kunci]) || null;
    if (!m) continue;
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("width", "22");
    svg.setAttribute("height", "22");
    svg.setAttribute("fill", "currentColor");
    svg.setAttribute("aria-hidden", "true");
    const p = document.createElementNS("http://www.w3.org/2000/svg", "path");
    p.setAttribute("d", m.d);
    svg.appendChild(p);
    s.replaceChildren(svg);
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
  pasangLambangMerek();
  pasangIkon();
  // Periksa dulu apakah sudah masuk. Tanpa ini, halaman langsung memanggil
  // belasan endpoint, semuanya dijawab 401, dan yang terlihat hanya pesan galat
  // bertumpuk alih-alih layar masuk.
  const akun = await ambil("/api/saya").catch(() => null);
  if (!akun || !akun.pengguna) {
    tampilkanGerbang(true);
    return;
  }
  keadaan.peran = akun.pengguna.peran || "user";
  keadaan.saya = akun.pengguna.nama || "";
  sembunyikanKhususAdmin();
  // Yang menahan tampilan awal hanya dua hal: daftar percakapan dan model.
  // Sisanya (berkas, catatan, plugin, skill) dimuat di latar belakang, jadi
  // halaman skill yang lambat tidak menahan percakapan muncul.
  await Promise.all([muatSesi(), muatModel()]);
  // Percakapan kosong yang belum pernah dipakai dibuang supaya riwayat tidak
  // penuh baris "Percakapan baru".
  await kirim("/api/sessions/kosong", {}, "DELETE").catch(() => null);
  await muatSesi();
  sambungKejadian();
  // Strip kerja: muncul sendiri selama ada tugas berjalan, tanpa membuka menu.
  stripMulai();
  const d = await ambil("/api/state").catch(() => null);
  if (d) gambarAlatBantu(d.gateway || {});
  const daftar = await ambil("/api/sessions").catch(() => ({ sessions: [] }));
  const sesi = (daftar.sessions || [])[0];
  if (sesi) bukaSesi(sesi.id);
  else sesiBaru();
  for (const f of [muatPekerja, muatBerkas, muatGit, () => muatCatatan(false), muatMcp, muatSkill, muatMarketplace, muatPekerjaPasang]) {
    f().catch(() => {});
  }
}

pasangFormMasuk();

/* ------------------------------------------------------------------ terminal */

/* Terminal di UI memakai dua jalur yang berbeda, dan pemisahannya disengaja:

   - Perintah yang hasilnya langsung ditampilkan (git clone, npm install, ls)
     dikirim lewat POST /api/terminal dan dijalankan di shell pengguna yang
     tetap hidup, supaya `cd` dan variabel bertahan antar perintah.
   - Keluaran yang mengalir dibaca lewat SSE /api/terminal/alir, jadi perintah
     panjang terlihat bergerak, bukan diam lalu muncul sekaligus.

   Layar dibatasi jumlah barisnya: `npm install` bisa mengeluarkan ribuan baris
   dan tanpa batas itu halaman akan melambat. */

const terminalKeadaan = { tersedia: false, prefix: "", mode: "", alat: {}, siap: false };
let terminalAliran = null;
let terminalBaris = 0;
const BATAS_BARIS_TERMINAL = 2000;

function terminalTulis(teks, kelas) {
  const layar = el("terminal-layar");
  if (!layar) return;
  const baris = buat("div", "terminal-baris-teks" + (kelas ? " " + kelas : ""), teks);
  layar.appendChild(baris);
  terminalBaris += 1;
  // Buang dari atas, bukan dari bawah: yang dibaca pengguna adalah yang terbaru.
  while (terminalBaris > BATAS_BARIS_TERMINAL && layar.firstChild) {
    layar.removeChild(layar.firstChild);
    terminalBaris -= 1;
  }
  layar.scrollTop = layar.scrollHeight;
}

function terminalTanda(jalur) {
  const t = el("terminal-tanda");
  if (!t) return;
  // Tanda $ yang mengikuti folder kerja: tanpa ini pengguna tidak tahu di mana
  // perintahnya dijalankan setelah beberapa kali `cd`.
  const pendek = String(jalur || "").split("/").filter(Boolean).slice(-2).join("/");
  t.textContent = pendek ? pendek + " $" : "$";
}

async function muatTerminal() {
  try {
    const d = await ambil("/api/terminal");
    Object.assign(terminalKeadaan, d);
    const alat = Object.entries(d.alat || {}).filter(([, ada]) => ada).map(([n]) => n);
    const kurang = Object.entries(d.alat || {}).filter(([, ada]) => !ada).map(([n]) => n);
    el("terminal-keadaan").textContent = d.tersedia
      ? `Siap. Mode ${d.mode}. Tersedia: ${alat.join(", ")}` +
        (kurang.length ? ` — belum ada: ${kurang.join(", ")}` : "")
      : "Terminal tidak tersedia di lingkungan ini.";
    terminalTanda(d.cwd);
    if (d.tersedia) {
      terminalTulis("Terminal siap. Folder kerja: " + d.cwd, "redup");
      terminalTulis("Coba: git clone https://github.com/git/git.git lalu cd git && ls", "redup");
      sambungTerminal();
    }
    el("terminal-input").disabled = !d.tersedia;
    el("terminal-jalan").disabled = !d.tersedia;
  } catch (e) {
    el("terminal-keadaan").textContent = "Terminal tidak bisa dimuat: " + e.message;
  }
}

function sambungTerminal() {
  if (terminalAliran) return;
  try {
    terminalAliran = new EventSource("/api/terminal/alir");
  } catch {
    return;
  }
  terminalAliran.onmessage = (ev) => {
    let d = {};
    try { d = JSON.parse(ev.data); } catch { return; }
    if (typeof d.baris === "string" && d.baris !== "") terminalTulis(d.baris);
    if (d.cwd) terminalTanda(d.cwd);
  };
  // Kalau sambungan putus (layar tidur, server restart), sambungkan lagi setelah
  // jeda. EventSource sebenarnya sudah mencoba sendiri, tetapi tidak saat
  // server mati total, dan itu justru kasus yang sering terjadi di HP.
  terminalAliran.onerror = () => {
    terminalAliran.close();
    terminalAliran = null;
    setTimeout(() => { if (!el("alat-terminal").hidden || !el("halaman").hidden) sambungTerminal(); }, 3000);
  };
}

async function terminalJalankanPerintah(perintah) {
  if (!perintah.trim()) return;
  terminalTulis("$ " + perintah, "perintah");
  const tombol = el("terminal-jalan");
  tombol.disabled = true;
  tombol.textContent = "Berjalan…";
  try {
    const d = await kirim("/api/terminal", { perintah, timeout: 600 });
    if (d.cwd) terminalTanda(d.cwd);
    // Keluaran biasanya sudah tampil lewat aliran SSE; cetak hanya kalau aliran
    // tidak menyampaikannya, supaya tidak ada baris kembar.
    const teks = String(d.keluaran || "");
    if (teks && !terminalAliran) {
      for (const b of teks.replace(/\n$/, "").split("\n")) terminalTulis(b);
    }
    if (!d.ok) {
      terminalTulis(`[selesai dengan kode ${d.kode}${d.error ? ": " + d.error : ""}]`, "galat");
    }
  } catch (e) {
    terminalTulis("gagal: " + e.message, "galat");
  } finally {
    tombol.disabled = false;
    tombol.textContent = "Jalankan";
    el("terminal-input").focus();
  }
}

/* Pemasangan penangan di bawah ini dijaga: kalau HTML yang dimuat masih versi
   lama (cache browser), elemennya belum ada dan tanpa penjagaan satu galat akan
   menghentikan sisa skrip. */
function pada(id, kejadian, fn) {
  const n = el(id);
  if (n) n.addEventListener(kejadian, fn);
}

pada("terminal-form", "submit", (ev) => {
  ev.preventDefault();
  const inp = el("terminal-input");
  const p = inp.value;
  inp.value = "";
  terminalJalankanPerintah(p);
});

pada("terminal-bersih", "click", () => {
  el("terminal-layar").replaceChildren();
  terminalBaris = 0;
  kirim("/api/terminal/bersihkan", {}).catch(() => {});
});

pada("terminal-stop", "click", async () => {
  await kirim("/api/terminal/hentikan", {}).catch(() => {});
  terminalTulis("[shell dihentikan. Perintah berikutnya menyalakannya lagi.]", "redup");
});

pada("terminal-bantuan", "click", async () => {
  const d = await kirim("/api/terminal", { perintah: "astroz --help", timeout: 60 }).catch(() => null);
  if (d && d.keluaran) {
    for (const b of String(d.keluaran).replace(/\n$/, "").split("\n")) terminalTulis(b, "bantuan");
  } else {
    terminalTulis("Perintah astroz tidak tersedia di lingkungan ini.", "redup");
  }
});

// Pencarian model yang lebih lengkap ada di lembar bawah; tombol ini yang
// menghubungkan panel model dengan lembar itu, supaya tidak ada dua tempat
// pencarian yang harus diisi terpisah.
pada("model-pilih-lembar", "click", () => { bukaLembar("lembar-model"); muatModelLembar(); });

mulai();
