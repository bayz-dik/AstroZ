# Adapter plugin universal

AstroZ bisa menerima capability dari tiga ekosistem yang bentuknya berbeda,
lalu menormalkannya ke satu bentuk internal sebelum diteruskan ke pekerja.

```
sumber plugin
    |
    v
adapters_plugin.py          (deteksi, baca, normalkan)
    |
    v
capability manifest         (skill / agent / command / hook / mcp / rule)
    |
    v
AstroZ
    |
    +--> plugins.skill_tautkan   -> skill ke folder yang dibaca pekerja
    +--> plugins.mcp_pasang      -> MCP lewat sistem MCP yang sudah ada
    +--> tulis agen              -> ~/.claude/agents, ~/.codex/agents, dan seterusnya
    |
    v
pekerja: claude, codex, opencode, omp
```

Orchestrator tidak diubah. Sistem skill lama dan sistem MCP lama tidak diubah:
adapter memanggil keduanya, tidak menggantikannya.

## Ekosistem yang dikenali

| ekosistem | penanda | yang dibaca |
|---|---|---|
| Claude Code Plugin | `.claude-plugin/plugin.json` | `skills/`, `agents/`, `commands/`, `hooks/`, `.mcp.json` |
| Codex Skill/Plugin | `.codex-plugin/plugin.json` | `skills/`, `agents/` (`.toml`), `hooks/`, `mcpServers` |
| Hermes Skill/Plugin | `plugin.yaml` | `provides_hooks`, `provides_tools`, `provides_commands`, skill yang menyertai |
| Agent Skills standar | `SKILL.md` di mana pun | setiap folder berisi `SKILL.md` |
| MCP | `.mcp.json` / `mcp.json` | semua server di dalam `mcpServers` |

Repo besar yang menampung beberapa plugin di dalamnya juga dikenali: kalau akar
repo tidak punya penanda, adapter mencari satu tingkat lebih dalam dan
menawarkan setiap plugin yang ditemukan (`plugin_dalam`).

## Empat status

Setiap capability punya satu status, dan tidak ada yang dibuang diam-diam.

| status | arti |
|---|---|
| `supported` | dipakai apa adanya |
| `converted` | dipakai setelah diterjemahkan ke bentuk lain |
| `skipped` | tidak dipakai, alasannya ditampilkan |
| `requires` | butuh alat lain di luar AstroZ, alasannya ditampilkan |

Contoh keputusan nyata:

- **Skill** selalu `supported` dan diterima keempat pekerja, karena keempatnya
  membaca folder `SKILL.md` yang sama.
- **Agen dengan kunci khusus Claude** (`model:`, `tools:`, `isolation:`,
  `color:`) jadi `converted`: kunci itu tidak punya padanan di Codex, OpenCode,
  dan OMP, jadi yang dipertahankan hanya nama dan keterangan sebagai aturan
  peran. Isinya diterjemahkan ke format tiap harness, bukan disalin mentah.
- **Perintah slash** jadi `converted`: bentuknya berbeda di tiap CLI, jadi
  naskahnya disimpan sebagai aturan, bukan didaftarkan sebagai perintah yang
  sebenarnya tidak akan jalan.
- **Hook** jadi `skipped`: hook dijalankan harness pemiliknya dan perintahnya
  memakai variabel lingkungan CLI itu sendiri (`CLAUDE_PLUGIN_ROOT`). Menyalinnya
  ke CLI lain akan menjalankan perintah yang gagal atau salah.
- **Plugin Hermes** jadi `requires`: hook dan tool-nya adalah kode Python yang
  berjalan di dalam Hermes, bukan sesuatu yang bisa dipakai pekerja.
- **Server MCP** selalu `supported` dan dipasang lewat `plugins.mcp_pasang`,
  dengan `${CLAUDE_PLUGIN_ROOT}` dan `${CLAUDE_PLUGIN_DATA}` sudah diganti jalur
  nyata supaya tidak mengandalkan variabel CLI lain.
- **Server MCP tanpa `command` maupun `url`** jadi `skipped`, bukan disalin
  sebagai entri kosong.
- **Paket yang bukan plugin** (misalnya program Python biasa) dilaporkan apa
  adanya: nol capability, dengan catatan yang menjelaskannya.

## API

```
GET    /api/capability              daftar paket yang pernah dipasang
POST   /api/capability/pratinjau    unduh dan baca, TIDAK memasang apa pun
POST   /api/capability/pasang       pasang ke pekerja yang kompatibel
DELETE /api/capability/{nama}       lepas tautan dan catatannya
```

Contoh:

```bash
# pratinjau: lihat isi sebelum memasang
curl -X POST http://127.0.0.1:8799/api/capability/pratinjau \
  -H 'Content-Type: application/json' \
  -d '{"url":"https://github.com/mem0ai/mem0","sub":"integrations/claude-code-plugin"}'

# pasang hanya skill dan MCP-nya
curl -X POST http://127.0.0.1:8799/api/capability/pasang \
  -H 'Content-Type: application/json' \
  -d '{"url":"https://github.com/mem0ai/mem0","sub":"integrations/claude-code-plugin","pilih":["skill","mcp"]}'
```

Bentuk sumber yang diterima: tautan repo GitHub, tautan folder di dalam repo,
`pemilik/repo`, atau jalur paket lokal di mesin ini.

## UI

Menu garis tiga -> **Pasang dari URL**. Isi tautan, tekan Pratinjau: AstroZ
menampilkan nama paket, jenisnya, penanda yang ditemukan, dan setiap capability
dengan statusnya. Dari situ pilih jenis yang mau dipasang, lalu tekan pasang.

## Alat luar

Tiga alat yang diintegrasikan punya venv sendiri di `tools/paket/<nama>`, bukan
di venv server:

```bash
bash tools/pasang_alat.sh          # semuanya
bash tools/pasang_alat.sh cognee   # satu saja
```

Dipisah karena aider mematok `numpy<2` yang tidak punya wheel untuk Python 3.14,
dan memasangnya bersama server pernah membuat venv server kehilangan berkas
paket lain.

Catatan lingkungan: di container proot ini `uv pip install` kadang tidak
menyalin sebagian berkas paket. `tools/perbaiki_venv.py` membandingkan
`*.dist-info/RECORD` dengan isi folder lalu mengambil yang hilang dari wheel.
