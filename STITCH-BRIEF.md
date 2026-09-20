# BRIEF DESAIN UI WEB ASTROZ untuk Google Stitch
# ============================================================
# Target: mendesain ulang tampilan web app "AstroZ" agar identik
# dengan gaya MindStudio (mindstudio.ai). Semua angka di bawah
# DIUKUR dari situs hidup (computed style, 20 Sep 2026), bukan
# perkiraan. Ikuti angka ini apa adanya; jangan mengarang nilai
# baru. Keluaran yang diharapkan: desain UI aplikasi chat
# (bukan landing page), mobile-first, plus versi tablet/desktop.

## 1. IDENTITAS PRODUK
- Nama: AstroZ. Lambang: bintang empat/kilau sederhana (SVG).
- Fungsi: orkestrator AI coding. Satu kolom chat tempat pengguna
  menulis perintah, dan 4 "pekerja" AI (claude, codex, opencode,
  omp) mengerjakannya bersama. Ada panel berkas, catatan kejadian,
  pilih model, riwayat percakapan.
- Bahasa antarmuka: INDONESIA. Semua label yang kamu gambar wajib
  bahasa Indonesia (lihat daftar label di bagian 9).
- Perangkat utama: HP Android (WebView, lebar 412px). Desktop
  adalah tampilan kedua (>=1280px chat + panel samping).
- Karakter: alat kerja yang tenang. Bersih, terang, banyak napas,
  TANPA warna hangat, TANPA gradien, TANPA ilustrasi, TANPA
  glassmorphism selain blur pada kepala halaman.

## 2. TEMA WARNA (diukur, dipakai persis)
Netral (tulang punggung):
- neutral-50  #FAFAFA  latar halaman
- neutral-100 #F0F0F0  permukaan lembut, blok kode, latar chat pengguna
- neutral-200 #E0E0E0  SEMUA garis (border kartu, pemisah, header)
- neutral-300 #C3C3C3  garis isian (input) dan tombol sekunder
- neutral-400 #A0A0A0  teks nonaktif
- neutral-500 #787878  teks meta (waktu, keterangan kecil)
- neutral-600 #585858  teks lembut, item menu
- neutral-700 #404040  teks kuat sekunder
- neutral-800 #282828  garis di latar gelap
- neutral-900 #1A1A1A  permukaan gelap
- neutral-950 #060606  teks utama

Biru brand (SATU-SATUNYA aksen; tidak ada warna kedua):
- brand-50  #E6F0FF  latar pilihan lembut
- brand-500 #0069FF  tombol utama, aksen, fokus
- brand-600 #0055CC  hover tombol utama, teks tautan aksen
- brand-300 #4D9CFF  aksen di tema gelap

Status (dipakai hemat, hanya badge/ikon):
- selesai #1B7A54 (hijau tua, aman kontras; jangan pakai #24A270)
- jalan   #A16207 (kuning tua, aman kontras)
- galat   #C81E1E (merah)

Tema gelap (dibangun dari skala netral yang sama, bukan warna lain):
- latar #060606, permukaan #1A1A1A, permukaan lembut #282828,
  garis #404040, teks #FAFAFA, teks lembut #A0A0A0, meta #909090,
  aksen #4D9CFF, tombol utama tetap #0069FF dengan teks putih.

Aturan warna:
- Semua garis #E0E0E0, tanpa nada hangat (jangan krem/ivory).
- Kedalaman = garis 1px + bayangan SANGAT tipis, bukan bayangan tebal.
- Bayangan tipis: 0 1px 3px 0 rgba(0,0,0,.10), 0 1px 2px -1px rgba(0,0,0,.10)
- Bayangan mengambang (menu/lembar): 0 10px 15px -3px rgba(0,0,0,.10),
  0 4px 6px -4px rgba(0,0,0,.10)

## 3. TIPOGRAFI
- SATU keluarga huruf untuk SEMUA teks termasuk judul: Inter.
  Tidak ada serif, tidak ada font display kedua. Ini yang paling
  menentukan rasa MindStudio; memakai font judul lain = gagal.
- Kode/angka/waktu: JetBrains Mono.
- Bobot: 400 teks, 500 tombol/nav aktif, 600 judul. Tidak ada 700+.
- Judul selalu rapat (letter-spacing negatif).

Skala (desktop / versi HP):
- Display sapaan (h1 hero): 60px / 22px, w600, ls -0.025em, lh 1.08
- Judul panel (h2): 36px di landing; di dalam app cukup 17-20px,
  w600, ls -0.01em
- Body: 16px/1.6 w400
- Body besar (subjudul sapaan): 18px/1.6, warna #585858
- Body kecil: 14px/1.5 (item menu, tombol kecil, meta)
- Caption/meta: 12px, warna #787878 (di HP aman karena dipakai
  di atas putih; tetap >= #6B6B6B kalau ragu)

## 4. BENTUK & SPASI
- Radius: tombol/kartu/isian/menu 12px. Pil/checkbox 9999px.
  Radius kecil (chip kecil) 8px. Jangan pakai radius 0 atau 4px
  untuk komponen besar.
- Jarak dasar 4px. Padding section landing 96px; di dalam app
  cukup 16-24px.
- Lebar isi maksimum 1152px, padding samping 24px.
- Tinggi kepala halaman 54-56px.
- Target sentuh minimum 44px di layar sempit.
- Gerak: transisi warna/latar 150-200ms cubic-bezier(.4,0,.2,1).
  Tidak ada animasi hias. Satu-satunya animasi: titik "sedang
  bekerja" berdenyut (pulse 2s).

## 5. KOMPONEN (nilai persis)
- Kepala halaman (header): sticky, latar rgba(250,250,250,.8) +
  backdrop-blur 16px, garis bawah 1px #E0E0E0, tinggi 54px.
  Isi: lambang bintang + tulisan "AstroZ" kiri (tinggi 17-20px);
  di kanan: ikon pencarian (lingkaran+garis) dan titik tiga.
- Tombol utama: latar #0069FF, teks #FFFFFF, radius 12px,
  padding 12px 24px, font 16px/500, hover #0055CC.
- Tombol sekunder: latar PUTIH #FFFFFF, teks #060606, garis 1px
  #C3C3C3, radius 12px, padding 12px 24px, font 16px/400.
  BUKAN latar abu-abu.
- Tombol kecil: padding 8px 14px, font 14px, tinggi min 36px.
- Isian teks: latar putih, garis 1px #C3C3C3, radius 12px,
  padding 9px 12px, tinggi min 40px, teks 16px.
- Kartu: latar putih, garis 1px #E0E0E0, radius 12px, padding 24px.
- Menu turun/lembar samping: latar putih, garis 1px #E0E0E0,
  radius 12px, padding 4px 0, item 8px 16px 14px/400 warna #585858,
  hover cukup berubah warna jadi #060606 (tanpa latar abu), item
  aktif #060606 dengan bobot 500. Bayangan mengambang.
- Kepala lembar: latar putih dengan garis bawahnya sendiri
  (bukan menyatu dengan latar lembar).
- Checkbox/pil status: radius penuh, latar #F0F0F0 nonaktif,
  #0069FF saat aktif.
- Badge status: teks 12px, pil penuh, latar lembut (hijau #E9F9F2
  + teks #1B7A54; jalan #FEF3C7 + teks #A16207; galat #FEE2E2 +
  teks #C81E1E).

## 6. LAYAR-LAYAR YANG HARUS DIDESAIN (dalam urutan prioritas)
1. LAYAR MASUK (gerbang)
   Latar #FAFAFA penuh. Di tengah satu kartu: latar putih, garis
   #E0E0E0, radius 12px, padding 24px, lebar maksimum 380px.
   Isi dari atas ke bawah: lambang bintang AstroZ (48px), judul
   "Masuk AstroZ" (20px/600/rapat), satu kalimat catatan kecil
   #585858, satu isian sandi (type password, placeholder "sandi"),
   satu tombol utama penuh "Masuk", satu baris pesan galat kecil
   (muncul saat sandi salah). Tanpa pendaftaran, tanpa tab, satu
   cara masuk saja.
2. CHAT KOSONG (layar awal setelah masuk) - LAYAR PALING PENTING
   Kepala halaman seperti spesifikasi. Di tengah halaman (teks
   rata tengah): sapaan besar sesuai waktu: "Selamat pagi/siang/
   sore/malam" (60px desktop, 22px HP, w600, rapat), di bawahnya
   satu kalimat bantu 18px #585858: "Siap mengerjakan. Tulis
   perintah di kotak bawah." Kotak ketik menempel di dasar layar
   (jarak 12px dari tepi): satu wadah putih bergaris #C3C3C3
   radius 12px berisi textarea 16px placeholder "Mengobrol dengan
   AstroZ..." dan di bawahnya satu baris kontrol: tombol "+" bulat
   bergaris, pil model (nama model + ikon), pilihan ukuran "otomatis"
   (sembunyi di HP), tombol kirim bulat biru #0069FF dengan panah
   ke atas.
3. CHAT AKTIF (percakapan berjalan)
   Alur pesan satu kolom. Pesan pengguna: gelembung latar #F0F0F0,
   radius 12px, padding 12px 16px, lebar mengikuti isi, rata kanan,
   label "Kamu" 12px #787878 di atasnya. Jawaban AstroZ: TANPA
   gelembung, teks biasa #060606 16px di atas latar halaman, label
   "AstroZ" di atasnya. Di bawah jawaban ada baris "skrip" ringkas
   (teks kecil 13px mono, warna #585858) merangkum langkah kerja.
   Saat pekerja berjalan: tampil strip tipis di bawah kepala (44px)
   berisi titik biru berdenyut + teks "sedang bekerja" + chip nama
   pekerja (pil kecil bergaris) + timer mono. Badge "selesai" hijau
   di pesan yang tuntas, dengan waktu mono 12px.
4. MENU ALAT (lembar samping dari kiri, mobile; panel kiri di desktop)
   Lembar 280px, latar #FAFAFA, radius 12px di sisi dalam, bayangan
   mengambang. Kepala putih bergaris: lambang + judul "Menu" + tombol
   tutup X. Daftar item (ikon 22px + label 14px #585858): Riwayat
   percakapan, Skill, Plugin MCP, Pasang dari URL, Pekerja, Berkas
   dan tes, Catatan kejadian, Model.
5. RIWAYAT PERCAKAPAN
   Daftar baris satu percakapan per baris: judul 14px #060606
   terpotong satu baris, tombol titik tiga di kanan (menu: semat,
   ganti nama, hapus). Baris tersemat diberi ikon semat kecil.
   Bagian atas ada tombol "Baru" (tombol utama biru kecil).
6. PANEL BERKAS / CATATAN / MODEL (kanan di desktop, lembar di HP)
   Panel judul 17px/600 + kartu-kartu isi. Berkas: kotak cari
   (isian standar, placeholder "cari nama berkas atau folder"),
   daftar berkas ber-pohon dengan nama mono 13px dan ukuran mono
   12px #787878, maksimum 60 baris. Catatan: daftar kejadian satu
   baris per kejadian dengan titik warna status. Model: daftar
   model dengan nama mono + badge "hidup" hijau, dan tombol
   "Terapkan ke semua" (tombol utama).
7. PENGATURAN
   Kartu-kartu bertumpuk: "Sandi" (isian sandi baru + tombol kecil
   "Simpan sandi"), "Penyimpanan" (daftar akun + pemakaian), "Tema"
   (dua tombol sekunder: Terang / Gelap), "Pengembang" (dua ikon
   sosial). Setiap kartu: judul 16px/600 + catatan kecil #585858.
8. VERSEL/LEMBAR KERJA (kotak muncul tengah layar)
   Kartu putih 560px, radius 12px, garis + bayangan mengambang,
   kepala putih bergaris berisi judul + tombol X, isi bisa digulir.

## 7. TATA LETAK
- HP (<1000px): satu kolom. Kepala sticky di atas, konten di tengah,
  kotak ketik menempel dasar (jarak 12px). Menu dan panel dibuka
  sebagai lembar geser. Tidak ada gulir horizontal.
- Desktop (>=1280px): kepala full-width; di bawahnya grid dua kolom:
  chat (minmax(0,1fr)) + panel kerja 368px, dipisah garis 1px.
  Kotak ketik tetap menempel dasar kolom chat.
- Konten chat terbatas lebar bacaan ±720px dan di tengah.

## 8. LARANGAN (yang membuat hasil TIDAK mirip)
- Jangan serif untuk judul; jangan font kedua selain Inter+JetBrains Mono.
- Jangan terracotta/oranye/krem; satu-satunya warna aksen adalah
  biru #0069FF.
- Jangan bayangan tebal/neumorphism/glassmorphism (kecuali blur kepala).
- Jangan radius 0 atau sudut lancip pada tombol/kartu.
- Jangan ikon bergaya outline tebal/duotone berwarna-warni; ikon
  garis tipis satu warna (current color).
- Jangan gradien, jangan pola, jangan ilustrasi di dalam app.
- Jangan teks Inggris di label antarmuka.

## 9. LABEL RESMI (bahasa Indonesia, tulis persis)
- Sapaan: "Selamat pagi" / "Selamat siang" / "Selamat sore" /
  "Selamat malam"; sub: "Siap mengerjakan. Tulis perintah di kotak bawah."
- Kotak ketik: placeholder "Mengobrol dengan AstroZ..."
- Tombol kirim (ikon panah atas, aria "Kirim pesan"); tombol "+".
- Ukuran tugas: "otomatis"; ukuran lain: "kecil", "sedang", "besar".
- Menu: "Riwayat percakapan", "Skill", "Plugin MCP", "Pasang dari
  URL", "Pekerja", "Berkas dan tes", "Catatan kejadian", "Model", "Menu".
- Riwayat: "Baru", menu baris: "Ganti nama percakapan", "Sematkan
  percakapan", "Salin percakapan ini", "Lihat proses kerja".
- Strip kerja: "sedang bekerja"; chip pekerja: "claude", "codex",
  "opencode", "omp"; timer format "0:12".
- Status: "selesai", "jalan", "galat", "menunggu", "antre".
- Panel berkas: "Berkas kerja", cari: "cari nama berkas atau folder",
  tombol "Muat ulang".
- Pengaturan: "Sandi", "Sandi baru", "Simpan sandi", "Penyimpanan",
  "Tema", "Terang", "Gelap", "Pengembang".
- Layar masuk: "Masuk AstroZ", catatan "Masukkan sandi untuk masuk.
  Sandi diatur di team.yaml.", placeholder "sandi", tombol "Masuk".
- Lainnya: "Pengaturan", "Tutup", "Baru".

## 10. ACCEPTANCE CHECK (yang akan saya periksa)
1. Semua garis #E0E0E0; tidak ada nada hangat.
2. Inter di semua teks termasuk judul; judul w600 + rapat.
3. Satu aksen biru #0069FF; tombol sekunder putih bergaris, bukan abu.
4. Radius 12px di tombol/kartu/isian.
5. Kepala sticky + blur 16px + garis bawah 1px, tinggi 54px.
6. Item menu 14px #585858, hover berubah warna (bukan latar abu).
7. Pesan pengguna gelembung #F0F0F0; jawaban tanpa gelembung.
8. Tema gelap tersedia dari skala netral yang sama (#060606/#1A1A1A).
9. Mobile 412px tanpa overflow, target sentuh >=44px.
10. Semua label bahasa Indonesia persis seperti bagian 9.
