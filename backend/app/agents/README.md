# Remote Agent Backend (Phase A)

Sisi backend dari koneksi `Remote Agent -> WSS -> NOVA Backend`. Agent di
jaringan lokal user **membuka koneksi keluar**; backend tidak pernah
menghubungi jaringan lokal secara langsung.

## Struktur

| File | Peran | Bergantung pada |
|---|---|---|
| `manager.py` | Inti: auth, heartbeat, duplicate, sweeper, shutdown | stdlib saja |
| `protocol.py` | Format pesan, close code, parser ketat | stdlib saja |
| `states.py` | 5 state + `effective_status()` | stdlib saja |
| `tokens.py` | Generate/hash/verify token (constant-time) | stdlib saja |
| `store.py` | Kontrak `AgentStore` (semua tulis kondisional) | stdlib saja |
| `registry.py` | Socket yang dipegang proses ini | stdlib saja |
| `ratelimit.py` | Sliding-window limiter (auth gagal per IP, pesan per koneksi) | stdlib saja |
| `sql_store.py` | `AgentStore` di PostgreSQL | SQLAlchemy |
| `starlette_adapter.py` | Starlette `WebSocket` -> `SocketLike` | Starlette |
| `wiring.py` | Instance produksi dari `settings` | semua di atas |

`manager.py` sengaja bebas FastAPI/SQLAlchemy sehingga race antar-koneksi
diuji dengan store/socket palsu (`tests/test_agents_core.py`, tanpa DB).

## State

| State | Arti |
|---|---|
| `offline` | Belum pernah connect, atau agent pamit bersih (`bye` / close 1000, 1001) |
| `connecting` | Token valid & koneksi di-claim; `registered` belum terkonfirmasi |
| `online` | Terkonfirmasi, heartbeat segar |
| `disconnected` | Putus tanpa pamit: socket drop, heartbeat timeout, backend restart, worker crash |
| `error` | Handler backend gagal tak terduga (`last_error` terisi, sudah disanitasi) |

Tersimpan per agent: id, owner_id, name, os, agent_version, status,
last_heartbeat_at, last_connected_at, last_disconnected_at, created_at
(+ `connection_id`, `worker_id`, `token_hash`, `last_error`).

## Multi-worker tanpa Redis

PostgreSQL yang sudah ada menjadi sumber kebenaran. Tiga aturan:

1. **Kepemilikan = `connection_id`.** Setiap koneksi sukses autentikasi
   meng-claim baris agent (last-writer-wins). Semua tulis berikutnya
   (`mark_online`, heartbeat, `release`) memakai `WHERE connection_id = :mine`.
   Koneksi lama atau milik worker lain tidak bisa menimpa koneksi baru.
   **Claim divalidasi ulang secara atomik:** `claim_connection` mengunci baris
   (`SELECT ... FOR UPDATE OF agents`) dan, di transaksi yang sama, memastikan
   `token_hash` masih sama dengan hash yang baru diverifikasi manager serta owner
   masih aktif. REST rotate/delete mengunci baris yang sama, jadi keduanya
   terserialisasi: rotate commit duluan -> claim ditolak; claim commit duluan ->
   rotate me-NULL-kan `connection_id` sehingga koneksi itu ditolak di heartbeat
   berikutnya. Token yang sudah dicabut tidak pernah menghasilkan koneksi.
2. **Status dibaca lewat `effective_status()`**, bukan dari memori worker:
   `online`/`connecting` dengan heartbeat lebih tua dari
   `AGENT_HEARTBEAT_TIMEOUT_SECONDS` dilaporkan `disconnected`. Worker B tidak
   pernah menyimpulkan "offline" hanya karena socket-nya ada di worker A.
3. **Sweeper** (jalan di tiap worker, idempoten) menandai baris basi
   `disconnected` -- ini yang menangani worker yang crash. Koneksi hidup yang
   sempat tersapu pulih sendiri pada heartbeat berikutnya.

**Belum ada (disengaja):** mengirim *command* ke agent yang socket-nya ada di
worker lain. Itu butuh pub/sub (PostgreSQL `LISTEN/NOTIFY` atau Redis) dan
diputuskan terpisah saat fitur command masuk. Sampai itu, jalankan 1 worker
atau pakai sticky routing untuk jalur command.

Heartbeat juga ditolak (close 4009) jika owner agent dinonaktifkan.

Efek samping yang perlu diketahui: setelah token di-rotate / agent dihapus,
koneksi di **worker lain** baru tertutup pada heartbeat berikutnya (maks. satu
interval, default 30 dtk); koneksi di worker yang sama tertutup seketika.

## Keamanan

- Token tidak ada di URL; dikirim di frame `auth` pertama (timeout 10 dtk).
- Hanya hash SHA-256 yang disimpan; bandingkan dengan `hmac.compare_digest`,
  juga untuk agent yang tidak ada (hash dummy) agar timing tidak bocor.
- Semua kegagalan auth (agent tak ada, token salah, owner nonaktif) ->
  respons identik `4401 authentication failed`; alasan hanya di log server.
- Token tidak pernah masuk log/audit/`repr` (ada tes khusus).
- **Rate limiting** (per proses/worker, in-memory; `AGENT_AUTH_FAIL_*`,
  `AGENT_MAX_PENDING_AUTH_PER_IP`, `AGENT_MAX_MESSAGES_PER_WINDOW`):
  - kegagalan auth per IP (token salah, agent tak ada, owner nonaktif, token
    dicabut, frame rusak, timeout) dihitung; IP yang mencapai batas (default 10
    per 60 dtk) ditolak dengan close `4429` SEBELUM `accept` dan tanpa query DB;
    auth sukses tidak dihitung;
  - koneksi yang sudah di-accept tapi belum terautentikasi dibatasi per IP
    (default 20) agar tidak bisa menahan banyak socket sampai timeout;
  - pesan per koneksi terautentikasi dibatasi (default 20 per 10 dtk); heartbeat
    normal 1 per 30 dtk. Pelanggaran -> close `4429`, status `disconnected`.
  Dengan N worker, batas efektif per IP bisa sampai N x limit (limiter tidak
  dibagi antar proses). IP klien hanya benar di belakang proxy jika uvicorn
  memakai `--proxy-headers` dengan `--forwarded-allow-ips` yang tepat.
- Kegagalan auth **tidak** ditulis ke tabel `audit_logs` (supaya trafik
  tak terautentikasi tidak bisa membanjiri DB); hanya ke logger.
- TLS: `AGENT_REQUIRE_TLS` (otomatis `true` bila `APP_ENV=production`).

## Hubungan dengan gateway lama (`/agent/ws`)

`app/api/agent.py` (Phase 1: token statis dari `NOVA_AGENT_TOKENS_JSON`, dipakai
oleh `remote_agent/`) **tidak diubah** dan tetap aktif di `/agent/ws`. Phase A
menambah jalur terpisah `/ws/agent/{agent_id}` + REST `/agents` dengan token
per-agent di database. Gateway lama tidak punya rate limiting dan tidak memakai
kepemilikan koneksi DB; migrasi klien `remote_agent/` ke protokol Phase A dan
pensiun gateway lama adalah pekerjaan Phase B.

## Deployment WSS

TLS umumnya diterminasi di reverse proxy. Contoh nginx:

```nginx
location /ws/agent/ {
    proxy_pass http://127.0.0.1:8000;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Forwarded-For $remote_addr;
    proxy_read_timeout 3600s;   # lebih besar dari heartbeat timeout
}
```

Uvicorn harus mempercayai header proxy supaya `wss` terdeteksi:

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000 \
  --proxy-headers --forwarded-allow-ips="127.0.0.1" \
  --ws-max-size 65536 --ws-ping-interval 20 --ws-ping-timeout 20
```

Tanpa `--proxy-headers`, backend melihat `ws` dan akan menolak semua agent
saat `AGENT_REQUIRE_TLS=true`. `--ws-ping-*` mendeteksi TCP yang mati di
level protokol, melengkapi heartbeat aplikasi.

## Catatan untuk Phase B (Windows Agent)

- Reconnect dengan exponential backoff + jitter; **jangan** retry cepat pada
  close `4401`, `4429`, dan `4009`. `4009` berulang = dua instance agent memakai
  kredensial yang sama.
- Kirim `bye` + close 1000 saat service di-stop agar status jadi `offline`
  (bukan `disconnected`).
- Heartbeat tiap `heartbeat_interval_seconds` dari pesan `registered`.

## Menjalankan test

```bash
cd backend
alembic upgrade head                    # membuat tabel agents
pytest tests/test_agents_core.py tests/test_agents_security.py -v   # tanpa DB
pytest tests/test_agents_api.py -v      # butuh PostgreSQL aktif
```
