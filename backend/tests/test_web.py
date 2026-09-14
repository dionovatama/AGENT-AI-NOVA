"""
Test untuk web.search dan web.read_page (general-purpose Q&A tool).

Pola sama seperti test_linux_ssh.py: boundary eksternal (library
duckduckgo_search / trafilatura, yang keduanya melakukan network I/O
sungguhan) di-mock, supaya test cepat, deterministik, dan tidak
tergantung koneksi internet. Logika kita sendiri (parsing hasil,
error handling, truncation) tetap diuji sungguhan.
"""

from unittest.mock import patch

import pytest

from app.main import app  # memicu registrasi tool ke tool_manager saat import
from app.tools.manager import tool_manager
from app.tools.schemas import PermissionLevel, RiskLevel, ToolRequest
from app.tools.web import (
    WebReadPageInput,
    WebReadPageOutput,
    WebSearchHit,
    WebSearchInput,
    execute_web_read_page,
    execute_web_search,
)


class TestWebSearchAllowlist:
    def test_web_search_is_registered_at_startup(self):
        assert "web.search" in tool_manager.list_tools()

    def test_web_read_page_is_registered_at_startup(self):
        assert "web.read_page" in tool_manager.list_tools()


class TestWebSearchExecution:
    @pytest.mark.asyncio
    async def test_search_success_returns_structured_hits(self):
        fake_hits = [
            WebSearchHit(title="Judul A", url="https://a.example/1", snippet="Ringkasan A"),
            WebSearchHit(title="Judul B", url="https://b.example/2", snippet="Ringkasan B"),
        ]
        with patch("app.tools.web._search_sync", return_value=fake_hits):
            result = await execute_web_search(WebSearchInput(query="apa itu subnetting", max_results=2))

        assert result.success is True
        assert result.query == "apa itu subnetting"
        assert len(result.results) == 2
        assert result.results[0].url == "https://a.example/1"

    @pytest.mark.asyncio
    async def test_search_failure_never_leaks_raw_exception(self):
        """Kegagalan library eksternal (timeout, rate limit, dsb) harus
        dikembalikan sebagai success=False + error, bukan exception mentah."""
        with patch("app.tools.web._search_sync", side_effect=RuntimeError("network unreachable")):
            result = await execute_web_search(WebSearchInput(query="test", max_results=3))

        assert result.success is False
        assert result.error is not None
        assert "network unreachable" in result.error

    @pytest.mark.asyncio
    async def test_search_via_tool_manager_read_permission_no_confirmation_needed(self):
        with patch("app.tools.web._search_sync", return_value=[]):
            request = ToolRequest(
                tool_name="web.search",
                arguments={"query": "cuaca hari ini", "max_results": 3},
                confirmed=False,  # READ — tidak butuh confirmed=True
            )
            result = await tool_manager.execute(request)

        assert result.success is True
        assert result.permission_level == PermissionLevel.READ
        assert result.risk_level == RiskLevel.LOW

    @pytest.mark.asyncio
    async def test_search_query_too_long_rejected_by_schema(self):
        request = ToolRequest(
            tool_name="web.search",
            arguments={"query": "a" * 500},  # melebihi max_length=400
            confirmed=False,
        )
        from app.tools.manager import ToolValidationError

        with pytest.raises(ToolValidationError):
            await tool_manager.execute(request)

    @pytest.mark.asyncio
    async def test_search_empty_query_rejected_by_schema(self):
        request = ToolRequest(tool_name="web.search", arguments={"query": ""}, confirmed=False)
        from app.tools.manager import ToolValidationError

        with pytest.raises(ToolValidationError):
            await tool_manager.execute(request)


class TestWebReadPageExecution:
    @pytest.mark.asyncio
    async def test_read_page_success(self):
        fake_output = WebReadPageOutput(
            success=True,
            url="https://example.com/artikel",
            title="Judul Artikel",
            text="Isi artikel yang sudah dibersihkan dari HTML.",
            truncated=False,
        )
        with patch("app.tools.web._read_page_sync", return_value=fake_output):
            result = await execute_web_read_page(
                WebReadPageInput(url="https://example.com/artikel")
            )

        assert result.success is True
        assert result.title == "Judul Artikel"
        assert result.truncated is False

    @pytest.mark.asyncio
    async def test_read_page_unreachable_returns_explicit_failure(self):
        fake_output = WebReadPageOutput(
            success=False,
            url="https://unreachable.example/x",
            error="Gagal mengambil halaman (unreachable atau diblokir).",
        )
        with patch("app.tools.web._read_page_sync", return_value=fake_output):
            result = await execute_web_read_page(
                WebReadPageInput(url="https://unreachable.example/x")
            )

        assert result.success is False
        assert result.error is not None

    @pytest.mark.asyncio
    async def test_read_page_exception_never_leaks_raw(self):
        with patch("app.tools.web._read_page_sync", side_effect=RuntimeError("boom")):
            result = await execute_web_read_page(WebReadPageInput(url="https://example.com/x"))

        assert result.success is False
        assert "boom" in result.error

    @pytest.mark.asyncio
    async def test_read_page_invalid_url_rejected_by_schema(self):
        request = ToolRequest(
            tool_name="web.read_page",
            arguments={"url": "bukan-url-valid"},
            confirmed=False,
        )
        from app.tools.manager import ToolValidationError

        with pytest.raises(ToolValidationError):
            await tool_manager.execute(request)
