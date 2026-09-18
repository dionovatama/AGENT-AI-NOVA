"""
Tool Calling — jembatan antara OpenRouter function-calling dan Tool
Manager (PRD section 9: app/ai/tool_calling.py, sebelumnya direncanakan
tapi belum ditulis).

Kenapa file ini perlu ada secara terpisah dari openrouter.py dan
tools/manager.py (bukan digabung ke salah satunya):
- openrouter.py TIDAK BOLEH tahu apa-apa soal ToolManager/ToolRequest —
  dia murni AI Gateway generik.
- tools/manager.py TIDAK BOLEH tahu apa-apa soal OpenRouter/format
  function-calling — dia murni security boundary generik.
- File inilah satu-satunya tempat yang boleh menjembatani keduanya,
  supaya Core Principle tetap berlaku: LLM = untrusted decision maker.
  LLM HANYA boleh "meminta" tool dipanggil (lewat tool_calls terstruktur
  dari OpenRouter); backend (ToolManager.execute) yang benar-benar
  memutuskan & mengeksekusi lewat flow lengkap Schema Validation ->
  Authorization -> Risk Assessment -> Permission -> Executor -> Result.

Keputusan keamanan penting di file ini:
- HANYA tool ber-permission READ yang pernah diekspos ke LLM lewat
  jalur chat biasa ini. MODIFY/HIGH_RISK (mis. suatu saat linux.*
  yang mengubah state, atau tool konfigurasi MikroTik/Cisco) TIDAK
  pernah otomatis dipanggil dari chat — itu tetap harus lewat
  Configuration Flow eksplisit (PRD section 20: Preview -> Confirmation
  -> Apply), bukan tool-calling bebas di percakapan biasa.
- Per kategori task, hanya subset tool yang relevan yang diekspos
  (_CATEGORY_TOOL_ALLOWLIST) — bukan seluruh registry tool_manager
  sekaligus. Ini mencegah, misalnya, pertanyaan general_chat kasual
  ("cuaca hari ini?") diam-diam bisa memicu SSH ke VM lab hanya
  karena linux.system_info juga READ/LOW. Kategori lain (mis.
  troubleshooting, network_diagnostic) bisa ditambah ke allowlist
  belakangan sesuai kebutuhan nyata — bukan premature abstraction.
- Kegagalan eksekusi tool (ToolManagerError apa pun) TIDAK membuat
  seluruh request chat gagal — hasilnya dikembalikan ke model sebagai
  tool result role="tool" berisi error, supaya model bisa menjelaskan
  ke user apa yang terjadi (konsisten dengan prinsip "tidak pernah
  mengklaim sukses tanpa verifikasi").
- max_tool_iterations membatasi berapa kali model boleh bolak-balik
  minta tool sebelum dipaksa menjawab — mencegah loop tak terbatas.
"""

from __future__ import annotations

import json
import logging

from pydantic import BaseModel

from app.ai.model_router import TaskCategory
from app.config import settings
from app.database.models import User
from app.ai.openrouter import ChatMessage, OpenRouterError, _call_openrouter_raw
from app.tools.manager import ToolManagerError, tool_manager
from app.tools.schemas import PermissionLevel, RiskLevel, ToolRequest

logger = logging.getLogger("nova.ai.tool_calling")


# Kategori task -> daftar nama tool yang boleh diekspos ke LLM di kategori
# itu. Hanya tool READ yang boleh masuk sini (ditegakkan ulang secara
# runtime di _build_tool_schemas, bukan cuma diasumsikan dari daftar ini).
_CATEGORY_TOOL_ALLOWLIST: dict[TaskCategory, list[str]] = {
    TaskCategory.GENERAL_CHAT: ["web.search", "web.read_page"],
}

MAX_TOOL_ITERATIONS = 3
MAX_TOOL_CALLS_PER_TURN = 5

# Nama tool NOVA memakai titik ("web.search"), tapi banyak provider
# function-calling mewajibkan nama function match ^[a-zA-Z0-9_-]+$ (tanpa
# titik). Alias dua arah supaya konversi reversibel dan tidak perlu
# tool_manager tahu apa pun soal representasi ini.
def _to_function_name(tool_name: str) -> str:
    return tool_name.replace(".", "__")


def _from_function_name(function_name: str) -> str:
    return function_name.replace("__", ".")


class ChatWithToolsResult(BaseModel):
    """Structured output jalur tool-calling — terpisah dari ChatCompletionResult
    (Milestone 2) supaya endpoint lama tidak berubah kontraknya."""

    content: str
    model_used: str
    category: TaskCategory
    used_fallback: bool
    tools_used: list[str] = []

    model_config = {"protected_namespaces": ()}


def _build_tool_schemas(category: TaskCategory) -> list[dict]:
    """
    Bangun daftar tool (format OpenAI function-calling) untuk satu
    kategori, HANYA dari tool yang (a) ada di allowlist kategori ini
    DAN (b) benar-benar terdaftar di tool_manager DAN (c) permission
    level-nya READ DAN (d) risk level-nya bukan HIGH. Kalau salah satu
    syarat gagal, tool itu diam-diam tidak diekspos (fail-safe), bukan error.

    FIX-H: HIGH_RISK tool TIDAK PERNAH diekspos ke LLM lewat jalur
    conversational tool-calling ini, bahkan jika permission level-nya READ.
    """
    allowed_names = _CATEGORY_TOOL_ALLOWLIST.get(category, [])
    schemas: list[dict] = []

    for name in allowed_names:
        tool = tool_manager.get_tool(name)
        if tool is None:
            continue
        if tool.permission_level != PermissionLevel.READ:
            logger.warning(
                "Tool '%s' ada di allowlist kategori '%s' tapi permission "
                "level-nya bukan READ (%s) — tidak diekspos ke LLM.",
                name, category.value, tool.permission_level.value,
            )
            continue
        # FIX-H: Hard gate — HIGH_RISK tidak pernah masuk jalur conversational.
        if tool.risk_level == RiskLevel.HIGH:
            logger.error(
                "Tool '%s' ada di allowlist tapi risk level-nya HIGH — "
                "TIDAK DIEKSPOS ke LLM (HIGH_RISK tools require explicit "
                "Configuration Flow, bukan conversational tool-calling).",
                name,
            )
            continue

        schemas.append(
            {
                "type": "function",
                "function": {
                    "name": _to_function_name(tool.name),
                    "description": tool.description,
                    "parameters": tool.input_model.model_json_schema(),
                },
            }
        )

    return schemas


async def _execute_tool_call(
    function_name: str,
    arguments: dict,
    category: TaskCategory,
    user: User | None = None,
) -> dict:
    """
    Menjalankan satu tool call lewat ToolManager.execute() — SATU-SATUNYA
    jalur eksekusi, sama seperti request tool manual dari endpoint
    /tools/execute. confirmed selalu False di sini karena hanya tool
    READ yang pernah sampai ke titik ini (lihat _build_tool_schemas).

    FIX-A: user TIDAK BOLEH None. Jika None, ToolManager.execute() akan
    menolak via AuthorizationError — tidak ada bypass fake system user.

    FIX-O: Second-layer defense — verifikasi tool_name dari LLM ada di
    allowlist kategori ini sebelum meneruskan ke ToolManager. Ini mencegah
    LLM yang "nakal" meminta tool dari luar scope percakapan ini.
    """
    tool_name = _from_function_name(function_name)

    # FIX-O: Second-layer category allowlist check.
    allowed_names = _CATEGORY_TOOL_ALLOWLIST.get(category, [])
    if tool_name not in allowed_names:
        logger.warning(
            "LLM meminta tool '%s' yang TIDAK ADA di allowlist kategori '%s' — ditolak.",
            tool_name, category.value,
        )
        return {
            "success": False,
            "error": f"Tool '{tool_name}' tidak diizinkan untuk kategori ini.",
        }

    request = ToolRequest(tool_name=tool_name, arguments=arguments, confirmed=False)

    try:
        result = await tool_manager.execute(request, user=user)
    except ToolManagerError as exc:
        # Jangan gagalkan seluruh chat — kembalikan error terstruktur
        # ke model, biarkan model yang menjelaskan ke user.
        return {"success": False, "error": str(exc)}

    return result.model_dump()


async def _run_with_model(
    messages: list[ChatMessage],
    model: str,
    tool_schemas: list[dict],
    category: TaskCategory,
    user: User | None = None,
) -> tuple[str, list[str]]:
    """
    Loop tool-calling untuk SATU model tertentu (tidak menangani
    fallback — itu tanggung jawab caller). Melempar OpenRouterError
    kalau model ini gagal di iterasi mana pun.
    """
    tools_used: list[str] = []
    total_calls = 0

    for _ in range(MAX_TOOL_ITERATIONS):
        raw = await _call_openrouter_raw(messages, model, tools=tool_schemas or None)

        if not raw.tool_calls:
            return raw.content or "", tools_used

        # Simpan giliran assistant (termasuk tool_calls mentah, format
        # OpenAI) sebelum menambahkan hasil eksekusi masing-masing tool.
        messages.append(
            ChatMessage(
                role="assistant",
                content=raw.content,
                tool_calls=[
                    {
                        "id": call.id,
                        "type": "function",
                        "function": {
                            "name": _to_function_name(call.name),
                            "arguments": json.dumps(call.arguments),
                        },
                    }
                    for call in raw.tool_calls
                ],
            )
        )

        for call in raw.tool_calls:
            total_calls += 1
            if total_calls > MAX_TOOL_CALLS_PER_TURN:
                messages.append(
                    ChatMessage(
                        role="tool",
                        tool_call_id=call.id,
                        name=_to_function_name(call.name),
                        content=json.dumps(
                            {"success": False, "error": "Batas jumlah tool call per giliran tercapai."}
                        ),
                    )
                )
                continue

            output = await _execute_tool_call(call.name, call.arguments, category=category, user=user)
            tools_used.append(call.name)
            messages.append(
                ChatMessage(
                    role="tool",
                    tool_call_id=call.id,
                    name=_to_function_name(call.name),
                    content=json.dumps(output),
                )
            )

    # Iterasi habis tapi model masih belum memberi jawaban akhir —
    # paksa satu panggilan terakhir TANPA tools supaya model wajib menjawab.
    raw = await _call_openrouter_raw(messages, model, tools=None)
    return raw.content or "", tools_used


async def get_completion_with_tools(
    user_message: str,
    category: TaskCategory,
    system_prompt: str | None = None,
    user: User | None = None,
) -> ChatWithToolsResult:
    """
    Entry point utama untuk chat DENGAN tool-calling.

    PENTING -- beda dari get_completion() (Milestone 2): model yang
    dipakai di sini SENGAJA BUKAN get_primary_model(category)/model
    chat biasa. Model chat umum (mis. nvidia/nemotron-3.5-lightning:free
    untuk general_chat) terbukti TIDAK reliable untuk function-calling --
    diam-diam mengabaikan parameter 'tools' dan menjawab dari memori
    sendiri, alih-alih benar-benar memanggil tool (evidence: NOVA
    menjawab tanggal pelantikan presiden yang salah padahal web.search
    seharusnya mengembalikan tanggal yang benar).

    settings.tool_calling_model / settings.tool_calling_fallback_model
    dipilih backend secara eksplisit karena TERBUKTI mendukung
    function-calling (bukan asumsi) -- bukan dipilih user, konsisten
    dengan Core Principle bahwa backend yang berwenang menentukan
    kapabilitas eksekusi, bukan LLM/user.

    Sama seperti get_completion() dari sisi fallback (Primary -> gagal
    -> Fallback -> gagal -> Safe Error), tapi setiap model boleh
    melakukan beberapa putaran tool call sebelum menjawab akhir.

    FIX-A: user TIDAK BOLEH None. Tidak ada lagi fake system user.
    Jika user=None, tool execution akan ditolak oleh ToolManager via
    AuthorizationError. Caller (chat.py) wajib menyediakan current_user
    dari JWT dependency.
    """
    messages: list[ChatMessage] = []
    if system_prompt:
        messages.append(ChatMessage(role="system", content=system_prompt))
    messages.append(ChatMessage(role="user", content=user_message))

    tool_schemas = _build_tool_schemas(category)

    primary_model = settings.tool_calling_model
    try:
        content, tools_used = await _run_with_model(
            list(messages), primary_model, tool_schemas, category=category, user=user
        )
        return ChatWithToolsResult(
            content=content,
            model_used=primary_model,
            category=category,
            used_fallback=False,
            tools_used=tools_used,
        )
    except OpenRouterError as primary_error:
        logger.warning(
            "Model tool-calling primary '%s' gagal untuk kategori '%s': %s. Mencoba fallback.",
            primary_model, category.value, primary_error,
        )

    fallback_model = settings.tool_calling_fallback_model
    if fallback_model == primary_model:
        raise OpenRouterError(
            f"Model tool-calling primary '{primary_model}' gagal dan fallback model sama "
            f"dengan primary — tidak ada opsi lain."
        )

    try:
        content, tools_used = await _run_with_model(
            list(messages), fallback_model, tool_schemas, category=category, user=user
        )
        return ChatWithToolsResult(
            content=content,
            model_used=fallback_model,
            category=category,
            used_fallback=True,
            tools_used=tools_used,
        )
    except OpenRouterError as fallback_error:
        logger.error(
            "Model tool-calling fallback '%s' juga gagal untuk kategori '%s': %s",
            fallback_model, category.value, fallback_error,
        )
        raise OpenRouterError(
            f"Primary ('{primary_model}') dan fallback ('{fallback_model}') "
            f"model tool-calling sama-sama gagal untuk kategori '{category.value}'."
        ) from fallback_error
