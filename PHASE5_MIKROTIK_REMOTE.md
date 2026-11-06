# Phase 5 — MikroTik over Relay (API-SSL, pin fingerprint)

Keputusan: kepercayaan sertifikat router = **pin fingerprint SHA-256** (bukan CA).

## Alur

```
tool / adapter (async)
  -> remote_api_socket(device, ctx)          app/network/remote_transport.py
       RelayTarget(device_id) ada?  tidak -> jalur lokal lama (tidak berubah)
                                    ya    -> relay saja, TIDAK pernah fallback langsung
       wajib: connection_type api-ssl, port di target.ports, tls_fingerprint terisi
  -> open_relay(...)                         Phase 4
  -> open_pinned_tls_socket(channel, fp)     app/network/relay_tls.py
       TLS di BACKEND (Agent hanya meneruskan byte terenkripsi)
       handshake -> hash DER cert -> bandingkan pin -> baru izinkan byte aplikasi
  -> soket blocking (socketpair) -> thread librouteros (login + perintah)
  -> thread selesai -> tls.aclose() -> channel ditutup
```

Jembatan thread↔async: `socket.socketpair()`. Sisi `app_sock` blocking untuk thread
librouteros; sisi `pump_sock` non-blocking dipompa oleh dua task di event loop
(`_tx`: lokal→TLS→channel, `_rx`: channel→TLS→lokal). Backpressure: `sock_sendall`
menunggu thread membaca; antrean `RelayChannel` yang penuh menutup sesi (Phase 4).

## Perubahan

- Migrasi `f60718293041`: kolom `relay_targets.tls_fingerprint` (nullable). Jalankan `alembic upgrade head`.
- `POST /agents/{id}/targets` menerima `tls_fingerprint` (`AA:BB:..`, `aabb..`, atau `sha256:..`; disimpan 64 hex huruf kecil). Respons ikut menampilkannya.
- `tools/mikrotik.py`: `_connect/_api_session/*_sync` menerima `sock=None`; semua tool `mikrotik.*` lewat `_run_on_device`.
- `network/adapters/mikrotik.py`: semua operasi lewat `_call` (lokal atau relay).
- Adapter/tool lokal: perilaku sama; tanpa `ctx.db` langsung jalur lokal.

## Tentang `CERT_NONE`

Jalur remote memakai `verify_mode=CERT_NONE` di `relay_tls.py` karena Python tidak bisa
memvalidasi rantai self-signed. Verifikasi sebenarnya = pin, dicek SEBELUM satu byte aplikasi
(termasuk password) dikirim. Tes `test_wrong_fingerprint_is_rejected_and_no_app_data_sent`
membuktikan server tidak menerima byte aplikasi saat pin salah. Jalur LOKAL lama (`CERT_NONE`
tanpa pin) tidak diubah.

## Syarat di router

- Service `api-ssl` aktif dengan sertifikat yang ditetapkan (tanpa sertifikat RouterOS pakai
  anonymous-DH: tidak ada yang bisa di-pin dan OpenSSL modern menolaknya).
- Ambil fingerprint SHA-256 dari sertifikat itu, daftarkan di target.
- Pin berubah (sertifikat diganti) -> koneksi ditolak sampai pin diperbarui. Belum ada endpoint
  update pin: hapus lalu buat ulang target.

## Status uji

- `tests/test_relay_tls.py` (11 tes, stdlib + cryptography): LULUS. Server TLS lokal nyata,
  klien soket blocking di thread: cocok diterima, tidak cocok ditolak, cert ditukar ditolak,
  non-TLS, timeout, EOF, tutup lokal, payload ~1 MB, close idempoten.
- `tests/test_remote_transport.py` dan tes pin di `test_agent_targets_api.py`: ditulis, BELUM
  dijalankan (butuh PostgreSQL + sqlalchemy).
- `_connect_over_socket` (impor `Api`, `SocketTransport`, `ApiProtocol`, `plain` dari
  librouteros 3.4.1) BELUM diuji terhadap librouteros asli.

## Masih terbuka

- [ ] Jalankan seluruh suite (`pytest`) dan `alembic upgrade head` di mesin dev.
- [ ] Uji dengan MikroTik lab + Agent sungguhan (satu-satunya bukti untuk `_connect_over_socket`).
- [ ] Endpoint update/rotasi pin; UI untuk memasukkan fingerprint.
- [ ] Multi-worker routing relay (masih process-local).
