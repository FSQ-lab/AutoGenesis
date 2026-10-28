import io
import json
import logging
import sys
import uuid

import pytest

from autogenesis_windows_mcp.security import remember_config_secrets, scrub
from autogenesis_windows_mcp.utils.logger import _SafeDiagnostic, log_tool_call
from autogenesis_windows_mcp.utils.response_format import format_tool_response


def no_secret(canary, *values):
    if any(canary in str(value) for value in values):
        pytest.fail("A secret crossed the redaction boundary.", pytrace=False)


@pytest.mark.anyio
async def test_tool_error_and_logging_never_include_arguments_text_keys_or_results(caplog):
    canary = uuid.uuid4().hex
    @log_tool_call
    async def failing(content: str, key_sequence_raw: str):
        raise RuntimeError(content + key_sequence_raw)
    with caplog.at_level(logging.INFO), pytest.raises(RuntimeError) as caught:
        await failing(content=canary, key_sequence_raw=canary)
    no_secret(canary, caught.value, caplog.text)
    assert "sensitive details withheld" in str(caught.value)
    @log_tool_call
    async def successful(content: str):
        return json.dumps({"status": "success", "data": content})
    with caplog.at_level(logging.INFO):
        result = await successful(content=canary)
    # Ordinary text remains data. The logger must omit it without registering
    # it as a secret or changing the successful response.
    assert json.loads(result) == {"status": "success", "data": canary}
    no_secret(canary, caplog.text)


@pytest.mark.parametrize("launch_arg", ["a", "s", "0", "status", "data", "success"])
def test_ordinary_launch_args_preserve_response_fields_and_text(launch_arg):
    remember_config_secrets({"launch_args": [launch_arg]})
    response = {
        "status": "success",
        "data": {"snapshot": {"title": "A sample app", "value": "a useful value"}, "step_raw": "a normal step", "duration": 0},
    }
    assert json.loads(format_tool_response(response)) == response


@pytest.mark.anyio
@pytest.mark.parametrize("input_name", ["content", "key_sequence_raw", "key_sequence_formatted", "step", "step_raw", "scenario", "task_description", "expected_value", "element_value"])
@pytest.mark.parametrize("ordinary_value", ["a", "status"])
async def test_ordinary_tool_inputs_preserve_response_fields_and_text(input_name, ordinary_value):
    response = {"status": "success", "data": {"snapshot": {"title": "A sample app", "value": "a useful value"}, "step_raw": "a normal step"}}
    @log_tool_call
    async def snapshot(content="", key_sequence_raw="", key_sequence_formatted="", step="", step_raw="", scenario="", task_description="", expected_value="", element_value=""):
        return format_tool_response(response)
    assert json.loads(await snapshot(**{input_name: ordinary_value})) == response


@pytest.mark.anyio
@pytest.mark.parametrize("credential", ["api_key", "authorization", "password", "accessKey", "clientSecret", "userName", "auth_token"])
async def test_credential_key_canaries_remain_redacted_from_results_logs_and_evidence(credential, caplog):
    canary = uuid.uuid4().hex
    @log_tool_call
    async def credential_tool(api_key="", authorization="", password="", accessKey="", clientSecret="", userName="", auth_token=""):
        return format_tool_response({"status": "success", "data": {"echo": canary}})
    with caplog.at_level(logging.INFO):
        result = await credential_tool(**{credential: canary})
    evidence = json.dumps({"response": json.loads(result), "logs": caplog.text})
    no_secret(canary, result, caplog.text, evidence)
    assert json.loads(result) == {"status": "success", "data": {"echo": "[REDACTED]"}}


@pytest.mark.anyio
async def test_password_control_canary_remains_protected_in_later_responses_and_evidence(caplog):
    canary = uuid.uuid4().hex
    @log_tool_call
    async def password_control(title: str, content: str):
        return format_tool_response({"status": "success", "data": {"echo": content}})
    with caplog.at_level(logging.INFO):
        result = await password_control(title="Password", content=canary)
    subsequent = format_tool_response({"status": "success", "data": {"snapshot": {"value": canary}}})
    evidence = json.dumps({"response": json.loads(result), "subsequent": json.loads(subsequent), "logs": caplog.text})
    no_secret(canary, result, subsequent, caplog.text, evidence)
    assert json.loads(subsequent)["data"]["snapshot"]["value"] == "[REDACTED]"


@pytest.mark.anyio
@pytest.mark.parametrize("field,value", [("token_count", "status"), ("tokenizers_parallelism", "false")])
async def test_custom_tool_fields_are_not_credentials(field, value):
    response = {"status": "success", "data": {field: value, "echo": value}}
    @log_tool_call
    async def custom_tool(token_count="", tokenizers_parallelism=""):
        return format_tool_response(response)
    assert json.loads(await custom_tool(**{field: value})) == response


@pytest.mark.anyio
async def test_short_credential_value_preserves_response_keys(monkeypatch):
    monkeypatch.setenv("API_KEY", "status")
    remember_config_secrets({})
    response = {"status": "success", "data": {"echo": "status", "nested": {"status": "status"}}}
    expected = {"status": "success", "data": {"echo": "[REDACTED]", "nested": {"status": "[REDACTED]"}}}
    assert scrub(response) == expected
    @log_tool_call
    async def read_state():
        return format_tool_response(response)
    # The decorator also handles serialized JSON; it must preserve those keys.
    assert json.loads(await read_state()) == expected


def test_tokenizers_parallelism_is_not_an_environment_secret(monkeypatch):
    monkeypatch.setenv("TOKENIZERS_PARALLELISM", "false")
    remember_config_secrets({})
    response = {"status": "success", "data": {"parallelism": "false", "value": False}}
    assert scrub(response) == response


@pytest.mark.parametrize("name", ["TOKEN", "GITHUB_TOKEN", "SERVICE_PASSWORD", "OPENAI_API_KEY", "AUTHORIZATION", "AWS_SECRET_ACCESS_KEY", "SSH_PRIVATE_KEY"])
def test_real_environment_credentials_remain_protected(name, monkeypatch):
    canary = uuid.uuid4().hex
    monkeypatch.setenv(name, canary)
    remember_config_secrets({})
    response = scrub({"status": "success", "data": {"echo": canary}})
    no_secret(canary, json.dumps(response))
    assert response == {"status": "success", "data": {"echo": "[REDACTED]"}}


def test_dependency_tracebacks_and_config_readback_are_redacted():
    canary = uuid.uuid4().hex
    remember_config_secrets({"api_key": canary})
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.addFilter(_SafeDiagnostic())
    try:
        raise RuntimeError(canary)
    except RuntimeError:
        record = logging.LogRecord("httpx", logging.ERROR, "", 1, "request %s", (canary,), sys.exc_info())
    handler.handle(record)
    rendered = scrub({"config": {"ordinary": canary}, "api_key": canary, "diagnostic": "error " + canary})
    no_secret(canary, stream.getvalue(), json.dumps(rendered))
    assert "Traceback" not in stream.getvalue()
    assert rendered["config"] == "[REDACTED]"
    assert rendered["api_key"] == "[REDACTED]"


@pytest.mark.windows
@pytest.mark.skipif(sys.platform != "win32", reason="Windows driver modules")
@pytest.mark.anyio
async def test_real_keystroke_and_text_tool_errors_do_not_echo_sensitive_inputs(app_config, caplog):
    from autogenesis_windows_mcp.app_session import AppSessionManager
    from autogenesis_windows_mcp.server import WindowsMCP
    from autogenesis_windows_mcp.tools.common_tool import register_common_tools
    canary = uuid.uuid4().hex
    manager = AppSessionManager(app_config)
    async def fail(*args, **kwargs):
        raise RuntimeError(canary)
    manager.get_main_window = fail
    server = WindowsMCP("secret-boundary")
    register_common_tools(server, manager)
    with caplog.at_level(logging.INFO):
        keys = await server.call_tool("send_keystrokes", {"caller": "acceptance", "key_sequence_raw": canary, "key_sequence_formatted": canary, "need_snapshot": 0})
        text = await server.call_tool("enter_text", {"caller": "acceptance", "control_framework": "pywinauto", "title": "password", "content": canary, "control_type": "Edit", "automation_id": "password", "need_snapshot": 0})
    no_secret(canary, keys, text, caplog.text)
    assert not manager.is_executing


@pytest.mark.windows
@pytest.mark.skipif(sys.platform != "win32", reason="Windows driver modules")
@pytest.mark.anyio
async def test_known_credentials_cannot_enter_generation_preview_or_written_code(tmp_path, app_config):
    from autogenesis_windows_mcp.app_session import AppSessionManager
    from autogenesis_windows_mcp.server import WindowsMCP
    from autogenesis_windows_mcp.tools.gen_code_tool import register_gen_code_tools
    from autogenesis_windows_mcp.utils.gen_code import gen_code_preview, generate_step_definition
    canary = uuid.uuid4().hex
    manager = AppSessionManager({**app_config, "api_key": canary})
    manager.gen_code_id = "acceptance"
    manager.steps_dir = str(tmp_path)
    manager.step_file_target = str(tmp_path / "steps.py")
    manager.gen_code_cache = [{"gen_code_id": "acceptance", "tool_name": "enter_text", "step": 'When enter "' + canary + '"', "tool_params": {"content": canary}, "scenario": "credential entry"}]
    preview = gen_code_preview(manager)
    no_secret(canary, preview, manager.proposed_changes)
    server = WindowsMCP("generation-boundary")
    register_gen_code_tools(server, manager)
    result = await server.call_tool("confirm_code_changes", {})
    no_secret(canary, result, (tmp_path / "steps.py").read_text(encoding="utf-8"))
    # Ordinary text still replays unchanged and is not classified as a secret.
    ordinary = generate_step_definition({"tool_name": "enter_text", "step_type": "when", "step_text_raw": "search for a public term", "tool_params": {"content": "public search term"}})
    assert "public search term" in ordinary
