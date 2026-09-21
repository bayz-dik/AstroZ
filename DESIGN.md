# Acuan desain AstroZ: ChatGPT "graphite ink on paper" + kaca

Arah MindStudio DIGANTI 21 Sep 2026. Acuan aktif: spesifikasi ChatGPT yang
diukur pihak lain dan diberikan sebagai berkas (4 berkas di
`design-systems/chatgpt/` — DESIGN.md, tokens.json, theme.css, variables.css;
salinan asli di /mnt/sdcard/Download/GPT/).

Baca `design-systems/chatgpt/DESIGN.md` untuk aturan lengkapnya. Ringkasan
yang paling menentukan:

- Akromatik total: sidebar #f9f9f9, kanvas #ffffff, tinta grafit #0d0d0d.
  Tidak ada warna kedua. Makna dibawa bobot (600/500/400), tonal, dan garis.
- Huruf SISTEM (-apple-system/system-ui/Segoe UI/Roboto). Nol webfont.
- Radius: 10px (tombol/kartu/isian/nav), 16px (gelembung), pil hanya untuk chip.
  Tidak ada teks >24px; 24px/600 adalah tier display tunggal.
- Hover: selubung #0000000d, bukan perubahan warna. Scrim: #00000080.
- Spasi: elemen 6px, bagian 24px, kartu 16px.

## Penyimpangan yang disengaja dari acuan (atas permintaan pengguna)

Acuan ChatGPT adalah flat, tanpa kaca dan tanpa bayangan. Dua hal ini
diperintahkan langsung oleh pengguna, jadi keduanya dipertahankan, tetapi
dengan batas yang diukur — bukan ditebak:

1. **Kaca (glassmorphism) menyeluruh** sejak 21 Sep 2026. Setiap permukaan
   memakai `backdrop-filter` di atas `.latar` (tiga bentuk logam buram).
   Alpha diturunkan dari pengukuran kontras, bukan dipilih karena cantik:
   `--kaca-lebar` 0.60 terang / 0.62 gelap adalah titik paling tembus yang
   masih lolos WCAG 4.5 untuk teks meta.
2. **Tepi lempeng diberi garis tinta + bayangan tipis.** Ini bukan hiasan:
   di tema terang, kaca terang di atas kertas terang hanya berbeda beberapa
   tingkat terang. Tanpa `--kaca-garis` (tinta 0.20) dan `--kaca-bayang`
   (alpha 0.10), lempeng percakapan, kepala, dan kotak tulis menyatu jadi satu
   bidang putih — keluhan pengguna "warnanya menyatu semua". Di tema gelap
   arahnya dibalik (`--kaca-garis` putih 0.24).

## Gelembung: hanya pesan pengguna

21 Sep 2026: `.pesan.aku` bergelembung (`--gelembung`, hampir pekat, radius
16px, dibatasi 85% lebar); `.pesan.astroz` TIDAK bergelembung sama sekali —
latar transparan, padding 0, tanpa garis. Jawaban AI jatuh langsung di atas
lempeng percakapan seperti teks halaman.

## Hasil ukur (bukan klaim)

CDP, viewport 412x900 DPR 2, piksel dibaca dari screenshot:

| Wilayah | lum terang | meta terang | lum gelap | meta gelap |
|---|---|---|---|---|
| lempeng percakapan | 0.768..0.991 | 4.54:1 | 0.021..0.044 | 6.42:1 |
| kotak tulis | 0.831..0.965 | 4.89:1 | 0.016..0.048 | 6.93:1 |
| kepala | 0.947..0.973 | 5.54:1 | 0.017..0.026 | 6.84:1 |

Kontras teks jawaban vs latar lokal: 18.6:1 (terang), 10.1:1 (gelap).
Pemisahan tepi: garis 1px turun ~60 tingkat terang (203 vs 248 di tepi kiri
lempeng). Luberan mendatar: 0 px pada 320/360/412.

## Pitfall yang sudah pernah menggigit

Bentuk logam di `.latar` menentukan apakah kaca terlihat. Pada posisi lama
(`bottom: -18%`, `top: -26%`), pusat ketiga bola jatuh di luar layar bagian
atas dan bawah, sehingga bagian tengah percakapan rata putih dan semua
permukaan di atasnya terbaca menyatu. Setelah dipindah ke dalam layar
(b1 `bottom: 2%`, b2 `top: -8%`, b3 `top: 26%`), lum lempeng turun dari
249-252 ke 229-251. Kalau kaca "tidak terasa", periksa posisi bola dulu.
