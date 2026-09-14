# N.O.V.A — Operator Console (Frontend, Milestone 4 baseline)

GUI web awal untuk N.O.V.A, dibangun di atas backend Milestone 1–4
(auth, AI Gateway, Tool Manager, Linux Executor). Next.js 14 (App Router)
+ TypeScript + Tailwind, sesuai stack yang ditetapkan PRD §8/§34.

## Menjalankan

```bash
cd frontend
npm install
cp .env.local.example .env.local   # isi NEXT_PUBLIC_NOVA_API_BASE_URL
npm run dev
```

Backend NOVA (`backend/`) harus jalan di URL yang sama dengan
`NEXT_PUBLIC_NOVA_API_BASE_URL` (default `http://localhost:8000`).

## Yang nyata vs yang placeholder

| Halaman | Status | Terhubung ke |
|---|---|---|
| `/login` | Nyata | `POST /auth/register`, `POST /auth/login` |
| `/chat` | Nyata | `POST /chat/completions` (Model Router + fallback) |
| `/tools` | Nyata | `GET /tools/list`, `POST /tools/execute` |
| `/devices` | Placeholder | tidak ada endpoint backend — preview struktur data saja |
| `/audit` | Placeholder | `audit.py` backend baru nulis ke logger, belum ke DB/endpoint |
| `/settings` | Placeholder | Voice, Automation, Credential Mgmt, RBAC — fase-fase berikutnya |

Setiap panel placeholder diberi label fase PRD (`PlaceholderPanel`) dan
rujukan section PRD, supaya jelas ini bagian yang belum dikerjakan, bukan
bug atau lupa. Ini juga dimaksudkan supaya console tumbuh 1:1 mengikuti
milestone backend, bukan mendahului dengan UI yang mengklaim fitur yang
belum ada.

### Ketergantungan yang perlu diperhatikan

`lib/types.ts` berisi `KNOWN_TOOLS` — daftar bentuk input tiap tool,
disalin tangan dari `backend/app/tools/*.py` karena `GET /tools/list`
saat ini cuma mengembalikan nama tool (`list[str]`), bukan schema-nya.
Kalau ada tool baru didaftarkan di backend, tool itu akan muncul di
allowlist tapi TIDAK dapat form otomatis sampai `KNOWN_TOOLS` disinkronkan
manual — console menandainya secara eksplisit ("belum punya form di
console") alih-alih diam-diam menyembunyikannya. Perbaikan nyata untuk
ini: tambahkan endpoint `GET /tools/schema/{name}` di backend yang
mengembalikan `input_model` sebagai JSON schema.

## Design Notes

Referensi visual yang dikirim (dashboard AI generik: orb ungu, hero
"Ready to create something new?") sengaja TIDAK ditiru langsung — pola
itu adalah default template consumer-chat, bukan operator console untuk
infrastructure automation. NOVA menyasar teknisi (network engineer,
sysadmin, IT support — PRD §5), jadi arah desainnya:

- **Warna** — `base` (slate gelap, bukan hitam pekat generik) + `signal`
  (teal = aksi/aktif, hijau = READ/ok, amber = MODIFY/butuh konfirmasi,
  merah = HIGH_RISK/gagal). Warna status mengikuti makna permission
  system PRD §23, bukan dekorasi bebas.
- **Tipografi** — IBM Plex Sans untuk UI, IBM Plex Mono untuk data teknis
  (nama tool, hostname, JSON output, command). Mono di sini fungsional
  (ini benar-benar console yang menampilkan output command), bukan label
  hias.
- **Momen gerak tunggal** — `SystemPulse` (poll `/health` tiap 15 detik,
  titik animasi saat online) menggantikan hero orb generik: satu sinyal
  hidup yang jujur, bukan animasi dekoratif di semua tempat.
- **Placeholder** — bukan kartu "coming soon" pemasaran, tapi papan status
  yang menyebut fase PRD & section rujukan, konsisten dengan cara backend
  mencatat bug/keputusan di `NOVA_Milestone4_Linux_Executor_Log_FINAL.txt`.

## Struktur

```
frontend/
├── app/
│   ├── layout.tsx              # font + shell global
│   ├── page.tsx                # redirect -> /chat
│   ├── login/page.tsx
│   └── (console)/
│       ├── layout.tsx          # sidebar + system pulse, guard auth client-side
│       ├── chat/page.tsx
│       ├── tools/page.tsx
│       ├── devices/page.tsx    # placeholder
│       ├── audit/page.tsx      # placeholder
│       └── settings/page.tsx   # placeholder
├── components/
│   ├── Sidebar.tsx
│   ├── SystemPulse.tsx
│   ├── StatusBadge.tsx
│   ├── PlaceholderPanel.tsx
│   ├── chat/ (ChatWindow, CategoryPicker)
│   └── tools/ (ToolCard, ToolRunModal)
└── lib/
    ├── api.ts                  # fetch wrapper + JWT header
    ├── auth.ts                 # token storage (localStorage — lihat catatan keamanan di file)
    └── types.ts                # tipe + KNOWN_TOOLS registry
```

## Belum dikerjakan (disengaja, di luar scope commit ini)

- Auth guard masih client-side (`useEffect` redirect) — belum ada
  middleware/SSR-level protection. Cukup untuk development, tidak untuk
  production.
- Token disimpan di `localStorage`, bukan httpOnly cookie — lihat catatan
  di `lib/auth.ts`.
- Tidak ada test (unit/e2e) untuk frontend ini sama sekali — backend
  sudah punya budaya test ketat (pytest per milestone), frontend belum
  menyusul. Direkomendasikan sebelum dianggap "selesai" secara evidence-based.
