# Boot splash video — spek yang disarankan

`components/BootSplash.tsx` mencari file berikut di folder ini
(urutan pencarian: webm dulu, lalu mp4 sebagai fallback):

- `nova-boot.webm` (opsional, biasanya kompresi lebih kecil)
- `nova-boot.mp4` (wajib kalau tidak ada webm)

Kalau kedua file ini belum ada, splash **tidak error/blank** — otomatis
jatuh ke `HudLoader` (ring SVG) selama ~4 detik lalu lanjut ke form
login. Jadi aman ditaruh sekarang meski videonya belum ada.

## Spek yang disarankan

- **Durasi**: 2–4 detik. Ini splash yang orang lihat setiap buka tab
  baru — jangan bikin mereka menunggu.
- **Resolusi**: 720p–1080p cukup, di-render di `max-h-[60vh] max-w-[85vw]`
  jadi tidak perlu 4K.
- **Background**: boleh solid gelap (`#0A0D12` / senada base-950 NOVA)
  supaya menyatu dengan halaman login — tidak perlu alpha channel/transparansi,
  MP4 H.264 standar sudah cukup.
- **Loop**: TIDAK perlu loop — splash ini sengaja cuma diputar sekali
  lalu otomatis hilang saat video selesai (`onEnded`).
- **Ukuran file**: usahakan di bawah ~3MB supaya tidak berasa berat di
  koneksi lambat. Kalau lebih besar, encode ulang dengan bitrate lebih
  rendah atau pangkas durasi.

## Cara ganti

Cukup taruh file dengan nama persis di atas ke folder ini
(`frontend/public/brand/`). Tidak perlu ubah kode apa pun —
`BootSplash.tsx` sudah menunjuk ke path ini.
