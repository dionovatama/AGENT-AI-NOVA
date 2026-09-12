"""
Security Testing — Command Injection pada linux.service_status.

Sesuai PRD section 43 (Testing > Security Testing > Arbitrary command
execution). service_name adalah SATU-SATUNYA input dari luar di antara
tool linux.* Milestone 4 (tool lain tidak menerima argumen bebas), jadi
ini titik paling kritis untuk diuji.

PENTING: Test ini TIDAK memerlukan koneksi SSH/VM aktif. Validasi
service_name terjadi di level Pydantic Field(pattern=...) — tahap
"Schema Validation" pada flow Tool Manager (PRD section 12) — yaitu
SEBELUM executor (dan karenanya SSH) pernah dipanggil sama sekali.
Kalau salah satu test ini gagal (payload berbahaya LOLOS validasi),
itu berarti ada request yang akan diteruskan mentah-mentah ke
`systemctl is-active {service_name}` di server target — kegagalan
kritis, bukan kegagalan kosmetik.
"""

import pytest

from app.main import app  # memicu registrasi seluruh tool linux.* + ping
from app.tools.manager import ToolValidationError, tool_manager
from app.tools.schemas import ToolRequest


# Setiap payload di sini HARUS ditolak. Jika salah satu lolos, tool
# akan mengirim command shell attacker-controlled ke SSH target.
INJECTION_PAYLOADS = [
    "ssh; rm -rf /",              # command separator (;)
    "ssh && whoami",              # AND chaining
    "ssh || whoami",              # OR chaining
    "ssh | whoami",               # pipe
    "ssh `whoami`",                # backtick command substitution
    "ssh $(whoami)",              # $() command substitution
    "ssh\nwhoami",                 # newline injection (command baru)
    "ssh\n",                       # trailing newline saja (regex $ edge case)
    "ssh; whoami\n",              # separator + trailing newline
    "../../../etc/passwd",         # path traversal characters
    "ssh -x",                     # flag injection lewat spasi
    "ssh > /tmp/pwned",            # output redirection
    "ssh < /etc/shadow",           # input redirection
    "a" * 129,                     # melebihi max_length (128)
    "",                            # string kosong (min_length implisit via required)
]


class TestServiceStatusInjectionDefense:
    @pytest.mark.parametrize("payload", INJECTION_PAYLOADS)
    @pytest.mark.asyncio
    async def test_malicious_service_name_rejected_before_ssh(self, payload):
        """
        Setiap payload berbahaya harus gagal di ToolValidationError
        (setara HTTP 422), TIDAK PERNAH sampai ke executor/SSH.
        """
        request = ToolRequest(
            tool_name="linux.service_status",
            arguments={"service_name": payload},
            confirmed=False,
        )
        with pytest.raises(ToolValidationError):
            await tool_manager.execute(request)

    @pytest.mark.asyncio
    async def test_valid_service_name_passes_schema_validation(self):
        """
        Kontrol negatif: pastikan whitelist TIDAK terlalu ketat sampai
        menolak nama service yang sah. Ini tidak menguji SSH (akan gagal
        di tahap koneksi jika VM tidak reachable dari lingkungan test),
        tapi memastikan tidak berhenti di ToolValidationError.
        """
        request = ToolRequest(
            tool_name="linux.service_status",
            arguments={"service_name": "sshd"},
            confirmed=False,
        )
        try:
            await tool_manager.execute(request)
        except ToolValidationError:
            pytest.fail("Nama service valid 'sshd' seharusnya lolos schema validation")
        except Exception:
            # Error lain (mis. SSH connection error karena VM tidak
            # reachable dari lingkungan CI) DITERIMA di test ini —
            # yang tidak boleh terjadi hanya ToolValidationError.
            pass
