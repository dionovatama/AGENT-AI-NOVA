"""
Chat endpoint with safe, offline MikroTik configuration generation.
"""
import re

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.database.models import User
from app.security.dependencies import get_current_user
from app.ai.model_router import TaskCategory
from app.ai.openrouter import ChatMessage, ChatCompletionResult, OpenRouterError, get_completion
from app.ai.tool_calling import NOVA_SYSTEM_PROMPT, get_completion_with_tools
from app.api.mikrotik_generator import (
    GeneratorRequest,
    generate_configuration,
)

router = APIRouter(prefix="/chat", tags=["chat"])


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=8000)
    category: TaskCategory = TaskCategory.GENERAL_CHAT
    use_tools: bool = False
    configuration_mode: str | None = None  # "file" or "direct", selected after confirmation


def _configuration_intent(message: str) -> bool:
    text = message.lower()
    asks_to_configure = re.search(
        r"\b(buatkan|buat|generate|bikinkan|hasilkan|siapkan|konfigurasikan|konfigurasi|atur|tambahkan|aktifkan|blokir|pasang|tolong|butuh|perlu|ingin|minta)\b",
        text,
    )
    mentions_config = re.search(
        r"\b(mikrotik|routeros|router\s+os|firewall|dhcp|nat|masquerade|filter|rule|router)\b",
        text,
    )
    asks_for_explanation = re.search(
        r"\b(jelaskan|jelasin|apa\s+itu|fungsi|pengertian|cara\s+kerja|bedanya|mengapa|kenapa)\b",
        text,
    )
    return bool(asks_to_configure and mentions_config and not asks_for_explanation)


def _configuration_from_message(message: str) -> GeneratorRequest:
    text = message.lower()
    modules: list[str] = []
    if re.search(r"\b(ip|alamat ip|lan|gateway)\b", text):
        modules.append("ip")
    if re.search(r"\b(dhcp|pool dhcp)\b", text):
        modules.extend(["ip", "dhcp"])
    if re.search(r"\b(nat|masquerade|internet sharing)\b", text):
        modules.append("nat")
    if re.search(r"\b(firewall|filter|blokir|block|proteksi)\b", text):
        modules.append("firewall")
    if not modules:
        modules = ["ip", "firewall"]
    modules = list(dict.fromkeys(modules))

    version_match = re.search(r"router\s*os\s*v?([67])|routeros\s*v?([67])", text)
    version = next((group for group in version_match.groups() if group), "7") if version_match else "7"
    cidr_match = re.search(r"\b((?:\d{1,3}\.){3}\d{1,3}/\d{1,2})\b", message)
    lan_match = re.search(r"(?:lan_interface|interface\s+lan)\s*[:=]\s*([A-Za-z][A-Za-z0-9_.-]{0,31})", message, re.I)
    wan_match = re.search(r"(?:wan_interface|interface\s+wan)\s*[:=]\s*([A-Za-z][A-Za-z0-9_.-]{0,31})", message, re.I)
    # Extract common interface names mentioned naturally, e.g. "ether1 dan ether5".
    mentioned_wans = list(dict.fromkeys(re.findall(
        r"\b(?:ether\d+|sfp\d+(?:-\d+)?|pppoe-out\d*|wan\d+)\b", text
    )))
    wan_interfaces = mentioned_wans or ([wan_match.group(1)] if wan_match else ["ether1"])

    return GeneratorRequest(
        routeros_version=version,
        modules=modules,
        lan_interface=lan_match.group(1) if lan_match else "bridge-lan",
        wan_interface=wan_interfaces[0],
        wan_interfaces=wan_interfaces,
        ip_cidr=cidr_match.group(1) if cidr_match else "192.168.88.1/24",
    )


@router.post("/completions", response_model=ChatCompletionResult)
async def chat_completions(
    payload: ChatRequest,
    current_user: User = Depends(get_current_user),
):
    # First ask the user which execution path they want. The original request
    # is preserved by the frontend and resubmitted with configuration_mode.
    if payload.configuration_mode is None and _configuration_intent(payload.message):
        return ChatCompletionResult(
            content="Baik, Tuan. Konfigurasi ini ingin diproses dengan cara apa?",
            model_used="nova-configuration-router",
            category=TaskCategory.CONFIGURATION_GENERATION,
            used_fallback=False,
            tools_used=[],
            generated_files=[],
            configuration_choice=True,
        )

    if payload.configuration_mode == "direct":
        return ChatCompletionResult(
            content=(
                "Mode konfigurasi langsung belum tersedia pada instalasi ini. "
                "NOVA belum terhubung ke router untuk menerapkan perubahan. "
                "Pilih pembuatan file konfigurasi, atau hubungkan dan uji tool eksekusi router terlebih dahulu."
            ),
            model_used="nova-configuration-router",
            category=TaskCategory.CONFIGURATION_GENERATION,
            used_fallback=False,
            tools_used=[],
            generated_files=[],
        )

    # Configuration generation is an offline artifact flow, never a device action.
    if payload.configuration_mode == "file":
        try:
            request = _configuration_from_message(payload.message)
            generated = generate_configuration(request, current_user)
        except HTTPException as exc:
            return ChatCompletionResult(
                content=f"Permintaan konfigurasi belum bisa dibuat: {exc.detail}",
                model_used="nova-config-generator",
                category=TaskCategory.CONFIGURATION_GENERATION,
                used_fallback=False,
                tools_used=[],
                generated_files=[],
            )
        modules = ", ".join(generated.modules)
        return ChatCompletionResult(
            content=(
                f"Konfigurasi MikroTik RouterOS v{generated.routeros_version} berhasil disiapkan "
                f"untuk modul: {modules}. File tersedia di bawah untuk preview dan unduhan. "
                "Saya tidak terhubung ke router dan tidak menerapkan konfigurasi otomatis. "
                "Periksa nama interface, alamat IP, rule duplikat, dan backup sebelum mengimpor."
            ),
            model_used="nova-config-generator",
            category=TaskCategory.CONFIGURATION_GENERATION,
            used_fallback=False,
            tools_used=["mikrotik-config-generator.generate"],
            generated_files=[item.model_dump() for item in generated.files],
        )

    if payload.use_tools:
        try:
            result = await get_completion_with_tools(
                payload.message, payload.category,
                system_prompt=NOVA_SYSTEM_PROMPT, user=current_user,
            )
        except OpenRouterError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"AI Gateway gagal memproses request: {exc}",
            )
        return ChatCompletionResult(
            content=result.content,
            model_used=result.model_used,
            category=result.category,
            used_fallback=result.used_fallback,
            tools_used=result.tools_used,
            diagrams=result.diagrams,
        )

    messages = [ChatMessage(role="user", content=payload.message)]
    try:
        return await get_completion(messages, payload.category)
    except OpenRouterError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"AI Gateway gagal memproses request: {exc}",
        )
