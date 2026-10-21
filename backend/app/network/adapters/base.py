"""
Base Network Device Adapter (Vendor-Agnostic Interface).

Mendefinisikan antarmuka abstrak yang wajib diimplementasikan oleh setiap adapter
vendor (MikroTik, Cisco, dll) maupun adapter simulasi (Fake/Mock)
(PRD section 17, 18, 19).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

from app.network.models import DeviceStateSnapshot, NetworkOperation

if TYPE_CHECKING:
    from app.database.models import Device
    from app.tools.context import ExecutionContext


class NetworkDeviceAdapter(ABC):
    """Antarmuka vendor-agnostik untuk operasi konfigurasi dan pembacaan state."""

    @abstractmethod
    async def get_device_state(
        self, device: Device, ctx: ExecutionContext | None = None
    ) -> DeviceStateSnapshot:
        """Membaca state nyata perangkat (interfaces, ip_addresses, routes)."""
        pass

    @abstractmethod
    async def apply_operation(
        self, op: NetworkOperation, device: Device, ctx: ExecutionContext | None = None
    ) -> str:
        """
        Menerapkan satu operasi konfigurasi ke perangkat.
        Mengembalikan identifier objek unik yang dibuat di perangkat (misal ID MikroTik '*1A')
        yang wajib dicatat untuk keperluan inverse/rollback.
        """
        pass

    @abstractmethod
    async def remove_operation(
        self,
        op: NetworkOperation,
        object_id: str,
        device: Device,
        ctx: ExecutionContext | None = None,
    ) -> bool:
        """
        Menghapus objek yang sebelumnya dibuat berdasarkan object_id.
        Digunakan dalam rollback terbalik.
        """
        pass

    @abstractmethod
    async def verify_operation(
        self, op: NetworkOperation, device: Device, ctx: ExecutionContext | None = None
    ) -> bool:
        """
        Memverifikasi bahwa efek dari operasi benar-benar terwujud pada state nyata perangkat.
        """
        pass

    @abstractmethod
    def render_cli_preview(self, op: NetworkOperation) -> str:
        """
        Merender representasi teks CLI dari operasi sesuai sintaks vendor
        (deterministik, bukan buatan LLM).
        """
        pass
