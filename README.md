<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/astroz-logo-gelap.png">
    <img src="assets/astroz-logo.png" alt="AstroZ" width="150">
  </picture>
</p>

# AstroZ

Satu chat untuk mengerjakan tugas koding, dengan tim pekerja di belakangnya.

Kamu menulis seperti mengobrol biasa. AstroZ meneruskan pesan itu ke sebuah tim:
satu perencana menyusun langkah, empat CLI pekerja (Claude Code, Codex, OpenCode,
OMP) mengerjakannya lewat 9Router sebagai gerbang model tunggal, lalu satu
penilai memeriksa hasilnya sebelum jawaban dikirim balik ke chat.

Jawabanmu muncul sebagai balasan chat. Proses kerjanya tidak dicampur ke dalam
percakapan: rencana, keluaran tiap pekerja, hasil tes, dan penilaian duduk di
panel terpisah di sebelahnya.

## Yang perlu ada dulu

1. **Python 3.10 atau lebih baru**, dengan tiga paket di `requirements.txt`
   (fastapi, uvicorn, PyYAML). Pasang di venv supaya tidak menabrak python
   sistem:

   ```bash
   git clone https://github.com/bayz-dik/AstroZ.git astroz
   cd astroz
   python3 -m venv .venv
   .venv/bin/pip install -r requirements.txt
   ./run.sh
   ```

   `run.sh` mencari python berurutan: `$PY`, lalu `.venv`, lalu `python3`. Kalau
   paketnya belum lengkap, skrip berhenti dengan perintah yang harus dijalankan,
   bukan gagal di tengah dengan pesan uvicorn yang membingungkan.

2. **9Router** di `:20128`. Ini gerbang model untuk semua pekerja. Begitu
   AstroZ menyala, kunci API, alamat gateway, dan daftar modelnya diambil
   sendiri dari 9Router: tidak perlu menempelkan kunci di UI dan tidak perlu
   menekan tombol sinkron. Kalau 9Router belum ada, `run.sh` memberi tahu dan
   bagian lain tetap menyala.

3. **Node.js 20 atau lebih baru**, untuk memasang CLI pekerja. Empat pekerja
   (Claude Code, Codex, OpenCode, OMP) bisa dipasang langsung dari UI: menu
   garis tiga, bagian Pekerja, tekan Pasang sekarang. Tidak perlu terminal.

4. **Satu CLI pekerja minimal** supaya tugas bisa dikerjakan. Satu pekerja sudah
   cukup untuk bekerja; menambah pekerja lain membuat tugas besar bisa dipecah
   paralel dan dibandingkan hasilnya, jadi lebih cepat dan lebih teliti.

Yang tidak perlu: kunci API tidak perlu diisi ulang di UI, karena sudah dibaca
dari 9Router.

## Jalankan

```bash
./run.sh                 # 9Router + penyaring SSE + UI di :8799
./run.sh 8799 --foreground
```

`run.sh` mencetak dua alamat: satu untuk dibuka dari HP (`http://<ip-lan>:8799/`),
satu untuk dari mesin sendiri.

Supaya tidak mati sendiri:

```bash
python3 watchdog.py --loop --interval 30
```

Watchdog memeriksa port dengan koneksi TCP sungguhan, bukan `ss` (di container
proot ini `ss` tidak melaporkan socket yang listening, jadi pemeriksaan berbasis
`ss` akan menganggap semua layanan mati).

## Bagian layar

| Bagian | Isi |
|---|---|
| Chat | pesanmu dan jawaban AstroZ. Pesanmu blok berlatar hangat, jawaban AstroZ teks polos. Progres kerja tidak ditulis di sini, hanya satu tombol kecil untuk membukanya |
| Menu alat | dibuka dari tombol garis tiga di kiri atas: Obrolan, Proses kerja, Plugin MCP, Skill dari GitHub, Pekerja, Berkas dan tes, Catatan kejadian, Model |
| Menu titik tiga | aksi untuk percakapan yang sedang dibuka: lihat proses kerja, ganti nama, salin percakapan, tema |
| Strip kerja | kotak kecil di bawah bar yang muncul sendiri selama ada tugas berjalan: pekerja mana yang sedang mengerjakan, sudah berapa lama, dan langkah terakhirnya kalau diketuk |
| Panel kerja | keadaan tugas terakhir, berkas yang berubah, dan langkah-langkahnya. Kolom tetap di 1280px ke atas, lembar geser di bawahnya |

Di layar 1280px ke atas keduanya tampil bersamaan: chat dan panel kerja. Di
bawah 1280px panel kerja jadi lembar geser supaya kolom chat tidak diperas, dan
daftar percakapan juga lembar geser dari tombol di kanan atas.

Pesan yang jelas bukan pekerjaan (sapaan, pertanyaan pendek) dijawab langsung
oleh model tanpa memanggil pekerja CLI dan tanpa membuat folder kerja baru.
Panel kerjanya menandai ini sebagai "Dijawab langsung".

## Satu model untuk lima tempat

Menu Alat, bagian Model: pilih satu baris, tekan pakai model ini. Sekali tekan,
model yang sama ditulis ke Hermes dan keempat pekerja. Pil nama model di kotak
tulis ikut berubah sendiri, dan model itu juga yang dipakai kalau kamu menekan
pilnya untuk memilih dari sana.

| Sasaran | Berkas | Alamat yang ditulis |
|---|---|---|
| claude | `~/.claude/settings.json` | :20128 langsung |
| codex | `~/.codex/config.toml` | :20129 |
| opencode | `~/.config/opencode/opencode.json` | :20129 |
| omp | `~/.omp/agent/models.yml` | :20129 |
| hermes | `$HERMES_HOME/config.yaml` | :20128 langsung |

Port dan model itu dua hal terpisah: port adalah pintu yang diketuk, model adalah
siapa yang diminta di dalam pintu itu.

Daftar model dibaca dari dua sumber sekaligus, karena masing-masing tidak lengkap
sendiri:

- `/api/models` pada 9Router: katalog lengkap dengan nama, batas konteks, dan harga.
  Isinya hanya provider yang kredensialnya dikenal dashboard.
- `/v1/models`: daftar id yang benar-benar bisa dipanggil. Di sinilah provider
  seperti `kenari-id`, `dvvai`, `cavoti-ai`, dan `kr` muncul.

Id provider yang berupa uuid (`openai-compatible-chat-...`) diganti dengan prefix
yang dikenali (`kenari-id`, `oc-prod`, dan seterusnya), diambil dari daftar
koneksi 9Router. Tombol Tes mana yang hidup memeriksa model sungguhan dan
menandai mana yang menjawab.

## Alur kerja

- **Cepat**: satu pekerja langsung, lalu tes.
- **Sedang**: rencana singkat, satu sampai dua pekerja, tes, penilaian.
- **Besar**: tugas dipecah, dikerjakan paralel, pekerja saling menilai, tes,
  lalu penilaian akhir.

Kalau satu pekerja macet, tugas tidak ikut macet. Dua pengaman menjaganya:

- **Batas macet**: pekerja yang tidak menghasilkan kemajuan berarti selama
  `workflow.stall_seconds` (bawaan 240 detik) dihentikan. Baris progres seperti
  "Working..." tidak dihitung sebagai kemajuan, dan worker yang benar-benar
  mengalir keluarannya tidak pernah dipotong.
- **Eskalasi**: kalau semua percobaan gagal, tugas dicoba ke pekerja lain di
  daftar prioritas, sampai `workflow.escalate_tries` pekerja (bawaan 2). CLI
  yang macet gagal di model apa pun, jadi pindah pekerja lebih berguna daripada
  mengulang model.

Dua putaran perbaikan, keduanya bukan status akhir:

- tes merah, keluaran tes dikirim ke pekerja lain untuk diperbaiki (`fix_rounds`);
- penilaian menemukan masalah, daftar masalahnya dikirim balik ke pekerja lain
  (`fix_review_rounds`). Ini perlu karena tes hijau tidak berarti permintaan
  terpenuhi: pernah terjadi pekerja menambah newline padahal diminta tidak, dan
  tes buatannya sendiri tetap hijau.

Kalau model gateway tidak bisa dihubungi, rencana diisi versi sederhana supaya
tugas tetap jalan.

Pemilihan pekerja hemat dulu: `worker_order` dan `worker_cost` di `team.yaml`
menentukan urutannya, dan putaran perbaikan memakai pekerja termurah yang belum
menyentuh tugas itu.

## Berkas

```
config.py         pembaca team.yaml, token 9Router, kunci dari sqlite
hub.py            pusat kejadian (JSONL + SSE + pembaca berkas plugin)
gateway.py        klien 9Router: sinkron model, terapkan, chat, uji, setelan Hermes
adapters.py       empat adapter pekerja + apply_all
orchestrator.py   rencana, pekerja, diskusi, tes, penilaian, jawaban akhir
sessions.py       percakapan: satu utas berisi daftar tugas
project.py        daftar berkas, baca berkas, git, deteksi dan jalan tes
proxy.py          penyaring SSE :20129 ke 9Router :20128 (buang [DONE] ganda)
server.py         FastAPI: UI, API, SSE
watchdog.py       menjaga 9Router, penyaring, dan UI tetap hidup
web/index.html    kerangka UI
web/app.css       tampilan
web/app.js        perilaku: chat, panel proses, alat
assets/           banner README
tests/smoke.sh    uji end to end
```

`team.yaml` berisi kunci API dan tidak ikut ke repo; contohnya ada di
`team.yaml.example`.

## API

```
GET    /api/state                    ringkasan gateway, pekerja, tugas, proyek
GET    /api/sessions                 daftar percakapan
POST   /api/sessions                 percakapan baru
GET    /api/sessions/{id}            isi percakapan + kejadian tiap tugas
POST   /api/sessions/{id}            ganti judul
DELETE /api/sessions/{id}            hapus percakapan
POST   /api/chat                     kirim pesan: {text, session, workflow}
GET    /api/events?replay=N          aliran kejadian (SSE)
GET    /api/events/recent?limit=&kind=
POST   /api/gateway/sync?apply=0|1   baca model dari 9Router
GET    /api/gateway/models?q=&provider=&only_healthy=1
POST   /api/gateway/model            {model, apply_workers}
POST   /api/gateway/probe            uji model mana yang menjawab
POST   /api/gateway/key              {api_key}
POST   /api/apply                    tulis model sekarang ke semua pekerja
GET    /api/workers                  status pekerja
POST   /api/workers/{key}            aktifkan atau setel model pekerja
POST   /api/workers/{key}/probe      periksa satu pekerja
POST   /api/tasks                    kirim tugas langsung tanpa chat
GET    /api/tasks, /api/tasks/{id}   daftar dan rincian tugas
GET    /api/project/tree, /api/project/file?path=
GET    /api/git, /api/git/diff       POST /api/git/commit
POST   /api/test                     jalankan tes
POST   /api/config                   ubah folder kerja atau setelan alur
```

## Catatan teknis

Beberapa hal yang perlu diketahui sebelum mengubah isi repo ini:

- 9Router menutup stream SSE dengan `data: [DONE]` dua kali. Parser ketat
  (opencode) mati karenanya, jadi ada `proxy.py` di :20129 yang membuang
  terminator kedua. Semua pekerja menembak :20129; Hermes tetap ke :20128
  langsung karena Hermes tahan terhadap `[DONE]` ganda dan Hermes adalah alat
  untuk memperbaiki susunan ini.
- opencode menentukan folder kerjanya dari `process.env.PWD`, bukan `cwd` proses.
  Karena itu `env["PWD"]` diset sama dengan folder kerja; tanpa itu berkas
  mendarat satu tingkat di atas proyek dan tugas tetap melaporkan sukses.
- OMP perlu `--auto-approve` (kalau tidak, tugas menggantung di prompt pertama)
  dan provider [OI]-compatible harus didaftarkan di `~/.omp/agent/models.yml`.
- Codex CLI 0.154 ke atas memakai `wire_api = "responses"`, bukan `"chat"`.
- Claude menambahkan suffix `[1m]` pada model dari settings.json, jadi model
  selalu dikirim lewat `--model` eksplisit.
- Penilaian otomatis dari 9Router tidak semua hidup. Pakai Tes mana yang hidup.
- Sebagian provider bisa mati sewaktu-waktu: `oc-prod/*` pernah menjawab 404
  "No active credentials for provider" untuk semua modelnya, dan `cavoti-ai`
  menjawab 503. Model yang sedang dipakai harus yang benar-benar menjawab, kalau
  tidak semua pekerja akan menunggu jawaban yang tidak pernah datang. Cek dengan
  Tes mana yang hidup, lalu pilih model yang lolos.
- Model penalaran kadang mengisi `reasoning` dan membiarkan `content` kosong.
  `gateway.chat` menerima keduanya, dan penilai yang hanya mengembalikan template
  "PASS|FAIL" dicatat sebagai UNKNOWN, bukan ditebak.
- Jawaban yang kamu baca di chat bukan keluaran mentah pekerja. Keluarannya berisi
  baris progres, jejak berkas, dan kode warna terminal; semuanya dibersihkan dulu,
  lalu model gateway merangkumnya jadi beberapa kalimat yang bisa dibaca. Kalau
  gateway tidak bisa dihubungi, dipakai baris paling informatif dari pekerja.
- Setiap tugas yang selesai disimpan sebagai commit di folder kerja hanya kalau
  tes dan penilaiannya lulus (`workflow.auto_commit`).
- Jawaban yang dikirim balik ke chat adalah ringkasan dari model gateway, bukan
  keluaran mentah pekerja. Kalau tidak ada pekerja yang berhasil, jawabannya
  mengatakan itu apa adanya, bukan mengarang hasil.

## Plugin Hermes

`~/.hermes/plugins/astroz` menambahkan tool `coding_team` (submit, status, tasks,
models, model, sync, test), mencerminkan aktivitas agent loop ke aliran kejadian
UI, dan menyediakan perintah `/team`, `/team-model`, `/team-tasks`, `/team-sync`,
`/team-apply`.

```bash
hermes plugins enable astroz
```

## Uji

```bash
./tests/smoke.sh
MODEL=<id-model> ./tests/smoke.sh
```

## Catatan tampilan

Arah tampilan sekarang mengikuti rumah terracotta ala Claude Code. Aturan
lengkapnya di `design-systems/claude-code/DESIGN.md`, nilai tokennya di
`design-systems/claude-code/tokens.css`, dan asal setiap nilai di
`design-systems/claude-code/source/evidence.md`.

Dua sumber yang dipakai:

- `design-systems/claude/` dari repo [nexu-io/open-design](https://github.com/nexu-io/open-design)
  (Apache-2.0): kanvas perkamen, aksen terracotta, netral serba hangat,
  kedalaman memakai cincin `0 0 0 1px`, radius 8/12/16px, tanpa gradien.
- Palet Claude Code yang dibaca langsung dari binari `@anthropic-ai/claude-code`
  yang terpasang di mesin ini (aksen `#D97757`, hijau `#69DB7C`, kuning
  `#FFC107`, merah `#FF6B80`, latar gelap keluarga `rgb(38,38,38)`).

Hurufnya Fraunces (judul), Inter (teks), JetBrains Mono (angka dan kode),
ketiganya lisensi OFL dan disimpan sendiri di `web/fonts/` supaya UI tetap
sama tanpa internet.

Angka kontras dihitung dengan rumus WCAG, lalu diperiksa ulang di browser
sungguhan dengan menelusuri setiap simpul teks yang benar-benar tampil
(latar belakang dikomposit berlapis, termasuk baris percakapan yang terpilih):

| Pasangan | Terang | Gelap |
|---|---|---|
| teks utama pada latar halaman | 17.50:1 | 13.75:1 |
| teks lembut pada latar halaman | 6.26:1 | 6.82:1 |
| teks meta pada latar halaman | 5.23:1 | 5.79:1 |
| teks pada tombol aksen | 4.63:1 | 4.86:1 |
| aksen sebagai teks | 5.45:1 | 5.09:1 |
| selesai / jalan / gagal | 6.20 / 5.45 / 5.72 | 8.68 / 9.30 / 5.54 |
| garis batas kontrol | 3.20:1 | 3.53:1 |

Hasil audit terakhir di browser: 94 simpul teks diperiksa, 0 gagal, di kedua
tema. Strip kerja diaudit ulang terpisah sesudah ditambahkan (26 simpul di
dalamnya, kedua tema, 0 gagal): teks chip pekerja dan jamnya sengaja memakai
`--tinta-2` dan `--tinta-lembut`, bukan `--tinta-meta`, karena di atas latar
hangat `--tinta-meta` hanya 4.40:1. Di lebar 375px tidak ada geseran mendatar
dan semua sasaran sentuh minimal 44px. Di lebar 1000-1279px panel kerja
otomatis pindah jadi lembar geser supaya kolom percakapan tidak diperas.

Ikon diambil dari teks, bukan dari pustaka ikon. Animasi hanya dipakai untuk
menandai hal yang sedang berjalan (garis kilau di bawah bar dan kilau aksen
pada gelembung yang sedang dikerjakan), dan semuanya berhenti saat pekerjaan
selesai. `prefers-reduced-motion` mematikan semuanya. Tampilan diuji pada
lebar 375px, 1100px, dan 1280px, termasuk fokus keyboard.
