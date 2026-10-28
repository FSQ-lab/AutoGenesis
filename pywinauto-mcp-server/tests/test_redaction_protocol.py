"""Real Windows MCP protocol coverage for lossless SecretRef handling."""

import json
import os
import sys
from pathlib import Path

import pytest
from mcp.shared.memory import create_connected_server_and_client_session

from autogenesis_windows_mcp.server import WindowsMCP

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows driver modules")


class IdleSession:
    gen_code_id = None

    def start_tool_execution(self, tool_name):
        return True

    def finish_tool_execution(self, tool_name):
        pass

    async def get_main_window(self):
        raise RuntimeError("No UI in protocol acceptance")


@pytest.mark.anyio
async def test_protocol_resolves_ref_without_cross_request_redaction(monkeypatch, caplog):
    from autogenesis_windows_mcp.tools.common_tool import register_common_tools

    canary = "SYNTHETIC_WINDOWS_SECRET_REF_CANARY"
    monkeypatch.setenv("AUTOGENESIS_WINDOWS_PASSWORD", canary)
    server = WindowsMCP("secret-ref-regression")
    register_common_tools(server, IdleSession())
    transcript = []
    async with create_connected_server_and_client_session(server) as client:
        ordinary = await client.call_tool("app_wait", {"caller": "regression", "duration": 0, "step_raw": "application"})
        assert json.loads(ordinary.content[0].text) == {
            "status": "success", "data": {"duration": 0, "step_raw": "application"},
        }
        transcript.append(ordinary.model_dump(mode="json"))

        failed = await client.call_tool("enter_text", {
            "caller": "regression", "control_framework": "unsupported", "title": "Password",
            "content": {"$secret": "env:AUTOGENESIS_WINDOWS_PASSWORD"},
            "control_type": "Edit", "automation_id": "passwordInput", "need_snapshot": 0,
        })
        assert canary not in failed.model_dump_json()
        transcript.append(failed.model_dump(mode="json"))

        # Execution plaintext is call-local and cannot poison a later response.
        later = await client.call_tool("app_wait", {"caller": "regression", "duration": 0, "step_raw": canary})
        assert json.loads(later.content[0].text)["data"]["step_raw"] == canary
        transcript.append(later.model_dump(mode="json"))

    evidence = json.dumps({"protocol": transcript, "logs": caplog.text, "secret_ref": "env:AUTOGENESIS_WINDOWS_PASSWORD"})
    destination = os.environ.get("AUTOGENESIS_WINDOWS_EVIDENCE")
    if destination:
        root = Path(destination).resolve(strict=True)
        temporary = root / "secret-ref-protocol.json.tmp"
        temporary.write_text(evidence + "\n", encoding="utf-8")
        temporary.replace(root / "secret-ref-protocol.json")
