# N.O.V.A Tools — Panduan Menambah Tool Baru

Dokumen ini menjelaskan cara menambah tool baru ke N.O.V.A: anatomi satu
tool, konvensi `ExecutionContext`/`device_id` (dipakai mulai dari
`mikrotik.*`), dan checklist sebelum PR/commit.

Referensi arsitektur: PRD section 12 (Tool Manager), section 13 (Tool
Schema), section 30 (Security Architecture).

---

## 1. Prinsip yang tidak boleh dilanggar

- **LLM tidak pernah memanggil executor langsung.** Semua eksekusi lewat
  `ToolManager.execute()` — Schema Validation → Authorization → Risk
  Assessment → Permission → Executor → Result.
- **Tool tidak boleh mengklaim sukses tanpa verifikasi nyata.** Kegagalan
  (koneksi, parsing, timeout) ditangkap eksplisit dan dikembalikan sebagai
  `success=False` + `error=...` — jangan biarkan exception mentah bocor ke
  API layer.
- **Zero Secret Exposure.** Credential (password, private key, token)
  tidak pernah masuk ke prompt LLM, response API, atau log. Kalau
  argumen/kembalian tool berpotensi memuat secret, itu tanggung jawab
  `app/security/sanitization.py` — bukan alasan untuk menaruh secret di
  tempat yang seharusnya tidak.
- **Structured output, bukan raw text dump.** LLM tidak boleh disuruh
  parsing teks mentah sendiri (lihat catatan desain `linux.network_info`
  soal `interfaces_raw` yang sengaja diganti jadi list terstruktur).
- **Tool yang menerima argumen bebas dari luar WAJIB divalidasi ketat**
  (regex whitelist di level Pydantic `Field(pattern=...)`), bukan sanitasi
  manual di dalam executor. Lihat `_SERVICE_NAME_PATTERN` di `linux.py`
  sebagai contoh yang sudah teruji lewat `test_linux_injection.py`.

---

## 2. Anatomi satu tool

Setiap tool terdiri dari 4 bagian, semua di satu file per kategori
(`linux.py`, `mikrotik.py`, `web.py`, dst):

```python
# 1. Input schema — apa yang boleh diminta LLM/user
class FooInput(BaseModel):
    target: str = Field(..., pattern=r"^[a-zA-Z0-9_.-]+$", max_length=64)

# 2. Output schema — apa yang dikembalikan ke LLM/user
class FooOutput(BaseModel):
    success: bool
    result: str | None = None
    error: str | None = None

# 3. Executor — logika nyata, SELALU async, SELALU tangkap exception
async def execute_foo(input: FooInput, ctx: ExecutionContext | None = None) -> FooOutput:
    try:
        ...
        return FooOutput(success=True, result=...)
    except SomeSpecificError as exc:
        return FooOutput(success=False, error=f"...: {exc}")

# 4. ToolDefinition — metadata yang dibaca Tool Manager
foo_tool = ToolDefinition(
    name="namespace.foo",
    description="...",
    input_model=FooInput,
    output_model=FooOutput,
    permission_level=PermissionLevel.READ,
    risk_level=RiskLevel.LOW,
    supported_platforms=["mikrotik"],
    requires_device=True,
    timeout_seconds=15.0,
    logging_policy=LoggingPolicy.RESULT_ONLY,
    executor=execute_foo,
)
```

Lalu daftarkan di `app/main.py`:
```python
tool_manager.register(foo_tool)
```

Penamaan tool: `<namespace>.<action>` — `linux.system_info`,
`mikrotik.interface_status`, `web.search`. Namespace menentukan platform
gate di `authorization.py` (`_TOOL_PLATFORM_MAP`).

---

## 3. `ExecutionContext` & `device_id` — WAJIB untuk tool berbasis device

Sejak MikroTik tools masuk, tool yang menyasar device nyata (MikroTik,
dan nanti Cisco) **tidak lagi baca koneksi dari `.env` langsung** seperti
`linux.*` (pola lama, dipertahankan apa adanya, tidak dipaksa migrasi).
Tool baru mengambil koneksinya dari `Device` + `Credential` yang
didaftarkan user lewat `POST /devices` / `POST /credentials`.

**Kapan pakai `requires_device=True`:**
- Tool menyasar satu device spesifik milik user (MikroTik, Cisco, dst).
- TIDAK dipakai untuk tool yang tidak device-specific (`web.*`) atau tool
  lama yang masih pola `.env` single-device (`linux.*`, `ping`).

**Setiap executor SEKARANG menerima parameter kedua opsional:**
```python
async def execute_foo(input: FooInput, ctx: ExecutionContext | None = None) -> FooOutput:
```
- Tool yang tidak butuh device (`ping`, `web.*`, `linux.*`) mengabaikan
  `ctx` sepenuhnya — signature berubah, logic TIDAK berubah.
- Tool `mikrotik.*` WAJIB pakai `ctx.device` dan `ctx.credential_plaintext`
  untuk connect. Kalau `requires_device=True` tapi request tidak
  menyertakan `device_id`, Tool Manager menolak SEBELUM executor
  dipanggil (pesan jelas: "tool ini butuh device_id").

**Apa isi `ExecutionContext`:**
```python
@dataclass
class ExecutionContext:
    user: User
    db: Session
    device: Device | None = None
    credential_plaintext: str | None = None  # hasil decrypt, hidup di memory doang
```
`credential_plaintext` diisi Tool Manager tepat sebelum executor
dipanggil (dataclass-nya ada di `app/tools/context.py`, field ini
`repr=False`), dan TIDAK PERNAH:
- ditulis ke `AuditLog` (sanitization.py sudah redact key `credential`,
  tapi jangan sengaja masukkan ke `request_metadata` juga)
- dikembalikan lewat `ToolResult.output`
- dilog dengan `logger.info`/`print` apa pun alasannya

> **Gap yang diketahui — jangan dianggap sudah aman:** saat ini TIDAK ada
> enkripsi/vault. `POST /credentials` menyimpan nilai secret apa adanya di
> kolom `secret_reference`, dan Tool Manager membacanya langsung sebagai
> `credential_plaintext` (lihat komentar di `manager.py`, blok "4.5 Device
> Resolution"). Migrasi ke secret manager / enkripsi-at-rest adalah pekerjaan
> terpisah. Untuk MikroTik API-SSL, verifikasi sertifikat juga sengaja
> dimatikan (`ssl.CERT_NONE`, lab saja) — lihat docstring `mikrotik.py`.

**Tenant isolation:** resolusi `device_id` -> `Device` SELALU difilter
`owner_id == current_user.id`. Device milik user lain harus terlihat
sebagai "tidak ditemukan", bukan 403 — supaya tidak membocorkan device
mana saja yang eksis di sistem (anti user/ID enumeration).

### Mendaftarkan device MikroTik (syarat agar `mikrotik.*` bisa jalan)

Default `POST /devices` adalah `port=22` dan `connection_type="ssh"` —
itu untuk Linux. Untuk MikroTik, isi eksplisit:

```json
{
  "name": "lab-mikrotik-01",
  "platform": "mikrotik",
  "host": "192.168.88.1",
  "port": 8728,
  "connection_type": "api",
  "credential_id": "<id dari POST /credentials>",
  "metadata": {"username": "admin"}
}
```

- `connection_type`: `"api"` (port 8728) atau `"api-ssl"` (port 8729). Nilai
  lain ditolak executor dengan pesan jelas (`success=False`), termasuk
  `"ssh"` yang merupakan default.
- `metadata.username` wajib; password diambil dari credential yang terpasang
  di device (`secret_reference`).
- Service `api` (atau `api-ssl`) harus aktif di RouterOS: `/ip service`.
- Panggil lewat `POST /tools/execute` dengan `device_id` di body. Tool
  `mikrotik.*` sengaja belum ada di allowlist tool-calling `/chat`.

---

## 4. Wrapping library sync (RouterOS API, dll)

Sebagian besar client library (`librouteros`, `ddgs`, `trafilatura`)
sync, sementara seluruh backend NOVA async. Pola wajib: bungkus
`asyncio.to_thread()`, JANGAN panggil langsung di dalam `async def`
(itu akan blocking seluruh event loop, bukan cuma request itu sendiri).

```python
def _system_info_sync(host: str, port: int, username: str, password: str) -> dict:
    with librouteros.connect(host=host, port=port, username=username, password=password) as api:
        return list(api.path("/system/resource"))[0]

async def execute_system_info(input: SystemInfoInput, ctx: ExecutionContext | None = None) -> SystemInfoOutput:
    try:
        raw = await asyncio.to_thread(
            _system_info_sync, ctx.device.host, ctx.device.port,
            ctx.device.device_metadata.get("username"), ctx.credential_plaintext,
        )
        return SystemInfoOutput(success=True, ...)
    except librouteros.exceptions.TrapError as exc:
        return SystemInfoOutput(success=False, error=f"RouterOS API error: {exc}")
    except OSError as exc:
        return SystemInfoOutput(success=False, error=f"Connection error: {exc}")
```

Fungsi `_xxx_sync` dipisah dari executor supaya bisa diuji langsung tanpa
mock `asyncio.to_thread` (pola sama dengan `_parse_interfaces` di
`linux.py` yang diuji murni tanpa SSH aktif).

---

## 5. Permission & Risk level — panduan singkat

| Permission | Kapan dipakai | Butuh `confirmed`? |
|---|---|---|
| `READ` | Baca-baca saja, tidak ubah state device | Tidak |
| `MODIFY` | Mengubah konfigurasi yang reversibel (buat VLAN, ubah IP) | Ya, `confirmed=true` |
| `HIGH_RISK` | Destruktif / berdampak luas (hapus config, ubah firewall besar, putus akses remote) | Ya + `ApprovalContext` terverifikasi (bukan `confirmed=true` doang — lihat `authorization.py`) |

| Risk | Contoh |
|---|---|
| `LOW` | ping, baca resource/interface |
| `MEDIUM` | baca data yang lebih sensitif (firewall rules, DHCP lease berisi MAC/hostname client) |
| `HIGH` | apa pun yang HIGH_RISK permission-nya |

Diagnostic tools (semua `mikrotik.*` batch pertama) = `READ` + `LOW`.
Tool konfigurasi (VLAN, NAT, dst — menyusul di milestone terpisah)
baru masuk `MODIFY`/`HIGH_RISK`.

---

## 6. Checklist sebelum tool dianggap selesai

- [ ] Input model pakai `Field(pattern=..., max_length=...)` untuk semua
      string bebas dari luar — tidak ada yang lolos ke command/API call
      mentah-mentah tanpa whitelist.
- [ ] Executor tidak pernah raise exception mentah — semua jalur gagal
      balik sebagai `success=False, error=...`.
- [ ] Kalau ada dua kondisi gagal yang beda arti (mis. "device tidak
      terinstall fitur X" vs "device error sungguhan"), dibedakan
      eksplisit seperti `linux.docker_status` (`docker_installed=False`
      vs `success=False`).
- [ ] Output structured (tidak ada field `*_raw` berisi dump teks mentah
      kalau bisa diparse).
- [ ] `requires_device=True` untuk tool yang menyasar device spesifik;
      executor pakai `ctx.device`/`ctx.credential_plaintext`, bukan
      baca `.env` langsung.
- [ ] Tidak ada credential yang masuk ke `logger.*`, `ToolResult.output`,
      atau `AuditLog.request_metadata`.
- [ ] Terdaftar di `main.py` (`tool_manager.register(...)`) — bukan cuma
      didefinisikan di file tool-nya; tool yang tidak di-register tidak
      muncul di `/tools/list` dan selalu 404.
- [ ] Dependency library baru sudah masuk `requirements.txt`.
- [ ] Test: minimal 1) parser/fungsi murni tanpa mock koneksi (kalau
      ada parsing), 2) mocked-connection test untuk jalur sukses +
      gagal, 3) kalau ada input bebas dari luar → test injection
      (reuse `INJECTION_PAYLOADS` polanya, jangan duplikasi daftar).

---

## 7. Contoh yang bisa dicontek

- Tool sederhana tanpa device, tanpa argumen: `ping_tool` (`network.py`)
- Tool dengan argumen bebas + whitelist regex: `linux.service_status`
- Tool yang membedakan "fitur tidak ada" vs "error sungguhan":
  `linux.docker_status`
- Tool yang wrap library sync: `web.search` (`web.py`, `asyncio.to_thread`)
- Tool berbasis device (`ExecutionContext`, `device_id`): `mikrotik.*`
  (lihat `mikrotik.py`)