# MindStudio.ai — acuan desain (DIUKUR dari situs hidup)

Sumber: https://www.mindstudio.ai/ — diukur 20 Sep 2026 lewat computed style di
browser sungguhan (Chrome/CDP), bukan perkiraan dari melihat gambar.

Cara mengukur ulang kalau perlu: buka situsnya, lalu baca
`getComputedStyle(document.documentElement)` untuk variabel `--color-*`, dan
`getComputedStyle` pada `header`, `h1`, `a.bg-brand-500`, dan `footer`.

## 1. Warna

### Netral (tulang punggung seluruh tampilan)
| Token | Nilai | Dipakai untuk |
|---|---|---|
| neutral-50 | `#fafafa` | latar halaman |
| neutral-100 | `#f0f0f0` | permukaan lembut, isian |
| neutral-200 | `#e0e0e0` | SEMUA garis |
| neutral-300 | `#c3c3c3` | garis tombol sekunder |
| neutral-400 | `#a0a0a0` | teks nonaktif |
| neutral-500 | `#787878` | teks meta |
| neutral-600 | `#585858` | teks nav, teks lembut |
| neutral-700 | `#404040` | teks kuat sekunder |
| neutral-800 | `#282828` | garis di latar gelap |
| neutral-900 | `#1a1a1a` | permukaan gelap |
| neutral-950 | `#060606` | teks utama, latar gelap penuh |

### Biru brand (satu-satunya aksen)
| Token | Nilai | Catatan |
|---|---|---|
| brand-50 | `#e6f0ff` | latar pilihan lembut |
| brand-100 | `#b3d4ff` | |
| brand-300 | `#4d9cff` | |
| brand-400 | `#1a80ff` | |
| brand-500 | `#0069ff` | tombol utama, aksen, fokus |
| brand-600 | `#0055cc` | hover tombol utama |
| brand-700 | `#004099` | |
| brand-900 | `#001a40` | |

### Hijau aksen (dipakai hemat, untuk "berhasil"/"hidup")
`accent-50 #e9f9f2` · `accent-400 #43d598` · `accent-600 #24a270` · `accent-700 #1b7a54`

### Latar gelap
Bagian gelap memakai `#0a0a0a` (hero berkabut) dan `#060606` (footer/section),
teks putih.

## 2. Huruf

- Teks & judul: **Inter** (`--font-sans`, `--font-display`). Diukur: `h1`
  memakai Inter, bukan font judul terpisah.
- Kode/angka: **JetBrains Mono** (`--font-mono`).
- Ada `--font-franie` (Franie) untuk display, tetapi `h1` di halaman ini tetap
  Inter. Franie proprietary, tidak perlu dikejar.
- Bobot: 400 teks, 500 tombol, 600 judul. Tidak ada 700+ di antarmuka.

### Skala (diukur dari elemen nyata)
| Peran | Ukuran | Line-height | Letter-spacing | Bobot |
|---|---|---|---|---|
| display-lg (h1 besar) | 72px | 1.05 | -0.03em | 600 |
| display (h1) | 60px | 1.08 | -0.025em | 600 |
| display-sm | 48px | 1.1 | -0.02em | 600 |
| heading-lg (h2) | 36px | 1.15 | -0.015em | 600 |
| heading (h2 kecil) | 30px | 1.2 | -0.01em | 600 |
| heading-sm (h3) | 24px | 1.25 | -0.01em | 600 |
| body-lg | 18px | 1.6 | normal | 400 |
| body | 16px | 1.6 | normal | 400 |
| body-sm | 14px | 1.5 | normal | 400 |
| caption | 12px | 1.5 | normal | 400 |

## 3. Bentuk

| Token | Nilai |
|---|---|
| radius-sm | 4px |
| radius-md | 6px |
| radius-lg | 8px |
| radius-xl | **12px** (tombol, kartu, isian) |
| radius-card | 12px |
| shadow-sm | `0 1px 3px 0 #0000001a, 0 1px 2px -1px #0000001a` |
| shadow-lg (menu/kartu naik) | `0 10px 15px -3px #0000001a, 0 4px 6px -4px #0000001a` |
| blur (kepala menempel) | 16px (`backdrop-blur-lg`) |

## 4. Jarak

- Satuan dasar 4px (`--spacing: .25rem`).
- Padding section: `96px 0` (`--spacing-section: 6rem`), versi kecil 64px.
- Lebar isi maksimum: **1152px** (`--container-content: 72rem`).
- Padding mendatar wadah: 24px.
- Jarak antar kartu: 32px (`gap-8`); rapat 16px (`gap-4`).

## 5. Komponen (nilai terukur)

### Kepala (header)
```
position: sticky; top: 0; z-index: 50
background: rgba(250,250,250,.8) + backdrop-filter: blur(16px)
border-bottom: 1px solid #e0e0e0
tinggi: 54px
wadah: max-width 1152px, padding 10px 24px, flex, space-between
```
- Tautan nav: 14px / 400 / `#585858`, hover -> `#060606`, transisi warna.
- Logo: SVG lockup, tinggi 17px.

### Tombol utama
```
background #0069ff; color #fff; radius 12px; font 14px/500 (nav) atau 16px/500
padding 6px 14px (nav), 12px 24px (hero); hover background #0055cc
transition 200ms cubic-bezier(.4,0,.2,1)
```
### Tombol sekunder
```
background #fff; color #060606; border 1px solid #c3c3c3; radius 12px
font 16px/500; padding 12px 24px
```
### Kartu
```
background #fff; border 1px solid #e0e0e0; radius 12px
shadow-lg (kartu mengambang/menu)
```
### Menu turun
```
w-56 (224px); bg #fff; border 1px solid #e0e0e0; radius 12px
padding 4px 0; item 8px 16px; shadow-lg
```
### Footer
```
background #060606; color #fafafa; border-top 1px solid #282828
```
### Kisi
`grid-cols-4 gap-8` di desktop (4 x 252px + 32px), 1 kolom di HP.

## 6. Gerak

- Durasi bawaan 150ms; tombol 200ms.
- Kurva: `cubic-bezier(.4,0,.2,1)` (ease-out standar).
- Tidak ada animasi hias. Hanya transisi warna/latar dan `pulse` 2s untuk
  penanda "sedang jalan".

## 7. Yang HARUS sama saat diadaptasi ke AstroZ

1. Latar `#fafafa`, permukaan `#ffffff`, SEMUA garis `#e0e0e0`.
2. Satu aksen saja: biru `#0069ff`. Tidak ada terracotta, tidak ada warna kedua.
3. Inter untuk semua teks, TERMASUK judul (bukan serif). Judul 600, rapat
   (`-0.01em` sampai `-0.03em`).
4. Radius 12px untuk tombol/kartu/isian.
5. Kepala menempel dengan blur + garis bawah 1px.
6. Kedalaman lewat GARIS + bayangan tipis, bukan bayangan tebal.
7. Teks utama `#060606`, teks lembut `#585858`, meta `#787878`.

## 8. Padanan tema gelap (dari skala netral MindStudio sendiri)

MindStudio memakai bagian gelap `#060606` / `#0a0a0a`. Tema gelap AstroZ dibangun
dari skala yang sama supaya tetap satu keluarga:

| Peran | Terang | Gelap |
|---|---|---|
| latar | `#fafafa` | `#060606` |
| permukaan | `#ffffff` | `#1a1a1a` |
| permukaan lembut | `#f0f0f0` | `#282828` |
| garis | `#e0e0e0` | `#404040` |
| teks | `#060606` | `#fafafa` |
| teks lembut | `#585858` | `#a0a0a0` |
| meta | `#787878` | `#787878` |
| aksen | `#0069ff` | `#4d9cff` |
