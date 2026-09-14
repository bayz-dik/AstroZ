# Arah desain AstroZ: rumah terracotta ala Claude Code

Berkas ini yang dipakai untuk menilai apakah UI-nya masih melenceng. Kalau ada
yang tidak cocok dengan arah di bawah, itu bug, bukan selera.

Nilai token ada di `design-systems/claude-code/tokens.css`, asal-usulnya di
`design-systems/claude-code/source/evidence.md`.

## Apa ini dan siapa yang pakai

Alat kerja pribadi. Satu orang mengirim perintah, empat CLI koding
mengerjakannya. Dipakai dari HP maupun layar lebar, sebentar-sebentar, sambil
menunggu hasil. Yang dibaca paling sering cuma dua hal: apa yang tadi kuketik,
dan apa hasilnya.

Ini bukan halaman pemasaran, bukan dasbor kartu, bukan panel admin. Tidak ada
yang perlu dijual ke pengunjung.

## Suasana

Ruang kerja hangat seperti meja kayu, bukan konsol biru. Latar tanah hangat,
satu aksen terracotta, teks yang enak dibaca lama. Pekerjaan yang sedang
berjalan ditandai dengan kilau aksen, bukan dengan denyut atau roda berputar.

Yang paling sering salah: menganggap ini dasbor lalu menumpuk kartu. Ini ruang
kerja; yang menumpuk adalah baris teks dan hasil kerja.

## Warna

Dua tema, peran yang sama, nilai berbeda. Tidak pernah `#FFFFFF` sebagai latar
halaman, tidak pernah `#000`.

| Peran | Terang | Gelap |
|---|---|---|
| Latar halaman | `#FAF9F5` | `#262624` |
| Permukaan (kartu, kotak tulis) | `#FFFFFF` | `#30302E` |
| Permukaan hangat (gelembung pemakai) | `#E8E6DC` | `#3E332E` |
| Tinta utama | `#141413` | `#F5F4ED` |
| Tinta kedua | `#3D3D3A` | `#D8D6CF` |
| Tinta lembut | `#5E5D59` | `#B0AEA5` |
| Tinta meta | `#6F6E68` | `#9C9A92` |
| Garis | `#E8E6DC` | `#3E3E3B` |
| Garis kuat (batas kontrol) | `#8E8C84` | `#7C7A73` |
| Aksen latar | `#C96442` | `#D97757` |
| Aksen teks | `#A8492F` | `#E08B6E` |
| Selesai | `#146C2E` | `#69DB7C` |
| Jalan | `#A8492F` | `#FFC107` |
| Gagal | `#B53333` | `#FF6B80` |
| Fokus | `#2563EB` | `#3898EC` |

Aturan pakai:

- Satu aksen. Kalau ada dua hal yang mau ditonjolkan, salah satunya jadi tinta
  biasa. Paling banyak dua pemakaian aksen terlihat per layar.
- Semua netral bernada kuning-coklat. Abu biru dilarang, kecuali cincin fokus.
- Warna keadaan hanya untuk menandai keadaan. Jangan dipakai menghias.
- Biru fokus bukan warna merek; dia ada supaya papan tulis terlihat saat
  dipakai Tab.

## Tipografi

- Judul: Fraunces, bobot 500 saja. Tidak ada 600 atau 700 untuk judul.
- Teks: Inter, bobot 400 dan 500.
- Mesin: JetBrains Mono untuk waktu, nomor entri, jumlah, kode, dan isi berkas.
  Tidak untuk kalimat biasa.
- Ukuran: 11 / 12 / 13 / 15 / 17 / 22 / 28 px. Tidak ada ukuran lain.
- Tinggi baris isi 1.6, judul 1.2. Jarak antar huruf normal, kecuali label
  mesin huruf besar yang diberi 0.06em.
- Panjang baris isi dibatasi 68 huruf supaya enak dibaca di layar lebar.
- Huruf disimpan sendiri di `web/fonts/`. Tidak ada permintaan ke Google Fonts
  saat halaman dibuka.

## Bentuk

Radius 8px (standar), 12px (kontrol: tombol, kotak tulis, input), 16px (wadah
besar). Tidak ada sudut tajam.

Kedalaman memakai cincin `0 0 0 1px`, bukan bayangan jatuh. Bayangan hanya
untuk pesan singkat yang melayang.

Tombol: utama berlatar aksen, kedua berlatar permukaan hangat dengan cincin,
ketiga tanpa latar hanya teks bergaris bawah.

## Susunan

HP: satu kolom. Bar atas berisi tombol menu (garis tiga) di kiri, judul di
tengah kiri, dan ikon percakapan serta ikon titik di kanan. Alur percakapan
punya gulir sendiri, kotak tulis di bawah.

Layar kosong: satu lambang bintang kecil berwarna aksen, satu sapaan serif
mengikuti jam, satu baris keterangan, lalu kotak tulis. Tidak ada kartu
sambutan, tidak ada saran perintah bertumpuk.

Kotak tulis: satu kotak bergaris dengan sudut membulat, teks di dalamnya,
lalu satu baris tombol di bawahnya: tombol bulat `+` (lampiran, plugin, skill),
pil nama model, pemilih ukuran tugas, dan tombol kirim bulat berwarna aksen.
Tidak ada baris kedua di bawahnya.

Chat: pesan pemakai memakai blok berlatar permukaan hangat dengan sudut
membulat, rata kiri. Jawaban AstroZ berupa teks tanpa kotak, dengan garis
pemisah tipis antar pesan. Di bawah jawaban ada satu baris kecil berisi
keadaan (selesai, pekerja, tes) dan ringkasan langkah kerja. Aktivitas kerja
tidak pernah masuk ke chat sebagai kotak terpisah.

Menu alat (tombol garis tiga) memuat: Obrolan, Plugin MCP, Skill dari GitHub,
Berkas dan tes, Catatan kejadian, Model dan pekerja. Satu bagian terlihat pada
satu waktu. Percakapan baru selalu membuat percakapan baru; satu percakapan
tidak menumpuk semua tugas.

Layar lebar 1280px ke atas: tiga kolom dipisah garis, percakapan di kiri, chat
di tengah, panel pekerjaan di kanan. 1000 sampai 1279px: dua kolom, panel
pekerjaan pindah jadi lembar geser. Di bawah 1000px semuanya lembar geser.

Tinggi sasaran sentuh minimal 44px di layar sempit. Tidak ada gulir mendatar
di lebar 375px.

## Gerak

Minimal. Hanya tanggapan sentuh, satu garis kilau saat tugas berjalan, dan
penanda kecil di gelembung yang sedang dikerjakan. Semuanya berhenti begitu
tugas selesai. `prefers-reduced-motion` mematikan semuanya.

## Yang dikelola dari UI, bukan dari terminal

Semua yang dibutuhkan untuk bekerja ada di layar, tanpa membuka terminal:

- Model: pil nama model di kotak tulis, atau menu alat bagian Model. Ganti
  sekali, langsung ikut ke Hermes dan keempat pekerja.
- Plugin MCP: menu alat bagian Plugin MCP. Satu definisi ditulis ke konfigurasi
  keempat pekerja sekaligus, dan paketnya diunduh lebih dulu supaya pemakaian
  pertama tidak gagal.
- Skill dari GitHub: menu alat bagian Skill dari GitHub. Repo dikloning ke
  `~/.astroz/skills/<nama>`, lalu setiap folder berisi `SKILL.md` ditautkan ke
  folder skill yang dibaca pekerja. Pekerja diberi tahu daftar namanya di setiap
  tugas, jadi langsung dipakai tanpa perintah tambahan.
- Berkas, git, dan tes: menu alat bagian Berkas dan tes.
- Lampiran: tombol `+` di kotak tulis (gambar atau berkas apa saja).

Aturan yang dipegang: jangan menambah tombol atau mode yang tidak melakukan
apa-apa. Kalau sebuah fitur belum punya jalur yang benar-benar jalan, jangan
ditampilkan.

## Suara tulisan

Bahasa Indonesia sehari-hari. Kata kerja yang jelas: kirim, buka, simpan,
periksa. Tidak ada kata pemanis seperti "seamless", "powerful", "revolusioner",
"AI-powered", atau "mulus". Tidak ada tanda seru. Tidak ada tanda pisah panjang.
Tidak ada emoji. Kalau sesuatu gagal, tulis apa yang gagal dan apa yang bisa
dicoba berikutnya.

## Yang dilarang

- Tumpukan kartu, kartu di dalam kartu.
- Gradien, kaca buram, bayangan jatuh yang berat.
- Sudut tajam di tombol dan kartu.
- Abu-abu dingin atau biru di luar cincin fokus.
- Bobot huruf 600 ke atas untuk judul serif.
- Huruf mesin untuk kalimat biasa.
- Ikon hiasan atau emoji sebagai pengganti label.
- Badge palsu, angka karangan, panah hiasan.
- Warna yang tidak punya tugas.

## Cara memeriksa

1. Buka UI di lebar 375px dan 1280px. Tidak boleh ada gulir mendatar.
2. Tab sampai habis: setiap kontrol harus kelihatan cincin fokusnya.
3. Jalankan satu tugas sungguhan: gelembung pemakai, garis kilau, jawaban yang
   menggantikan keadaan jalan, dan panel Proses harus terisi.
4. Ganti tema terang dan gelap: semua teks harus tetap terbaca.
5. Konsol browser harus bersih.
