"""
Test untuk tool diagram.create (Mermaid).

Fokus: validasi input (allowlist tipe diagram + penolakan payload
berbahaya) dan jalur lewat ToolManager. Tidak ada I/O eksternal.
"""

import uuid

import pytest
from pydantic import ValidationError

from app.main import app  # noqa: F401 — memicu registrasi tool ke tool_manager
from app.database.models import User
from app.tools.diagram import MAX_CODE_CHARS, DiagramInput, execute_diagram_create
from app.tools.manager import ToolValidationError, tool_manager
from app.tools.schemas import PermissionLevel, RiskLevel, ToolRequest

FLOW = "flowchart TD\n  A[Client] --> B[Router]\n  B --> C[Internet]"


def _fake_user() -> User:
    return User(id=uuid.uuid4(), email="diagram-test@example.com", hashed_password="x", is_active=True)


class TestDiagramInputValid:
    @pytest.mark.parametrize(
        "code",
        [
            FLOW,
            "graph LR\n  A --> B",
            "sequenceDiagram\n  Client->>Router: SYN\n  Router-->>Client: SYN-ACK",
            "stateDiagram-v2\n  [*] --> Up\n  Up --> Down",
            "erDiagram\n  USER ||--o{ DEVICE : owns",
            "classDiagram\n  class Device\n  Device : +string name",
            "%% komentar boleh\nflowchart TD\n  A --> B",
            "flowchart LR\n  A <--> B",  # panah dua arah bukan tag HTML
            "flowchart TD\n  A[Baris 1<br/>Baris 2] --> B",  # <br> diizinkan
            "graph LR\n  click --> B",  # node bernama 'click' bukan directive
            "sequenceDiagram\n  A->>B: Data: 3 bytes",  # kata 'data:' di label
        ],
    )
    def test_valid_code_accepted(self, code):
        assert DiagramInput(title="Judul", code=code).code

    def test_code_is_normalized(self):
        result = DiagramInput(title=" Judul ", code="\r\nflowchart TD\r\n  A --> B\r\n")
        assert result.title == "Judul"
        assert result.code == "flowchart TD\n  A --> B"


class TestDiagramInputRejected:
    @pytest.mark.parametrize(
        "code",
        [
            "",
            "   ",
            "Halo ini bukan diagram",
            "gitGraph\n  commit",  # tipe tidak di-allowlist
            "flowchart TD\n  A[<script>alert(1)</script>] --> B",
            "flowchart TD\n  A[<img src=x onerror=alert(1)>] --> B",
            "flowchart TD\n  A[<b>tebal</b>] --> B",
            "%%{init: {'securityLevel': 'loose'}}%%\nflowchart TD\n  A --> B",
            "flowchart TD\n  A --> B\n  click A callback",
            "flowchart TD\n  A --> B\n  click A href \"https://evil.example\"",
            "sequenceDiagram\n  link Alice: Dashboard @ https://evil.example",
            "flowchart TD\n  A[javascript:alert(1)] --> B",
            "flowchart TD\n  A[data:text/html;base64,PHNjcmlwdD4=] --> B",
            "flowchart TD\n  A --> B[url(https://evil.example/x)]",
            "flowchart TD\n  A --> B\x00",
            "x" * (MAX_CODE_CHARS + 1),
        ],
    )
    def test_malicious_or_invalid_code_rejected(self, code):
        with pytest.raises(ValidationError):
            DiagramInput(title="Judul", code=code)

    @pytest.mark.parametrize("title", ["", "   ", "<b>x</b>", "a" * 121, "judul\x00"])
    def test_invalid_title_rejected(self, title):
        with pytest.raises(ValidationError):
            DiagramInput(title=title, code=FLOW)

    def test_unsupported_kind_rejected(self):
        with pytest.raises(ValidationError):
            DiagramInput(title="x", kind="svg", code=FLOW)


class TestDiagramTool:
    @pytest.mark.asyncio
    async def test_executor_returns_normalized_code(self):
        out = await execute_diagram_create(DiagramInput(title="T", code=FLOW))
        assert out.success is True
        assert out.kind == "mermaid"
        assert out.code == FLOW

    def test_registered_read_low_no_device_not_internal(self):
        tool = tool_manager.get_tool("diagram.create")
        assert tool is not None
        assert tool.permission_level == PermissionLevel.READ
        assert tool.risk_level == RiskLevel.LOW
        assert tool.requires_device is False
        assert tool.internal_only is False

    @pytest.mark.asyncio
    async def test_via_tool_manager_succeeds(self):
        request = ToolRequest(
            tool_name="diagram.create", arguments={"title": "T", "code": FLOW}, confirmed=False
        )
        result = await tool_manager.execute(request, user=_fake_user())
        assert result.success is True
        assert result.output["code"] == FLOW

    @pytest.mark.asyncio
    async def test_via_tool_manager_rejects_malicious_before_executor(self):
        request = ToolRequest(
            tool_name="diagram.create",
            arguments={"title": "T", "code": "flowchart TD\n  A[<script>x</script>] --> B"},
            confirmed=False,
        )
        with pytest.raises(ToolValidationError):
            await tool_manager.execute(request, user=_fake_user())
