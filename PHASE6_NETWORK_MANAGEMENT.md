# Phase 6 - Network Management Integration (dalam pengerjaan)

Basis kode: branch `chatbot` (sudah memuat Phase 5 dan chat history).

## Selesai di tahap ini (backend, bagian 1 dan 2)
- `GET /network/topology`: Agent, Device, relay target -> node + edge, status jujur, `issues` salah konfigurasi.
- `POST /network/devices/{id}/refresh`: probe jangkauan lewat Agent (relay + TLS + pin, tanpa login), throttle 5 dtk.
- Migrasi `h8b9c0d1e2f3`: `devices.reachability`, `last_checked_at`, `last_check_detail`.
- Device tanpa relay target tidak di-probe dari backend (menghindari SSRF/port-scan).

## Berikutnya
3. Halaman Network pakai data nyata (ganti data contoh + localStorage).
4. UI relay target (fingerprint, salin target_id, ganti pin).
5. Topology manual di database.
6. Discovery terotorisasi.
Celah chat history: backend belum memakai riwayat sebagai konteks model.
