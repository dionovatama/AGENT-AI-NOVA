"""
ExecutionContext — konteks eksekusi untuk tool berbasis device.

Dibuat oleh ToolManager (app/tools/manager.py, langkah 4.5 "Device
Resolution") HANYA untuk tool dengan ``requires_device=True`` (mis.
``mikrotik.*``), lalu diteruskan ke executor sebagai argumen kedua.
Tool lama (``ping``, ``linux.*``, ``web.*``) tidak memakainya sama sekali.
Lihat "N.O.V.A Tools — Panduan Menambah Tool Baru", section 3.

Aturan yang tidak boleh dilanggar:

- ``credential_plaintext`` hidup di memory saja selama satu eksekusi tool.
  Tidak boleh ditulis ke AuditLog, dikembalikan lewat ToolResult.output,
  atau dilog. Field ini sengaja ``repr=False`` supaya tidak ikut bocor
  kalau objek ctx ter-print / masuk traceback / masuk log secara tidak
  sengaja (Zero Secret Exposure, PRD section 29).
- ``device`` selalu sudah difilter ``owner_id == user.id`` oleh Tool
  Manager sebelum ctx dibuat (tenant isolation, PRD section 28) —
  executor tidak perlu (dan tidak boleh) menresolusi device sendiri.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from app.database.models import Device, User


@dataclass
class ExecutionContext:
    """
    Konteks eksekusi satu tool call terhadap satu device.

    ``user`` dan ``db`` bertipe Optional hanya supaya unit test executor
    bisa membuat ctx tanpa DB/user sungguhan (lihat tests/test_mikrotik.py).
    Di jalur produksi, ToolManager selalu mengisinya.
    """

    user: User | None
    db: Session | None
    device: Device | None = None
    # repr=False: jangan pernah tampil di repr()/log/traceback.
    credential_plaintext: str | None = field(default=None, repr=False)
