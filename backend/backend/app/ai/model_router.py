"""
Model Router.

Tanggung jawab: memetakan task category ke model OpenRouter yang akan
dipakai, berdasarkan konfigurasi (bukan hardcode).

Kategori task sesuai PRD:
    general_chat, technical_reasoning, troubleshooting,
    network_diagnostic, configuration_generation, coding, summarization

Model konkret ditentukan dari environment/config (app.config.settings),
sehingga riset dan pergantian model tidak memerlukan perubahan arsitektur.
"""

from enum import Enum

from app.config import settings


class TaskCategory(str, Enum):
    GENERAL_CHAT = "general_chat"
    TECHNICAL_REASONING = "technical_reasoning"
    TROUBLESHOOTING = "troubleshooting"
    NETWORK_DIAGNOSTIC = "network_diagnostic"
    CONFIGURATION_GENERATION = "configuration_generation"
    CODING = "coding"
    SUMMARIZATION = "summarization"


# Mapping category -> field di Settings. Menjaga satu tempat kebenaran
# dan menghindari if/elif panjang saat kategori baru ditambahkan.
_CATEGORY_TO_SETTING_FIELD: dict[TaskCategory, str] = {
    TaskCategory.GENERAL_CHAT: "general_chat_model",
    TaskCategory.TECHNICAL_REASONING: "technical_reasoning_model",
    TaskCategory.TROUBLESHOOTING: "troubleshooting_model",
    TaskCategory.NETWORK_DIAGNOSTIC: "network_diagnostic_model",
    TaskCategory.CONFIGURATION_GENERATION: "configuration_generation_model",
    TaskCategory.CODING: "coding_model",
    TaskCategory.SUMMARIZATION: "summarization_model",
}


def get_primary_model(category: TaskCategory) -> str:
    """Model utama untuk kategori task tertentu, dari konfigurasi."""
    field_name = _CATEGORY_TO_SETTING_FIELD[category]
    return getattr(settings, field_name)


def get_fallback_model(category: TaskCategory) -> str:
    """
    Model fallback jika primary gagal.

    Milestone 2: fallback bersifat global (satu model fallback untuk
    semua kategori). Bisa diperluas menjadi per-kategori di milestone
    berikutnya jika ada kebutuhan nyata — jangan premature abstraction.
    """
    return settings.fallback_model
