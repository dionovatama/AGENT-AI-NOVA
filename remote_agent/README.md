# NOVA Remote Agent (Phase B — protokol Phase A)

Agent koneksi untuk Windows (juga bisa jalan foreground di Linux). Agent **membuka koneksi keluar** ke
backend NOVA lewat WebSocket aman, mendaftar, mengirim heartbeat, dan melaporkan status. Agent ini
**tidak** memindai jaringan, tidak terhubung ke router/switch, tidak menjalankan perintah, dan tidak
mengubah konfigurasi apa pun (remote execution bukan bagian dari Phase B).

```
NOVA Backend (FastAPI)  <--  wss://HOST/ws/agent/{agent_id}  <--  Windows Remote Agent
```

Sumber kebenaran protokol: `backend/app/agents/protocol.py` dan `manager.py`.

## Yang berubah dari versi 0.1.0 (legacy)

| | 0.1.0 (legacy) | 0.2.0 (Phase A) |
|---|---|---|
| Endpoint | `/agent/ws` | `/ws/agent/{agent_id}` |
| Autentikasi | `authenticate` dengan token statis dari `NOVA_AGENT_TOKENS_JSON` | `auth` + `protocol_version: 1` + `os` + `agent_version`; token per-agent dari `POST /agents` |
| Heartbeat | tanpa nomor urut | `seq` bertambah, ACK harus mengembalikan `seq` yang sama |
| Interval | dari config | dari pesan `registered` (server yang menentukan) |
| Shutdown | langsung putus | `bye` + close 1000 → status `offline` |
| Reconnect | backoff tidak pernah di-reset, semua error diperlakukan sama | backoff + jitter, reset setelah heartbeat pertama berhasil, kebijakan per close code |

Gateway legacy `/agent/ws` di backend **tidak diubah**, tetapi agent 0.2.0 tidak lagi memakainya.

### Migrasi agent yang sudah ada

Token statis lama **tidak diterima** protokol Phase A, dan config lama akan ditolak dengan pesan yang jelas.
Untuk tiap agent lama:

1. Buat agent baru di backend (user login): `POST /agents` → simpan `id` dan `token` (token hanya tampil sekali).
2. Jalankan ulang `nova-agent init` dengan `agent_id` dan token baru (menimpa config lama).
3. `nova-agent restart`.

Format file config tidak berubah (`server_url`, `agent_id`, `token`); key lama `heartbeat_interval_seconds`
masih boleh ada tetapi diabaikan.

## Instalasi Windows 10/11

PowerShell **sebagai Administrator**:

```powershell
cd remote_agent
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e ".[windows]"

nova-agent init --server-url https://YOUR-NOVA-HOST --agent-id YOUR-AGENT-UUID   # token diminta lewat prompt tersembunyi
nova-agent install-service      # startup otomatis saat boot
nova-agent start
nova-agent status
```

Service: `NOVARemoteAgent` ("NOVA Remote Agent"). Config: `%ProgramData%\NOVA\Agent\config.json`
(hanya SYSTEM dan Administrators). Log: `%ProgramData%\NOVA\Agent\logs\agent.log` (rotasi 2 MB × 5; token disamarkan).

Perintah:

| Perintah | Fungsi |
|---|---|
| `nova-agent init` | Tulis config. Token dibaca lewat prompt tersembunyi, atau `--token-stdin`. `--token` ada tapi **tidak disarankan** (terlihat di daftar proses dan riwayat shell). |
| `nova-agent run` | Jalankan di foreground dengan log ke konsol; Ctrl+C = shutdown bersih. |
| `install-service` / `uninstall-service` | Pasang (auto-start + restart otomatis bila proses crash) / hapus service. |
| `start` / `stop` / `restart` / `status` | Kelola service. `status` memakai `sc.exe query`. |

Menghapus:

```powershell
nova-agent stop
nova-agent uninstall-service
```

## Debian / Ubuntu (foreground)

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install .
printf '%s' "$NOVA_TOKEN" | nova-agent init --server-url https://YOUR-NOVA-HOST --agent-id YOUR-AGENT-UUID --token-stdin
nova-agent run
```

## Konfigurasi dan validasi

- `agent_id`: UUID v4 kanonik (huruf kecil/besar diterima, dinormalisasi). Selain itu ditolak.
- `token`: format `nova_agt_` + 43 karakter. Tidak pernah masuk ke URL, log, `repr`, atau pesan error.
- `server_url`: URL dasar backend (bukan endpoint WebSocket). **HTTPS/WSS wajib.** `http://`/`ws://` hanya untuk
  development dan butuh opt-in eksplisit: `nova-agent init --allow-insecure` (menulis `"allow_insecure": true`)
  atau env `NOVA_AGENT_ALLOW_INSECURE=1`. Kredensial, query, dan fragment di URL ditolak. Path prefix reverse
  proxy didukung (`https://host/nova`).
- Backend produksi memakai `AGENT_REQUIRE_TLS=true`; koneksi tanpa TLS akan ditolak server.
- Log level: env `NOVA_AGENT_LOG_LEVEL` (default `INFO`).

## Perilaku koneksi

1. Buka `wss://HOST/ws/agent/{agent_id}`, kirim frame `auth` pertama.
2. Validasi `registered`: `protocol_version`, `agent_id`, `connection_id`, `heartbeat_interval_seconds`,
   `heartbeat_timeout_seconds` (harus > interval), `server_time`. Pesan tidak valid → sesi diputus.
3. Heartbeat dengan `seq` 1, 2, 3 … tiap `heartbeat_interval_seconds`. ACK harus membawa `seq` yang sama; ACK
   salah → close 1002 + reconnect. Tidak ada ACK dalam `heartbeat_timeout − interval` detik → close 4408 + reconnect.
4. Frame biner, JSON rusak, pesan > 64 KiB, atau pesan tak dikenal diperlakukan aman (tidak crash).

### Kebijakan reconnect

Backoff eksponensial 2 → 4 → … → 60 detik (+ jitter hingga 25%), di-reset setelah heartbeat pertama yang valid.
Putusnya internet **tidak pernah** menghentikan agent; agent terus mencoba dengan backoff.

| Sinyal dari backend | Tindakan agent |
|---|---|
| `4401` auth gagal (token salah/dicabut, agent dihapus) | **Berhenti**, tanpa reconnect. Perbaiki token (`init`), lalu `restart`. Exit code 3. |
| `4009` digantikan / token di-rotate / agent dihapus | Retry **lambat** (≥ 120 dtk, naik hingga 15 mnt). Berhenti setelah 3 kali berturut-turut tanpa sesi stabil (≥ 10 mnt) — biasanya dua instance memakai kredensial yang sama. Exit code 4. |
| `4429` rate limit | Retry lambat (≥ 120 dtk, naik hingga 15 mnt). |
| `4400` protocol error | Retry lambat; berhenti setelah 5 kali berturut-turut. Exit code 5. |
| `1008`, `1003`, `1009` | Retry lambat. |
| `4408`, `1011`, `1001`, `1006`, lainnya | Backoff normal. |
| HTTP 403/lainnya saat handshake | Retry lambat. Backend menutup **sebelum accept** untuk UUID salah, TLS tidak ada, atau IP kena rate limit — Starlette mengubahnya menjadi HTTP 403, sehingga close code aslinya tidak terlihat oleh agent. |

### Shutdown bersih

`stop`/Ctrl+C: heartbeat dihentikan → kirim `bye` (jika sudah terdaftar dan koneksi masih hidup) → close 1000 →
task asyncio dibatalkan → event loop ditutup. Backend mencatat status `offline` (bukan `disconnected`).
Penghentian saat masih menyambung atau menunggu backoff langsung dihormati.

## Keamanan

- Token tidak ada di URL; hanya dikirim di frame `auth` pertama lewat TLS (sertifikat diverifikasi store sistem).
- Config ditulis dengan izin terbatas **sebelum** token ditulis (SYSTEM + Administrators di Windows, `0600` di POSIX),
  lalu diganti secara atomik.
- Log disamarkan (token terdaftar dan pola `nova_agt_…`, termasuk traceback).
- Batas pesan 64 KiB di sisi client; nilai timing dari server dibatasi (anti interval 0 / sangat besar).
- Service berjalan sebagai LocalSystem (default). Menjalankan sebagai akun berhak-rendah (mis. `NT AUTHORITY\LocalService`)
  mungkin dilakukan, tetapi ACL `config.json` harus diberi akses baca ke akun itu — belum diotomatisasi.
  DPAPI untuk penyimpanan token adalah peningkatan berikutnya dan sengaja belum ditambahkan.

## Provisioning di backend

Phase A: user membuat agent lewat `POST /agents` (token plaintext hanya di response itu; DB menyimpan hash).
`POST /agents/{id}/rotate-token` mencabut token lama dan memutus koneksi aktif. Lihat `backend/app/agents/README.md`
untuk deployment WSS (nginx, uvicorn `--proxy-headers`).

## Test

Tanpa dependensi tambahan (stdlib `unittest`; juga kompatibel dengan pytest):

```bash
cd remote_agent
python -m compileall -q nova_agent tests
python -m unittest discover -s . -t . -p "test_*.py" -v
```

`tests/test_backend_compat.py` menjalankan klien melawan `AgentConnectionManager` backend yang asli (in-process,
`FakeStore` milik backend) dan otomatis dilewati jika folder `backend/` tidak ada. Test ini **tidak** menguji
stack WebSocket nyata (`websockets` + Starlette) maupun Windows Service; keduanya perlu diuji manual:

1. Backend: `uvicorn app.main:app` + PostgreSQL, buat agent via `POST /agents`.
2. Agent: `nova-agent init` lalu `nova-agent run`; `GET /agents` harus menampilkan `online`.
3. Ctrl+C → status `offline`. Matikan jaringan → agent terus mencoba lagi dengan backoff.
4. Windows: `install-service`, `start`, `status`, `restart`, `stop`; periksa `agent.log` dan Event Viewer.
