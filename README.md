# AstroZ

Satu Web UI (mobile-first) yang mengendalikan Hermes sebagai orchestrator plus
worker pool ([CC], Codex, OpenCode, OMP) lewat 9Router sebagai gateway LLM
tunggal. Dijalankan dari HP: Android, Termux, Ubuntu (proot), lalu buka UI-nya.

```
Android -> Termux -> Ubuntu -> Web UI (FastAPI) -> Hermes orchestrator
                                      |- ClaudeAdapter  -+
                                      |- CodexAdapter    |  worker pool
                                      |- OpenCodeAdapter |
                                      +- OMPAdapter     -+
                                      -> SSE sanitiser (:20129) -> 9Router (:20128) -> model LLM
```

Repo: https://github.com/bayz-dik/AstroZ

## Jalankan

```bash
/root/AstroZ/run.sh            # 9Router + SSE sanitiser + UI :8799, buka browser
/root/AstroZ/run.sh 8799 --foreground
```

Buka dari HP: `http://<ip-lan>:8799/` (run.sh mencetak URL-nya, dan
`termux-open-url` dipakai otomatis kalau tersedia).

Supaya tidak mati sendiri:

```bash
cd /root/AstroZ && /usr/local/lib/hermes-agent/venv/bin/python watchdog.py --loop --interval 30
```

Watchdog memeriksa port dengan TCP connect sungguhan, bukan `ss` (di proot
container ini `ss` tidak melaporkan socket yang listening, jadi pengecekan
berbasis `ss` akan menganggap semua layanan mati).

## Yang bisa dilakukan dari UI

Lima tab, diurutkan sesuai pemakaian harian:

| Tab | Isi |
|---|---|
| Beranda | sisa setup (3 langkah), kirim tugas (workflow otomatis/kecil/sedang/besar), tugas terakhir, aktivitas langsung |
| Tugas | daftar tugas + detail: rencana, catatan penilaian, jejak langkah per worker |
| Model | keadaan gateway, pilih satu model untuk semua, daftar model (cari + filter yang sudah teruji hidup), API key, perkakas worker |
| Perkakas | tiga segmen: Berkas (tree + isi file), Perubahan (status git, diff, simpan commit), Tes (jalankan test) |
| Log | catatan kejadian, disaring per jenis, riwayat dimuat ulang setiap saringan berubah |

Alur model: **tambah model di 9Router -> Muat daftar model -> pilih -> Terapkan
ke semua**. Satu klik menulis model yang sama ke Hermes dan keempat worker.

## API (dipakai UI dan plugin Hermes)

```
GET  /api/state                     ringkasan gateway/worker/task/project
GET  /api/events?replay=N           SSE feed (realtime)
GET  /api/events/recent?limit=&kind=
POST /api/gateway/sync?apply=0|1    baca model dari 9Router (+ apply)
POST /api/gateway/probe             tes model mana yang benar-benar menjawab
GET  /api/gateway/models?q=&limit=
POST /api/gateway/model             {model, apply_workers}
POST /api/gateway/key               {api_key}
POST /api/apply                     tulis model sekarang ke semua worker + Hermes
GET  /api/workers | POST /api/workers/{key} | POST /api/workers/{key}/probe
POST /api/tasks {prompt,workflow,workers,model} | GET /api/tasks | GET /api/tasks/{id}
GET  /api/project/tree | GET /api/project/file?path=
GET  /api/git | GET /api/git/diff | POST /api/git/commit {message}
POST /api/test
POST /api/config {project_dir|workflow}
```

## Arah desain UI

Dibuat dengan aturan antislop (filter, bukan penentu gaya). Arah yang dipakai:

- **Sasaran**: alat kerja pribadi untuk mengoperasikan tim koding dari HP, sering
  dipakai satu tangan sambil jalan. Bukan landing page, bukan produk yang dijual.
- **Bahasa visual**: tenang dan jelas. Latar navy gelap (bukan hitam murni),
  dua warna inti plus satu aksen hijau untuk aksi utama dan status hidup.
- **Tipografi**: IBM Plex Sans untuk teks (bentuknya netral dan enak dibaca di
  layar kecil), JetBrains Mono hanya untuk keluaran teknis (log, diff, JSON),
  bukan untuk judul.
- **Dial**: ENERGY 1 / RHYTHM 1 / MOTION 1. Seragam dan tenang memang pilihan,
  bukan kebetulan: yang dibutuhkan kecepatan baca dan target sentuh besar.
- **Kontras**: setiap pasangan warna dihitung, bukan dikira-kira. Teks normal
  minimal 4.5:1, tepi komponen interaktif minimal 3:1.
- **Navigasi**: bottom nav 5 tujuan dengan target 56px, jadi semua yang sering
  dipakai dalam jangkauan jempol.

## Workflow adaptif

- **kecil**: 1 worker langsung -> test.
- **sedang**: rencana singkat (LLM) -> 1-2 worker -> test -> review Hermes.
- **besar**: dekomposisi -> worker paralel (batch `max_parallel`) -> diskusi
  antar worker -> test -> review Hermes -> ringkasan.

Dua loop perbaikan (bukan status akhir):

- test merah -> `_fix_failure` kirim output test ke worker lain -> test ulang
  (`fix_rounds`).
- review FAIL -> `_fix_review` kirim daftar issue dari reviewer ke worker lain ->
  review ulang, tapi hanya kalau worker benar-benar mengubah file
  (`fix_review_rounds`). Ini penting: test hijau tidak berarti tugas terpenuhi,
  worker bisa lulus test buatannya sendiri sambil melanggar permintaan asli
  (contoh nyata: diminta isi file persis tanpa newline, worker menambah newline
  dan test-nya sendiri tetap hijau).

Planner memakai model gateway; kalau gateway tidak bisa menjawab, rencana diisi
heuristik supaya tugas tetap jalan (tidak pernah gagal karena planner).

## Pemilihan worker (hemat dulu, mahal belakangan)

`workflow.worker_order` + `workflow.worker_cost` di team.yaml menentukan siapa
yang mengerjakan apa:

```yaml
worker_order: [omp, opencode, codex, claude]
worker_cost:  {omp: 0.01, opencode: 0.02, codex: 0.05, claude: 0.45}
```

- **Subtask** mengikuti `worker_order` (termurah lebih dulu).
- **Repair round** (test merah / review FAIL) memakai worker termurah yang belum
  menyentuh tugas itu. Perbaikan kecil tidak perlu request Claude $0.45.
- **Tugas `besar`**: kalau planner menaruh semua subtask di worker yang sama,
  mereka disebar round-robin. Diskusi antar-agent hanya berguna kalau CLI-nya
  memang berbeda.
- Tab Model menampilkan `Pilihan ke-N · ~$X per tugas` per worker supaya
  urutannya kelihatan dari UI.

Worker mahal tetap terpakai: kalau semua worker murah gagal, `_pick_workers`
tetap mengembalikan seluruh pool terpasang dan eskalasi tetap bisa sampai claude.

## Konfigurasi worker (format beda-beda, sudah diinspeksi)

| Worker | File konfigurasi | Cara jalan |
|---|---|---|
| claude | `~/.claude/settings.json` (`env.ANTHROPIC_BASE_URL`, `ANTHROPIC_AUTH_TOKEN`, `ANTHROPIC_DEFAULT_*_MODEL`) | `claude -p <task> --model <m> --output-format json --dangerously-skip-permissions` |
| codex | `~/.codex/config.toml` (`[model_providers.9router]`, `wire_api = "responses"`) | `codex exec -m <m> -c model_provider="9router" -c approval_policy="never" <task>` |
| opencode | `~/.config/opencode/opencode.json` (`provider.9router` + `model`) | `opencode run --auto --model 9router/<m> <task>` |
| omp | `~/.omp/agent/models.yml` (`providers.9router` -> baseUrl/apiKey/models[]) | `omp -p <task> --model 9router/<m> --auto-approve --no-session` |

Catatan penting yang sudah dipelajari dari lingkungan ini:

- [CC] menolak `--dangerously-skip-permissions` sebagai root kecuali
  `IS_SANDBOX=1` diset (ini container).
- Codex CLI 0.154 ke atas tidak lagi menerima `wire_api = "chat"`, pakai
  `"responses"`.
- `claude` menambahkan suffix `[1m]` ke model dari settings.json, jadi selalu
  kirim `--model` eksplisit.
- OMP tidak punya `config.json`; provider [OI]-compatible harus didaftarkan di
  `~/.omp/agent/models.yml` (skema: `providers.<name>.{baseUrl,apiKey,api,models[]}`).
  Tanpa itu `omp --model <gateway-model>` menjawab `Model "..." not found`, dan
  `OPENAI_BASE_URL` saja tidak cukup (hanya memengaruhi provider bawaan `openai`).
  Model harus ditulis `9router/<id>` supaya cocok dengan provider itu.
- OMP dijalankan unattended, jadi `--auto-approve` wajib. Kalau tidak, dia
  berhenti di prompt approval pertama dan tugas menggantung sampai timeout.
- 9Router menutup stream SSE dengan `data: [DONE]` **dua kali**; parser ketat
  (opencode) mati dengan `JSON parsing failed: Text: [DONE] [DONE]`. Karena itu
  ada `proxy.py` di :20129 yang meneruskan semuanya ke :20128 tapi membuang
  terminator kedua. Semua worker diarahkan ke :20129.
- 9Router butuh header `x-9r-cli-token` (sha256(machine-id + "9r-cli-auth" +
  auth/cli-secret)[:16]) untuk `/api/*`; `/v1/*` pakai `Authorization: Bearer <api key>`.
- Model gateway tidak semuanya hidup: pakai **Tes model yang hidup** untuk
  memfilter.
- Hermes menyimpan custom provider sebagai **list** (`custom_providers: [{name: ...}]`),
  jadi `hermes config set custom_providers.9router.base_url` tidak mengena.
  `apply_hermes()` menulis ulang entri itu langsung di config.yaml (dan mengisi
  `api_key` inline, karena `key_env` harus ada di environment).
- Port dan model itu dua hal terpisah: port pintu mana yang diketuk, model siapa
  yang diminta di dalam pintu itu. Satu model yang sama dipakai di semua pintu.

## Berkas

```
config.py         team.yaml loader + token 9Router + key dari sqlite
hub.py            event hub (JSONL + SSE fanout + tail file plugin)
gateway.py        klien 9Router: sync, apply, chat, probe, hermes config
adapters.py       4 adapter worker + apply_all
orchestrator.py   rencana -> worker (paralel) -> diskusi -> test -> review
project.py        tree, baca file, git, deteksi+jalan test
proxy.py          SSE sanitiser :20129 -> 9Router :20128 (buang [DONE] ganda)
server.py         FastAPI: UI + API + SSE
watchdog.py       jaga 9Router + sanitiser + UI tetap hidup
web/index.html    UI mobile-first (single file, no build)
team.yaml.example contoh konfigurasi (team.yaml asli berisi API key, tidak ikut repo)
tests/worker_smoke.py  tes langsung tiap worker CLI (pakai adapters.py)
tests/smoke.sh    smoke test end-to-end
runtime/          events.jsonl, tasks.json, model_meta.json (tidak ikut repo)
logs/             ui.log, 9router.log, proxy.log, smoke.log (tidak ikut repo)
workspace/        folder kerja proyek (repo git sendiri, tidak ikut repo ini)
```

## Plugin Hermes

`~/.hermes/plugins/astroz` menambahkan:

- tool `coding_team` (submit/status/tasks/models/model/sync/test),
- mirror aktivitas agent-loop ke feed UI,
- slash command `/team`, `/team-model`, `/team-tasks`, `/team-sync`, `/team-apply`.

Aktifkan setelah clone:

```bash
hermes plugins enable astroz
```

## Smoke test

```bash
/root/AstroZ/tests/smoke.sh          # 9Router -> worker langsung -> tugas end-to-end -> git -> SSE
MODEL=oc-prod/gemini-3.7-flash /root/AstroZ/tests/smoke.sh
```
