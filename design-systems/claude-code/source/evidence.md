# Sumber dan bukti: design system claude-code

Berkas ini mencatat dari mana setiap nilai di `tokens.css` datang, supaya
tidak ada yang dikarang.

## 1. Design system Claude di OpenDesign

Repo: https://github.com/nexu-io/open-design (Apache-2.0)
Berkas yang dibaca: `design-systems/claude/DESIGN.md`, `tokens.css`,
`design-tokens.json`, `tailwind-v4.css`, `source/evidence.md`.

Yang dipakai dari sana:

- Kanvas perkamen `#f5f4ed`, permukaan gading `#faf9f5`, pasir hangat `#e8e6dc`.
- Tinta `#141413`, teks kedua `#3d3d3a`, abu hangat `#5e5d59`, meta `#87867f`.
- Garis krem `#f0eee6` dan `#e8e6dc`.
- Aksen terracotta `#c96442`, gading di atasnya `#faf9f5`.
- Gagal `#b53333`, fokus `#3898ec` sebagai satu-satunya warna dingin.
- Radius 8 / 12 / 16 px, tanpa sudut tajam.
- Kedalaman cincin `0 0 0 1px` ganti bayangan jatuh.
- Tinggi baris isi 1.6, judul serif bobot 500 tunggal.
- Semua netral bernada kuning-coklat, tidak ada abu biru.

Catatan penting dari berkas bukti OpenDesign sendiri: paket itu mengaku
diturunkan dari fixture bawaan mereka, bukan dari pengambilan ulang situs
Anthropic. Jadi ia dipakai sebagai aturan bentuk dan warna, bukan sebagai
klaim nilai resmi.

## 2. Palet Claude Code dari binari yang terpasang

`@anthropic-ai/claude-code` versi terpasang di mesin ini adalah satu binari
Bun. Tabel warna tema ada di dalamnya sebagai string, bukan di berkas
terpisah. Dibaca dengan mencari string lalu mencetak konteks di sekitarnya.

Perintah yang dipakai (baca saja, tidak menjalankan binari):

    python3 - <<'PY'
    data = open('bin/claude.exe','rb').read()
    i = data.find(b'rgb(208,180,255)')          # jangkar: tabel warna rainbow
    print(data[i-7000:i+2000].decode('utf-8','replace'))
    PY

Hasil yang terlihat dan cocok dengan pengetahuan umum soal Claude Code:

- Aksen terracotta di dua nada: `rgb(217,119,87)` = `#D97757` dan
  `rgb(215,119,87)` = `#D77757`, plus versi terang `rgb(245,149,117)` =
  `#F59575` (ini nilai `shimmer`, dipakai untuk kilau saat ada yang jalan).
- Keluarga shimmer lain: `permissionShimmer`, `promptBorderShimmer`,
  `inactiveShimmer`, `warningShimmer`, `fastModeShimmer`.
- Warna keadaan: `rgb(105,219,124)` = `#69DB7C` (hijau), `rgb(255,168,180)`
  = `#FFA8B4` (merah muda), `rgb(199,225,203)`, `rgb(253,210,216)`,
  `rgb(220,38,38)`, `rgb(22,163,74)`, `rgb(202,138,4)`, `rgb(251,188,4)`,
  `rgb(8,145,178)`, `rgb(37,99,235)`.
- Latar terang tema: `rgb(252,252,252)`, `rgb(250,245,250)`,
  `rgb(230,245,250)`, `rgb(245,245,245)`, `rgb(240,240,240)`.
- Latar gelap tema: `rgb(38,38,38)`, `rgb(55,55,55)`, `rgb(70,70,70)`,
  `rgb(80,80,80)`, `rgb(65,60,65)`, `rgb(55,65,70)`.
- Di dalam UI, dua token yang paling menentukan bentuk: `userMessageBackground`
  dan `userMessageBackgroundHover` (latar kotak pesan pemakai dan bar
  prompt yang dipaku di atas).
- Daftar nama tema: `dark`, `light`, `light-daltonized`, `dark-daltonized`,
  `light-ansi`, `dark-ansi`, plus `auto`.
- Bentuk tema kustom: `~/.claude/themes/<slug>.json` dengan kunci
  `name`, `base`, `overrides`. Nilai boleh `#rrggbb`, `rgb(r,g,b)`,
  `ansi256(n)`, atau `ansi:<nama>`. Token yang berguna: `text`, `subtle`,
  `userMessageBackground`, `userMessageBackgroundHover`, `inactive`,
  `promptBorder`, `bashMessageBackgroundColor`, `memoryBackgroundColor`.

Yang TIDAK berhasil dibaca: tabel token lengkap (`success`, `diffAdded`,
`error`, dan seterusnya) beserta nilainya. Stringnya tidak tersimpan sebagai
literal di binari. Karena itu:

- Latar gelap `#262624` dan permukaan `#30302E` diambil dari nilai kanonik
  tema gelap Claude (bukan dari binari). Keduanya konsisten dengan keluarga
  `rgb(38,38,38)`/`rgb(55,55,55)` yang terlihat di binari.
- Hijau selesai memakai `#69DB7C` yang memang terbaca dari binari.
- Kuning jalan memakai `rgb(255,193,7)` = `#FFC107` dari binari.
- Merah gagal memakai `rgb(255,107,128)` = `#FF6B80` dari binari.

## 3. Aturan yang ditambahkan sendiri

Nilai di bawah ini bukan dari Claude, melainkan hasil hitung kontras di
berkas `tokens.css`. Semuanya dipilih supaya lulus 4.5:1 di kedua tema:

| Peran | Terang | Gelap | Kontras |
|---|---|---|---|
| Aksen sebagai latar tombol | `#C96442` | `#D97757` | 4.63 / 4.86 |
| Aksen sebagai teks | `#A8492F` | `#E08B6E` | 5.45 / 5.09 |
| Selesai | `#146C2E` | `#69DB7C` | 6.20 / 8.68 |
| Jalan | `#A8492F` | `#FFC107` | 5.45 / 9.30 |
| Gagal | `#B53333` | `#FF6B80` | 5.72 / 5.54 |
| Garis kuat | `#8E8C84` | `#7C7A73` | 3.20 / 3.53 |

`#87867F` dari OpenDesign ternyata hanya 3.47:1 pada kertas `#FAF9F5`, jadi
terlalu redup untuk teks metadata dan diganti `#6F6E68` (4.85:1).

## 4. Huruf

Claude memakai keluarga huruf buatan sendiri (Anthropic Serif, Anthropic
Sans, Anthropic Mono) yang tidak boleh dipakai di luar produknya. Jadi
dipakai padanan berlisensi OFL yang disimpan sendiri di `web/fonts/`:

| Peran | Padanan | Alasan |
|---|---|---|
| Judul serif | Fraunces | serif modern berbobot sedang, hangat, bukan Georgia |
| Teks UI | Inter | netral, bersih, bukan huruf bawaan sistem |
| Angka dan kode | JetBrains Mono | tinggi huruf besar, angka tidak tertukar |

Tiga berkas woff2 per keluarga (latin dan latin-ext), total sekitar 308 KB,
diambil dari Google Fonts. Disimpan sendiri supaya UI tetap sama walau
tanpa internet, sama seperti alasan 9Router dipakai di mesin ini.
