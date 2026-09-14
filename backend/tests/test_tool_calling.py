"""
Test untuk app/ai/tool_calling.py — jembatan LLM <-> Tool Manager.

Mock di dua boundary:
1. app.ai.openrouter._call_openrouter_raw — supaya tidak perlu OpenRouter
   API key/credit sungguhan, dan skenario tool_calls bisa dikontrol persis.
2. app.tools.web._search_sync / _read_page_sync — supaya tool yang benar-
   benar dieksekusi (lewat tool_manager.execute, BUKAN dipanggil manual)
   tidak melakukan network I/O sungguhan.

Ini penting: test di sini memverifikasi tool BENAR-BENAR lewat
ToolManager.execute() (Schema Validation -> Permission -> Executor),
bukan jalur pintas — konsisten dengan Core Principle PRD bahwa LLM
tidak pernah mengeksekusi apa pun secara langsung.
"""

from unittest.mock import patch

import pytest

from app.ai.model_router import TaskCategory
from app.ai.openrouter import OpenRouterError, RawAssistantMessage, ToolCallRequest
from app.ai.tool_calling import (
    _build_tool_schemas,
    _to_function_name,
    get_completion_with_tools,
)
from app.main import app  # noqa: F401 — memicu registrasi tool ke tool_manager
from app.tools.web import WebSearchHit


class TestBuildToolSchemas:
    def test_general_chat_exposes_web_tools_only(self):
        schemas = _build_tool_schemas(TaskCategory.GENERAL_CHAT)
        names = {s["function"]["name"] for s in schemas}
        assert names == {"web__search", "web__read_page"}

    def test_category_without_allowlist_gets_no_tools(self):
        schemas = _build_tool_schemas(TaskCategory.CODING)
        assert schemas == []

    def test_schema_has_valid_json_schema_parameters(self):
        schemas = _build_tool_schemas(TaskCategory.GENERAL_CHAT)
        search_schema = next(s for s in schemas if s["function"]["name"] == "web__search")
        params = search_schema["function"]["parameters"]
        assert "query" in params["properties"]


class TestGetCompletionWithTools:
    @pytest.mark.asyncio
    async def test_model_answers_without_calling_any_tool(self):
        with patch(
            "app.ai.tool_calling._call_openrouter_raw",
            return_value=RawAssistantMessage(content="Jawaban langsung, tanpa tool.", tool_calls=[]),
        ) as mock_raw:
            result = await get_completion_with_tools("Halo, apa kabar?", TaskCategory.GENERAL_CHAT)

        assert result.content == "Jawaban langsung, tanpa tool."
        assert result.tools_used == []
        assert result.used_fallback is False
        assert mock_raw.call_count == 1

    @pytest.mark.asyncio
    async def test_model_calls_web_search_then_answers(self):
        first_call = RawAssistantMessage(
            content=None,
            tool_calls=[
                ToolCallRequest(id="call_1", name="web.search", arguments={"query": "cuaca Jakarta"})
            ],
        )
        second_call = RawAssistantMessage(
            content="Berdasarkan hasil pencarian, cuaca Jakarta hari ini cerah.",
            tool_calls=[],
        )

        with patch(
            "app.ai.tool_calling._call_openrouter_raw",
            side_effect=[first_call, second_call],
        ), patch(
            "app.tools.web._search_sync",
            return_value=[WebSearchHit(title="Cuaca Jakarta", url="https://x.example", snippet="Cerah")],
        ):
            result = await get_completion_with_tools("Cuaca Jakarta hari ini?", TaskCategory.GENERAL_CHAT)

        assert "cerah" in result.content.lower()
        assert result.tools_used == ["web.search"]

    @pytest.mark.asyncio
    async def test_tool_execution_failure_does_not_crash_whole_chat(self):
        first_call = RawAssistantMessage(
            content=None,
            tool_calls=[ToolCallRequest(id="call_1", name="web.search", arguments={"query": "x"})],
        )
        second_call = RawAssistantMessage(
            content="Maaf, pencarian gagal, tapi saya tetap bisa membantu.",
            tool_calls=[],
        )

        with patch(
            "app.ai.tool_calling._call_openrouter_raw",
            side_effect=[first_call, second_call],
        ), patch(
            "app.tools.web._search_sync",
            side_effect=RuntimeError("network down"),
        ):
            result = await get_completion_with_tools("cari sesuatu", TaskCategory.GENERAL_CHAT)

        # Tool gagal secara eksplisit (success=False dikirim balik ke model),
        # bukan exception yang bocor sampai menggagalkan seluruh chat.
        assert result.content == "Maaf, pencarian gagal, tapi saya tetap bisa membantu."

    @pytest.mark.asyncio
    async def test_primary_fails_falls_back_successfully(self):
        with patch(
            "app.ai.tool_calling._call_openrouter_raw",
            side_effect=[
                OpenRouterError("primary timeout"),
                RawAssistantMessage(content="Jawaban dari fallback.", tool_calls=[]),
            ],
        ):
            result = await get_completion_with_tools("halo", TaskCategory.GENERAL_CHAT)

        assert result.used_fallback is True
        assert result.content == "Jawaban dari fallback."

    @pytest.mark.asyncio
    async def test_both_primary_and_fallback_fail_raises(self):
        with patch(
            "app.ai.tool_calling._call_openrouter_raw",
            side_effect=[OpenRouterError("primary gagal"), OpenRouterError("fallback juga gagal")],
        ):
            with pytest.raises(OpenRouterError):
                await get_completion_with_tools("halo", TaskCategory.GENERAL_CHAT)

    @pytest.mark.asyncio
    async def test_unregistered_category_gets_plain_chat_no_tools_offered(self):
        """Kategori yang belum ada di allowlist (mis. coding) tetap harus
        bisa chat biasa — hanya saja tanpa tools sama sekali dikirim ke model."""
        with patch(
            "app.ai.tool_calling._call_openrouter_raw",
            return_value=RawAssistantMessage(content="Ini kode Python-nya.", tool_calls=[]),
        ) as mock_raw:
            result = await get_completion_with_tools("Buatkan fungsi fibonacci", TaskCategory.CODING)

        assert result.content == "Ini kode Python-nya."
        # tools kwarg yang dikirim ke _call_openrouter_raw harus None/kosong.
        _, kwargs = mock_raw.call_args
        assert not kwargs.get("tools")


class TestFunctionNameConversion:
    def test_dot_converted_to_double_underscore(self):
        assert _to_function_name("web.search") == "web__search"
        assert _to_function_name("linux.system_info") == "linux__system_info"
