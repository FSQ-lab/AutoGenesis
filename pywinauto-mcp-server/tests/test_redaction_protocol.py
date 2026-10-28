"""Driver-free MCP protocol coverage of the real common tools and redaction."""

import json
import logging
import os
import uuid
from pathlib import Path

import pytest
from mcp.shared.memory import create_connected_server_and_client_session

from autogenesis_windows_mcp.security import remember_config_secrets
from autogenesis_windows_mcp.server import WindowsMCP
from autogenesis_windows_mcp.tools.common_tool import register_common_tools


class IdleSession:
    # app_wait needs only the recording/concurrency boundary; no UI is opened.
    gen_code_id = None

    def start_tool_execution(self, tool_name):
        return True

    def finish_tool_execution(self, tool_name):
        pass


@pytest.mark.anyio
@pytest.mark.parametrize("launch_arg", ["a", "status", "0"])
@pytest.mark.parametrize("control_identifier", ["password", "passwordbox", "passwordinput", "PASSWORDINPUT", "secretInput"])
async def test_common_tool_protocol_preserves_ordinary_fields_and_protects_credentials(launch_arg, control_identifier, caplog):
    credential_canary = uuid.uuid4().hex
    password_canary = uuid.uuid4().hex
    remember_config_secrets({"launch_args": [launch_arg], "credentials": {"api_key": credential_canary}})
    server = WindowsMCP("redaction-regression")
    register_common_tools(server, IdleSession())
    transcript = []
    with caplog.at_level(logging.INFO):
        async with create_connected_server_and_client_session(server) as client:
            ordinary = await client.call_tool("app_wait", {"caller": "regression", "duration": 0, "step_raw": "a"})
            assert not ordinary.isError
            assert json.loads(ordinary.content[0].text) == {"status": "success", "data": {"duration": 0, "step_raw": "a"}}
            transcript.append(ordinary.model_dump(mode="json"))
            # The real text tool fails before any driver operation. Its
            # password-control value must stay protected in later responses.
            password_error = await client.call_tool("enter_text", {
                "caller": "regression", "control_framework": "unsupported", "title": "",
                "content": password_canary, "control_type": "Edit", "automation_id": control_identifier,
                "need_snapshot": 0,
            })
            transcript.append(password_error.model_dump(mode="json"))
            for canary in (credential_canary, password_canary):
                protected = await client.call_tool("app_wait", {"caller": "regression", "duration": 0, "step_raw": canary})
                assert not protected.isError
                # Defer canary failure until after the session is closed so
                # pytest does not wrap it in a task-group BaseExceptionGroup.
                if canary not in protected.model_dump_json():
                    assert json.loads(protected.content[0].text) == {"status": "success", "data": {"duration": 0, "step_raw": "[REDACTED]"}}
                transcript.append(protected.model_dump(mode="json"))
    evidence = json.dumps({"protocol": transcript, "logs": caplog.text, "secret_scan": "passed", "ordinary_fields": "unchanged"})
    for canary in (credential_canary, password_canary):
        if canary in evidence:
            pytest.fail("Credential disclosed in protocol, logs, or evidence.", pytrace=False)
    destination = os.environ.get("AUTOGENESIS_WINDOWS_EVIDENCE")
    if destination:
        root = Path(destination).resolve(strict=True)
        name = "redaction-regression-" + launch_arg + "-" + control_identifier + ".json"
        temporary = root / (name + ".tmp")
        temporary.write_text(evidence + chr(10), encoding="utf-8")
        temporary.replace(root / name)
