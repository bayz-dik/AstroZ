# Arah desain AstroZ

Aturan tampilan sekarang ada di satu tempat:

- `design-systems/mindstudio/DESIGN.md` untuk aturan, alasan, dan cara mengukur
  ulang nilainya dari situs aslinya.
- `web/app.css` blok `:root` dan `[data-tema="gelap"]` untuk nilai tokennya.

Ringkasnya: ruang kerja bersih ala MindStudio (mindstudio.ai). Latar `#FAFAFA`,
permukaan `#FFFFFF`, SEMUA garis `#E0E0E0`, satu aksen biru `#0069FF`, netral
abu hampir tanpa warna, radius 12px untuk tombol/kartu/isian, kepala menempel
dengan blur 16px, dan Inter untuk semua teks TERMASUK judul (bobot 600, rapat
`-0.01em` sampai `-0.02em`). Angka dan kode memakai JetBrains Mono.

Semua nilai itu diukur dari situs hidup lewat computed style di browser, bukan
dari melihat gambar. Cara mengukurnya ada di DESIGN.md bagian atas.

Berkas ini dulu memuat arah cetak Swiss (kertas putih, radius 0, Archivo dan
DM Mono), lalu arah hangat Claude Code (kanvas perkamen, aksen terracotta,
judul serif Fraunces). Keduanya sudah diganti. `design-systems/claude-code/`
masih ada sebagai catatan sejarah, tetapi tidak lagi dipakai UI.
