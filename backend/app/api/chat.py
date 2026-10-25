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


def _configuration_intent(message: str) -> bool:
    text = message.lower()
    asks_to_create = re.search(
        r"\b(buatkan|buat|generate|bikinkan|hasilkan|siapkan|konfigurasikan|generatekan|butuh|perlu|ingin|minta)\b",
        text,
    )
    mentions_mikrotik = re.search(r"\b(mikrotik|routeros|router os)\b", text)
    mentions_config = re.search(r"\b(konfigurasi|config|firewall|dhcp|nat|rsc)\b", text)
    # Generic "file konfigurasi firewall" requests are treated as MikroTik
    # only because that is the generator currently integrated into chat.
    generic_config_file = re.search(r"\b(file\s+)?konfigurasi\b", text) and re.search(
        r"\b(firewall|dhcp|nat|router)\b", text
    )
    return bool(asks_to_create and mentions_config and (mentions_mikrotik or generic_config_file))


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
    lan_match = re.search(r"(?:interface\s*(?:lan)?|lan)\s*[:=]?\s*([A-Za-z][A-Za-z0-9_.-]{0,31})", message, re.I)
    wan_match = re.search(r"(?:interface\s*(?:wan)?|wan)\s*[:=]?\s*([A-Za-z][A-Za-z0-9_.-]{0,31})", message, re.I)

    return GeneratorRequest(
        routeros_version=version,
        modules=modules,
        lan_interface=lan_match.group(1) if lan_match else "bridge-lan",
        wan_interface=wan_match.group(1) if wan_match else "ether1",
        ip_cidr=cidr_match.group(1) if cidr_match else "192.168.88.1/24",
    )


@router.post("/completions", response_model=ChatCompletionResult)
async def chat_completions(
    payload: ChatRequest,
    current_user: User = Depends(get_current_user),
):
    # Configuration generation is an offline artifact flow, never a device action.
    if _configuration_intent(payload.message):
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
