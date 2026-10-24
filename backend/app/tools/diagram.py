"""
Diagram Tool — memberi NOVA kemampuan menjelaskan dengan ilustrasi.

LLM menulis kode Mermaid (teks sintaks sederhana), backend memvalidasi
ketat, frontend yang menggambar. LLM TIDAK menulis SVG/HTML mentah —
SVG dari LLM bisa memuat <script>/onload dan butuh sanitizer rumit;
Mermaid + validasi + render 'strict' jauh lebih kecil permukaan
serangannya (PRD section 31: output LLM = untrusted).

Permission level : READ  (tidak menyentuh sistem apa pun, murni
                          memvalidasi & mengembalikan teks)
Risk level        : LOW

Lapisan pertahanan:
1. Di sini (backend): batas panjang, hanya tipe diagram yang di-allowlist,
   tolak directive %%{...}, click/link (callback & URL), tag HTML selain
   <br>, javascript:/data: URI, atribut on*=, karakter kontrol.
2. Frontend: mermaid securityLevel='strict', htmlLabels dimatikan, hasil
   SVG ditampilkan lewat <img src="data:...">, bukan innerHTML — script
   di dalam SVG tidak dieksekusi bila dimuat lewat <img>.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.tools.schemas import (
    LoggingPolicy,
    PermissionLevel,
    RiskLevel,
    ToolDefinition,
)

MAX_CODE_CHARS = 4000

# Hanya tipe diagram yang relevan untuk penjelasan teknis. Tipe lain
# (gitGraph, c4, dll) sengaja tidak diizinkan — tambah belakangan bila perlu.
_ALLOWED_DIAGRAM_TYPES = (
    "flowchart",
    "graph",
    "sequenceDiagram",
    "stateDiagram-v2",
    "stateDiagram",
    "erDiagram",
    "classDiagram",
)

_FORBIDDEN_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"%%\s*\{"), "directive %%{...} tidak diizinkan"),
    # Sintaks Mermaid: 'click NodeId ...' (callback/URL) dan, di sequence
    # diagram, 'link(s) Actor: ...'. Sengaja spesifik supaya node bernama
    # 'click'/'link' (mis. 'click --> B') tidak ikut tertolak.
    (re.compile(r"^\s*click\s+\w", re.MULTILINE), "click (callback/URL) tidak diizinkan"),
    (re.compile(r"^\s*links?\s+\w[^\n]*:", re.MULTILINE), "link/links tidak diizinkan"),
    # Tag HTML apa pun selain <br>. '<-->' / '<<->>' (panah) aman karena
    # setelah '<' bukan huruf.
    (re.compile(r"<\s*/?\s*(?!br\b)[a-zA-Z!?]"), "tag HTML tidak diizinkan"),
    (re.compile(r"javascript\s*:", re.IGNORECASE), "javascript: tidak diizinkan"),
    # Hanya data URI sungguhan (data:<mime>/<sub>), bukan kata 'data:' di label.
    (re.compile(r"data\s*:\s*[a-z]+/[a-z0-9.+-]+", re.IGNORECASE), "data: URI tidak diizinkan"),
    (re.compile(r"\bon\w+\s*=", re.IGNORECASE), "atribut event handler tidak diizinkan"),
    (re.compile(r"\burl\s*\(", re.IGNORECASE), "url(...) tidak diizinkan"),
]

# Karakter kontrol selain \n, \r, \t.
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _first_code_line(code: str) -> str | None:
    for line in code.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("%%"):
            return stripped
    return None


class DiagramInput(BaseModel):
    title: str = Field(
        ..., min_length=1, max_length=120,
        description="Judul singkat diagram (teks biasa, tanpa HTML).",
    )
    kind: Literal["mermaid"] = Field(
        default="mermaid", description="Format diagram. Saat ini hanya 'mermaid'."
    )
    code: str = Field(
        ..., min_length=1, max_length=MAX_CODE_CHARS,
        description=(
            "Kode Mermaid yang valid. Baris pertama harus tipe diagram: "
            "flowchart/graph, sequenceDiagram, stateDiagram-v2, erDiagram, "
            "atau classDiagram. Label pendek, tanpa HTML dan tanpa URL."
        ),
    )

    @field_validator("title")
    @classmethod
    def _title_plain_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("title tidak boleh kosong")
        if "<" in value or ">" in value or _CONTROL_CHARS.search(value):
            raise ValueError("title harus teks biasa (tanpa HTML/karakter kontrol)")
        return value

    @field_validator("code")
    @classmethod
    def _code_is_safe_mermaid(cls, value: str) -> str:
        if _CONTROL_CHARS.search(value):
            raise ValueError("code mengandung karakter kontrol")

        code = value.replace("\r\n", "\n").replace("\r", "\n").strip()
        if not code:
            raise ValueError("code tidak boleh kosong")

        first = _first_code_line(code)
        if first is None or not any(
            first == t or first.startswith(t + " ") or first.startswith(t + "\t")
            for t in _ALLOWED_DIAGRAM_TYPES
        ):
            raise ValueError(
                "baris pertama code harus tipe diagram yang diizinkan: "
                + ", ".join(_ALLOWED_DIAGRAM_TYPES)
            )

        for pattern, message in _FORBIDDEN_PATTERNS:
            if pattern.search(code):
                raise ValueError(message)

        return code


class DiagramOutput(BaseModel):
    success: bool
    title: str | None = None
    kind: str | None = None
    code: str | None = None
    error: str | None = None


async def execute_diagram_create(input: DiagramInput) -> DiagramOutput:
    """Input sudah divalidasi di Schema Validation (Tool Manager). Tidak
    ada I/O: mengembalikan kode yang sudah dinormalisasi untuk dirender
    frontend."""
    return DiagramOutput(
        success=True, title=input.title, kind=input.kind, code=input.code
    )


diagram_create_tool = ToolDefinition(
    name="diagram.create",
    description=(
        "Membuat diagram untuk mengilustrasikan penjelasan (topologi jaringan, "
        "alur troubleshooting, urutan interaksi, relasi entitas) dari kode "
        "Mermaid. Diagram ditampilkan ke user di bawah jawaban. Pakai hanya "
        "bila diagram benar-benar membantu, maksimal 1-2 per jawaban."
    ),
    input_model=DiagramInput,
    output_model=DiagramOutput,
    permission_level=PermissionLevel.READ,
    risk_level=RiskLevel.LOW,
    supported_platforms=["general"],
    timeout_seconds=5.0,
    logging_policy=LoggingPolicy.MINIMAL,
    executor=execute_diagram_create,
)
