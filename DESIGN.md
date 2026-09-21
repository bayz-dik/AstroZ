# Acuan desain AstroZ: ChatGPT "graphite ink on paper"

Arah MindStudio DIGANTI 21 Sep 2026. Acuan aktif sekarang: spesifikasi ChatGPT
yang diukur pihak lain dan diberikan sebagai berkas (4 berkas di
`design-systems/chatgpt/` — DESIGN.md, tokens.json, theme.css, variables.css;
salinan asli di /mnt/sdcard/Download/GPT/).

Baca `design-systems/chatgpt/DESIGN.md` untuk aturan lengkapnya. Ringkasan
yang paling menentukan (semuanya sudah dipatuhi `web/app.css`):

- Akromatik total: sidebar #f9f9f9, kanvas #ffffff, tinta grafit #0d0d0d.
  Tidak ada warna kedua. Makna dibawa bobot (600/500/400), tonal, dan garis.
- Huruf SISTEM (-apple-system/system-ui/Segoe UI/Roboto). Nol webfont —
  fonts.css tidak lagi dimuat oleh index.html.
- Radius: 10px (tombol/kartu/isian/nav), 16px (gelembung/links), pil hanya
  untuk chip. Tidak ada teks >24px; 24px/600 adalah tier display tunggal.
- Elevasi: garis rambut 1px rgba(0,0,0,0.10), BUKAN drop shadow. Flat.
- Hover: selubung #0000000d, bukan perubahan warna. Scrim: #00000080.
- Spasi: elemen 6px, bagian 24px, kartu 16px. Kepala TIDAK blur.

Dua nilai yang disesuaikan dari spesifikasi demi kontras (pola yang sama
dengan putaran MindStudio: ukur, ganti yang gagal, tulis alasannya):

- `--tinta-meta` terang: #8f8f8f (Hollow, 3.5:1) -> #6b6b6b (5.06 di #f9f9f9)
- `--tinta-meta` gelap: #8f8f8f (4.6) -> #ababab (4.95 di permukaan #2f2f2f)

Hasil audit kontras seluruh elemen berteks di browser (CDP), 412px, semua
bagian menu: 0 gagal di tema terang dan gelap (ambang WCAG 4.5, teks besar 3.0).
