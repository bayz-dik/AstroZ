"""Ukur geometri foto contoh secara presisi, bukan dengan perkiraan mata.

Yang diukur: batas panel menu, kotak ketik di strip percakapan, tinggi judul,
dan tinggi baris riwayat. Semuanya dipakai untuk menetapkan ukuran CSS.
"""
from PIL import Image

IM = "/mnt/sdcard/Download/AstroZ/contoh.jpg"
im = Image.open(IM).convert("RGB")
W, H = im.size
px = im.load()
print("ukuran gambar:", W, H)


def terang(c):
    return sum(c) / 3


def scan_baris(y, x0, x1, ambang=40):
    """Rentang x yang lebih terang dari ambang pada satu baris."""
    run = []
    mulai = None
    for x in range(x0, x1):
        if terang(px[x, y]) > ambang:
            if mulai is None:
                mulai = x
        else:
            if mulai is not None and x - mulai > 3:
                run.append((mulai, x - 1))
            mulai = None
    if mulai is not None:
        run.append((mulai, x1 - 1))
    return run


# ---- 1. batas panel menu: cari kolom x yang jadi pemisah gelap/terang ----
# Panel menu berisi teks terang; strip percakapan di kanan lebih gelap.
terang_per_kolom = []
for x in range(W):
    n = 0
    for y in range(300, 2000, 7):
        if terang(px[x, y]) > 55:
            n += 1
    terang_per_kolom.append(n)
# batas: kolom terakhir dengan banyak piksel terang, sebelum jurang panjang
batas = 0
for x in range(W - 1, 0, -1):
    if terang_per_kolom[x] > 20:
        batas = x
        break
print("panel menu berakhir di x =", batas, f"({round(batas / W * 100)}% lebar)")

# ---- 2. judul di kepala menu ----
for y in range(140, 260):
    r = scan_baris(y, 20, batas)
    if r:
        print("judul mulai di y =", y, "rentang x:", r[:3])
        break
baris_judul = []
for y in range(140, 300):
    r = scan_baris(y, 20, batas)
    baris_judul.append((y, sum(b - a for a, b in r)))
for y, tot in baris_judul:
    if tot > 0:
        print("  y", y, "lebar tinta", tot)
    if y > 240:
        break

# ---- 3. kotak ketik: cari kotak abu terang di bagian bawah strip kanan ----
x_kanan0 = batas + 10
print("\n-- cari kotak ketik di x >", x_kanan0)
for y in range(H - 400, H - 60, 4):
    r = scan_baris(y, x_kanan0, W, ambang=45)
    if r:
        lebar = max(b for a, b in r) - min(a for a, b in r)
        if lebar > 200:
            print("  y", y, "rentang", r[0], "lebar", lebar)
