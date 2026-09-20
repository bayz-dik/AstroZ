#!/usr/bin/env node
/* Cek sintaks JS terhadap versi ECMAScript yang dikenal WebView Android.

   Kenapa ini ada: WebView lama mematikan SELURUH skrip kalau ada satu fitur yang
   tidak dikenal, dan halaman tampil putih tanpa pesan galat. Mengukur dengan
   parser jauh lebih cepat daripada menebak dari gejala.

   Target aman proyek ini: ES2018 (Chrome 63+, Android 8+). Yang menahan versi di
   app.js: `?.` (ES2020), `catch {}` tanpa parameter (ES2019), matchAll (ES2019),
   dan spread objek (ES2018).

   Pakai:
     node tools/cek_es2018.js              # default: web/app.js
     node tools/cek_es2018.js web/app.js web/apa.js

   Keluar dengan kode 1 kalau tidak lolos ES2018.
*/
"use strict";

const fs = require("fs");
const path = require("path");

// acorn dicari di dua tempat: paket Next.js yang ikut di aset (dipakai di HP),
// lalu acorn milik Hermes di mesin ini. Jangan pasang apa pun: dua-duanya ada.
const kandidat = [
  "/usr/local/lib/hermes-agent/node_modules/acorn",
  path.join(__dirname, "..", "router", "node_modules", "acorn"),
];
let acorn = null;
for (const k of kandidat) {
  try {
    acorn = require(k);
    break;
  } catch (e) {
    /* coba berikutnya */
  }
}
if (!acorn) {
  console.error("acorn tidak ditemukan; cek daftar kandidat di skrip ini");
  process.exit(2);
}

const berkas = process.argv.slice(2);
if (berkas.length === 0) berkas.push(path.join(__dirname, "..", "web", "app.js"));

let gagal = false;
for (const f of berkas) {
  const kode = fs.readFileSync(f, "utf8");
  const hasil = [];
  for (const v of [2017, 2018, 2019, 2020]) {
    try {
      acorn.parse(kode, { ecmaVersion: v, sourceType: "script" });
      hasil.push("es" + v + "=OK");
    } catch (e) {
      hasil.push("es" + v + "=" + e.message);
    }
  }
  // Yang menentukan lulus: bisa diurai sebagai ES2018.
  const bisa2018 = hasil.some((h) => h.startsWith("es2018=OK"));
  console.log((bisa2018 ? "LOLOS  " : "GAGAL  ") + f);
  console.log("       " + hasil.join("  |  "));
  if (!bisa2018) gagal = true;
}

process.exit(gagal ? 1 : 0);
