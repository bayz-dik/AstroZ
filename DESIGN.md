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

## SATU PERMUKAAN, TANPA GARIS KOTAK

21 Sep 2026, permintaan pengguna: hapus garis kotak, jadikan satu latar dari
kepala sampai bawah. Yang berlaku sekarang:

- Latar kaca dipasang SEKALI di `.app` (`--kaca-lebar` + `--kilau` + blur).
  Semua bagian di dalamnya tembus: `.bar`, `.ticker`, `.strip-kerja`, `.alur`,
  `.tulis`, `.aktivitas` — `background: transparent`, `border: 0`, `margin: 0`,
  `box-shadow: none`.
- **Tidak ada satu pun garis pemisah horizontal.** Diverifikasi dengan scan
  piksel vertikal penuh di x=200: nol lompatan > 10 tingkat pada kedua tema.
- Kotak isian juga tanpa cincin. Cincin fokus (`--cincin-kuat`) hanya muncul
  saat `:focus-within` — di situ penanda memang dibutuhkan.
- Blur hanya dipasang di `.app` dan di permukaan yang MENGAMBANG di atasnya
  (menu turun, lembar geser, tirai kerja). Memasang `backdrop-filter` di
  elemen tembus di dalam `.app` tidak menghasilkan apa pun (memblur warna yang
  sudah diblur) dan hanya membakar GPU di HP.

**Efek samping yang wajib diingat:** karena satu permukaan, titik TERGELAP
layar dipakai bersama oleh kepala, percakapan, dan kotak tulis. Dua nilai
harus ikut naik agar tetap lolos WCAG 4.5:

- `--kaca-lebar` 0.70 (dari 0.60). Pada 0.60 titik tergelap jatuh ke lum 0.597
  dan teks meta di sana cuma 3.59:1.
- `--tinta-meta` #5e5e5e (dari #656565). Di lum 0.723, #656565 cuma 4.29:1.

Kalau kelak salah satu dinaikkan/diturunkan, UKUR ULANG keduanya bersamaan;
salah satu saja akan diam-diam menembus ambang.

## Penyimpangan yang disengaja dari acuan (atas permintaan pengguna)

Acuan ChatGPT flat dan tanpa kaca. Kaca diperintahkan langsung pengguna, jadi
dipertahankan, tetapi dengan batas yang diukur — bukan ditebak: `--kaca-lebar`
adalah titik paling tembus yang masih lolos 4.5:1 untuk teks meta.

## Gelembung: hanya pesan pengguna

21 Sep 2026: `.pesan.aku` bergelembung (`--gelembung`, hampir pekat, radius
16px, dibatasi 85% lebar); `.pesan.astroz` TIDAK bergelembung sama sekali —
latar transparan, padding 0, tanpa garis. Jawaban AI jatuh langsung di atas
lempeng percakapan seperti teks halaman.

## Hasil ukur (bukan klaim)

CDP, viewport 412x900 DPR 2, piksel dibaca dari screenshot:

Baris kosong (bebas teks), satu permukaan:

| Wilayah | lum terang | meta terang | lum gelap | meta gelap |
|---|---|---|---|---|
| kepala | 0.965..0.991 | 6.27:1 | 0.026..0.037 | 6.00:1 |
| percakapan | 0.871..0.991 | 5.69:1 | 0.019..0.042 | 6.68:1 |
| kotak tulis | 0.922..0.991 | 6.00:1 | 0.015..0.023 | 7.01:1 |

Kontras teks jawaban vs latar lokal: 18.6:1 (terang), 10.1:1 (gelap).
Lompatan piksel vertikal > 10 tingkat: **0** di kedua tema (bukti tidak ada
garis). Luberan mendatar: 0 px pada 320/360/412/768.

## Pitfall yang sudah pernah menggigit

Bentuk logam di `.latar` menentukan apakah kaca terlihat. Pada posisi lama
(`bottom: -18%`, `top: -26%`), pusat ketiga bola jatuh di luar layar bagian
atas dan bawah, sehingga bagian tengah percakapan rata putih dan semua
permukaan di atasnya terbaca menyatu. Setelah dipindah ke dalam layar
(b1 `bottom: 2%`, b2 `top: -8%`, b3 `top: 26%`), lum lempeng turun dari
249-252 ke 229-251. Kalau kaca "tidak terasa", periksa posisi bola dulu.
