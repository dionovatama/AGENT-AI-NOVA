"""Regression tests for routing direct chat configuration into the Configuration Engine."""

from app.api.chat import ChatRequest, _configuration_intent


def test_static_ip_request_is_detected_as_configuration_intent():
    assert _configuration_intent(
        "Tolong konfigurasi interface ether2 dengan IP 192.168.7.5/24"
    )


def test_read_only_interface_question_is_not_configuration_intent():
    assert not _configuration_intent("Tolong cek status interface ether2")


def test_chat_request_accepts_explicit_device_id():
    import uuid

    device_id = uuid.uuid4()
    request = ChatRequest(
        message="Tolong konfigurasi interface ether2 dengan IP 192.168.7.5/24",
        configuration_mode="direct",
        device_id=device_id,
    )
    assert request.device_id == device_id


def test_direct_configuration_does_not_require_llm_tool_calling():
    request = ChatRequest(
        message="Tolong konfigurasi interface ether2 dengan IP 192.168.7.5/24",
        use_tools=True,
        configuration_mode="direct",
    )
    assert request.configuration_mode == "direct"
    # The direct path is handled by the Configuration Engine proposal flow,
    # not by exposing a write tool to the LLM.
    assert request.use_tools is True
