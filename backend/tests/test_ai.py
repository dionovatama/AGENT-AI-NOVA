"""
Test untuk AI Gateway (Milestone 2).

Menggunakan mock terhadap httpx.AsyncClient.post — TIDAK memanggil
OpenRouter API sungguhan. Ini penting agar:
1. Test dapat dijalankan tanpa API key/credit OpenRouter.
2. Test cepat dan deterministik (tidak bergantung jaringan eksternal).
3. Fallback logic dapat diuji secara terisolasi untuk skenario gagal.
"""

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.ai.model_router import TaskCategory, get_primary_model, get_fallback_model
from app.ai.openrouter import ChatMessage, OpenRouterError, get_completion


def _mock_response(status_code: int, json_body: dict | None = None, text: str = ""):
    """Membuat objek httpx.Response tiruan untuk skenario tertentu."""
    request = httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions")
    if json_body is not None:
        return httpx.Response(status_code=status_code, json=json_body, request=request)
    return httpx.Response(status_code=status_code, text=text, request=request)


def _success_body(content: str = "Halo, ini jawaban dari model.") -> dict:
    return {"choices": [{"message": {"content": content}}]}


class TestModelRouter:
    def test_get_primary_model_returns_configured_value(self):
        model = get_primary_model(TaskCategory.GENERAL_CHAT)
        assert isinstance(model, str)
        assert len(model) > 0

    def test_all_categories_have_primary_model(self):
        # Memastikan tidak ada kategori yang lupa dipetakan.
        for category in TaskCategory:
            model = get_primary_model(category)
            assert model, f"Kategori {category} tidak punya model primary"

    def test_get_fallback_model_returns_configured_value(self):
        model = get_fallback_model(TaskCategory.TROUBLESHOOTING)
        assert isinstance(model, str)
        assert len(model) > 0


class TestOpenRouterFallback:
    @pytest.mark.asyncio
    async def test_primary_success_no_fallback_used(self):
        """Jika primary sukses, fallback tidak boleh dipanggil sama sekali."""
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = _mock_response(200, _success_body("Jawaban sukses"))

            result = await get_completion(
                [ChatMessage(role="user", content="Halo")],
                TaskCategory.GENERAL_CHAT,
            )

            assert result.content == "Jawaban sukses"
            assert result.used_fallback is False
            assert mock_post.call_count == 1  # hanya primary yang dipanggil

    @pytest.mark.asyncio
    async def test_primary_timeout_falls_back_successfully(self):
        """Primary timeout -> fallback dipanggil -> fallback sukses."""
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.side_effect = [
                httpx.TimeoutException("timeout"),
                _mock_response(200, _success_body("Jawaban dari fallback")),
            ]

            result = await get_completion(
                [ChatMessage(role="user", content="Halo")],
                TaskCategory.TECHNICAL_REASONING,
            )

            assert result.content == "Jawaban dari fallback"
            assert result.used_fallback is True
            assert mock_post.call_count == 2

    @pytest.mark.asyncio
    async def test_primary_rate_limited_falls_back(self):
        """Primary kena rate limit (429) -> fallback dicoba."""
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.side_effect = [
                _mock_response(429, text="rate limited"),
                _mock_response(200, _success_body("Fallback berhasil")),
            ]

            result = await get_completion(
                [ChatMessage(role="user", content="Halo")],
                TaskCategory.CODING,
            )

            assert result.used_fallback is True

    @pytest.mark.asyncio
    async def test_both_primary_and_fallback_fail_raises_safe_error(self):
        """
        Jika primary dan fallback SAMA-SAMA gagal, NOVA harus melempar
        error yang jelas — TIDAK BOLEH mengklaim sukses palsu.
        """
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.side_effect = [
                _mock_response(500, text="provider error"),
                _mock_response(500, text="provider error juga di fallback"),
            ]

            with pytest.raises(OpenRouterError):
                await get_completion(
                    [ChatMessage(role="user", content="Halo")],
                    TaskCategory.SUMMARIZATION,
                )

    @pytest.mark.asyncio
    async def test_malformed_response_treated_as_failure(self):
        """Response 200 tapi struktur JSON tidak sesuai harus dianggap gagal, bukan sukses."""
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.side_effect = [
                _mock_response(200, {"unexpected": "structure"}),
                _mock_response(200, _success_body("Fallback menyelamatkan")),
            ]

            result = await get_completion(
                [ChatMessage(role="user", content="Halo")],
                TaskCategory.TECHNICAL_REASONING,
            )

            assert result.used_fallback is True
            assert result.content == "Fallback menyelamatkan"

    @pytest.mark.asyncio
    async def test_empty_content_treated_as_failure(self):
        """Response 200 dengan content kosong bukan hasil valid."""
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.side_effect = [
                _mock_response(200, _success_body("")),
                _mock_response(200, _success_body("Ada isinya sekarang")),
            ]

            result = await get_completion(
                [ChatMessage(role="user", content="Halo")],
                TaskCategory.CONFIGURATION_GENERATION,
            )

            assert result.used_fallback is True
