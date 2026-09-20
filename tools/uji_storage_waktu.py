"""Bukti hitungan penyimpanan TIDAK memblokir event loop.

Bug aslinya: `/api/storage` memanggil `storage.pemakaian()` langsung di dalam
`async def`, jadi ia memblokir SATU-SATUNYA event loop selama 20+ detik. Yang
terlihat bukan hanya panel Penyimpanan yang lambat, tetapi SELURUH UI: permintaan
yang tidak ada hubungannya (mis. /api/state) ikut menunggu.

Uji ini harus dijalankan pada server yang BARU dinyalakan, karena simpanan
sebentar (CACHE_DETIK) membuat panggilan kedua tidak menghitung apa pun.
"""
import pathlib
import threading
import time
import urllib.request

BASE = "http://127.0.0.1:8799"
TOKEN = pathlib.Path("/root/AstroZ/app_token.txt").read_text().strip()


def ambil(jalur, timeout=180):
    req = urllib.request.Request(BASE + jalur)
    req.add_header("Authorization", "Bearer " + TOKEN)
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=timeout) as r:
        r.read()
    return time.time() - t0


# Pemanasan: /api/state sekali supaya impor dan cache internal sudah siap, agar
# yang diukur murni pengaruh hitungan storage.
print(f"/api/state (pemanasan) : {ambil('/api/state'):6.2f}s")

waktu = []
stop = threading.Event()


def pemantau():
    while not stop.is_set():
        try:
            waktu.append(ambil("/api/state", timeout=60))
        except Exception:
            waktu.append(float("nan"))
        time.sleep(0.15)


th = threading.Thread(target=pemantau, daemon=True)
th.start()
time.sleep(0.4)
t_storage = ambil("/api/storage")
time.sleep(0.3)
stop.set()
th.join(timeout=10)

bersih = [x for x in waktu if x == x]
print(f"/api/storage (dingin)  : {t_storage:6.2f}s")
if bersih:
    print(f"selama itu /api/state dipanggil {len(bersih)}x: "
          f"maks {max(bersih):.2f}s, rata-rata {sum(bersih)/len(bersih):.3f}s")
    print("event loop TIDAK diblokir:", "YA" if max(bersih) < 2.0 else "TIDAK")
else:
    print("pemantau tidak sempat memanggil apa pun")
