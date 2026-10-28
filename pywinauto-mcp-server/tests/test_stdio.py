import json
import os
import sys
import time
import uuid
from pathlib import Path

import pytest
from autogenesis_agent_contract import load_contract

from ._protocol import ProtocolProcess

pytestmark = [pytest.mark.windows, pytest.mark.skipif(sys.platform != "win32", reason="Real Windows package protocol acceptance")]


def configured_business(tmp_path, app_config):
    business = tmp_path / "business"
    business.mkdir()
    canary = uuid.uuid4().hex
    path = business / "apps.json"
    profile = {**app_config, "api_key": "$AUTOGENESIS_ACCEPTANCE_API_KEY", "launch_args": ["--token", "$AUTOGENESIS_ACCEPTANCE_API_KEY"]}
    path.write_text(json.dumps({"PYWINAUTO_CONFIG": {"apps_config": {"first": profile, "second": {**profile, "app_name": "second"}}}}), encoding="utf-8")
    if canary in path.read_text(encoding="utf-8"):
        pytest.fail("Test setup wrote a plaintext secret.", pytrace=False)
    return business, path, canary


def write_evidence(name, value, canary):
    rendered = json.dumps(value, indent=2, ensure_ascii=True) + chr(10)
    if canary in rendered:
        pytest.fail("Refusing to publish secret-bearing protocol evidence.", pytrace=False)
    destination = os.environ.get("AUTOGENESIS_WINDOWS_EVIDENCE")
    if destination:
        root = Path(destination).resolve(strict=True)
        temporary = root / (name + ".tmp")
        temporary.write_text(rendered, encoding="utf-8")
        temporary.replace(root / name)


def test_console_stdio_initialize_inventory_workflows_identity_canaries_and_eof(console_command, tmp_path, app_config):
    business, config, canary = configured_business(tmp_path, app_config)
    expected = json.loads((Path(__file__).parent / "fixtures/legacy_tool_schemas.json").read_text(encoding="utf-8"))["tools"]
    contract = load_contract()
    with ProtocolProcess(console_command + ["--config", str(config), "--app", "second"], business, {"AUTOGENESIS_ACCEPTANCE_API_KEY": canary}) as client:
        initialized = client.initialize()
        assert initialized["result"]["instructions"] == contract.instructions
        assert {"tools", "prompts", "resources"}.issubset(initialized["result"]["capabilities"])
        tools = client.rpc("tools/list")["result"]["tools"]
        actual = {tool["name"]: tool["inputSchema"] for tool in tools}
        changed = {"enter_text", "preview_code_changes"}
        assert set(actual) == set(expected)
        assert {name: schema for name, schema in actual.items() if name not in changed} == {
            name: schema for name, schema in expected.items() if name not in changed
        }
        enter_text = actual["enter_text"]
        assert "SecretRef" in enter_text["$defs"]
        assert {"type": "string"} in enter_text["properties"]["content"]["anyOf"]
        assert {"$ref": "#/$defs/SecretRef"} in enter_text["properties"]["content"]["anyOf"]
        preview = actual["preview_code_changes"]
        assert {"SecretBindings", "SecretRef"}.issubset(preview["$defs"])
        assert preview["properties"]["secret_bindings"]["default"] is None
        assert len(tools) == 22
        prompts = client.rpc("prompts/list")["result"]["prompts"]
        assert {prompt["name"] for prompt in prompts} == {"execute_scenario", "generate_scenario_test", "execute_natural_language_task"}
        for name, arguments in {
            "execute_scenario": {"scenario_text": "Given an application"},
            "generate_scenario_test": {"scenario_text": "Given an application", "feature_file_path": "features/demo.feature"},
            "execute_natural_language_task": {"task_text": "Inspect the application"},
        }.items():
            prompt = client.rpc("prompts/get", {"name": name, "arguments": arguments})
            assert prompt["result"]["messages"][0]["content"]["text"] == contract.render(name, arguments)
        resources = client.rpc("resources/list")["result"]["resources"]
        assert [resource["uri"] for resource in resources] == ["autogenesis://agent-contract/identity"]
        identity = client.rpc("resources/read", {"uri": "autogenesis://agent-contract/identity"})
        data = json.loads(identity["result"]["contents"][0]["text"])
        assert {key: data[key] for key in contract.identity.to_dict()} == contract.identity.to_dict()
        wait = client.rpc("tools/call", {"name": "app_wait", "arguments": {"caller": "acceptance", "duration": 0}})
        assert not wait["result"].get("isError", False)
        # SDK validation, unknown dispatch, prompt validation, resource errors,
        # and tool errors must not echo submitted values.
        requests = [
            ("tools/call", {"name": "app_wait", "arguments": {"caller": "acceptance", "duration": canary}}),
            ("tools/call", {"name": canary, "arguments": {"content": canary}}),
            ("tools/call", {"name": "enter_text", "arguments": {"caller": "acceptance", "control_framework": "unsupported", "title": "password", "content": canary, "control_type": "Edit", "automation_id": canary}}),
            ("prompts/get", {"name": "execute_scenario", "arguments": {"scenario_text": [canary]}}),
            ("prompts/get", {"name": "execute_scenario", "arguments": {canary: canary}}),
            ("resources/read", {"uri": "autogenesis://invalid/" + canary}),
        ]
        for method, params in requests:
            client.rpc(method, params)
        client.close_stdin()
        exit_code = client.wait()
        client.assert_no_secret(canary)
        transcript = list(client.transcript)
    write_evidence("stdio-protocol.json", {"transcript": transcript, "tools": expected, "identity": data, "shutdown": {"trigger": "stdin EOF", "exit_code": exit_code}, "secret_scan": "passed"}, canary)
    write_evidence("stdio-stderr.json", {"diagnostics": client.stderr, "secret_scan": "passed"}, canary)


def test_console_closes_on_eof_without_a_handshake(console_command, tmp_path, app_config):
    business, config, canary = configured_business(tmp_path, app_config)
    with ProtocolProcess(console_command + ["--config", str(config)], business, {"AUTOGENESIS_ACCEPTANCE_API_KEY": canary}) as client:
        client.close_stdin()
        client.wait()
        client.assert_no_secret(canary)


def test_eof_cancels_pending_tool_work(console_command, tmp_path, app_config):
    business, config, canary = configured_business(tmp_path, app_config)
    with ProtocolProcess(console_command + ["--config", str(config)], business, {"AUTOGENESIS_ACCEPTANCE_API_KEY": canary}) as client:
        assert "result" in client.initialize()
        client.send({"id": 1000, "method": "tools/call", "params": {"name": "app_wait", "arguments": {"caller": "acceptance", "duration": 60}}})
        assert "result" in client.rpc("tools/list")
        client.close_stdin()
        exit_code = client.wait()
        client.assert_no_secret(canary)
    write_evidence("pending-tool-eof.json", {"trigger": "stdin EOF with pending app_wait", "exit_code": exit_code, "secret_scan": "passed"}, canary)


@pytest.mark.parametrize("pending_tool", [False, True])
def test_sigint_with_open_stdin_terminates_the_real_installed_server(tmp_path, app_config, pending_tool):
    business, config, canary = configured_business(tmp_path, app_config)
    # Schedule a genuine SIGINT in the child event loop. This works on Windows
    # CI without relying on an interactive console or CTRL_C process groups.
    # The unmodified server, transport, drivers, and installed console main run.
    program = """
import asyncio
import signal
from autogenesis_windows_mcp import cli
original = cli._serve
async def serve(server, transport):
    asyncio.get_running_loop().call_later(2, signal.raise_signal, signal.SIGINT)
    await original(server, transport)
cli._serve = serve
raise SystemExit(cli.main())
"""
    with ProtocolProcess([sys.executable, "-I", "-c", program, "--config", str(config)], business, {"AUTOGENESIS_ACCEPTANCE_API_KEY": canary}) as client:
        assert "result" in client.initialize()
        if pending_tool:
            client.send({"id": 1000, "method": "tools/call", "params": {"name": "app_wait", "arguments": {"caller": "acceptance", "duration": 60}}})
            assert "result" in client.rpc("tools/list")
        assert not client.process.stdin.closed
        started = time.monotonic()
        exit_code = client.wait()
        shutdown_seconds = time.monotonic() - started
        assert not client.process.stdin.closed
        client.assert_no_secret(canary)
    name = "sigint-pending-tool.json" if pending_tool else "sigint.json"
    write_evidence(name, {"trigger": "SIGINT with stdin open", "stdin_left_open": True, "pending_tool": pending_tool, "exit_code": exit_code, "shutdown_seconds": shutdown_seconds, "protocol_only_stdout": True, "secret_scan": "passed"}, canary)


def test_source_entry_script_uses_the_installed_main_over_stdio(tmp_path, app_config):
    source_script = os.environ.get("AUTOGENESIS_SOURCE_SCRIPT")
    if not source_script:
        pytest.skip("Clean-wheel verifier supplies the real source entry script.")
    business, config, canary = configured_business(tmp_path, app_config)
    with ProtocolProcess([sys.executable, "-I", source_script, "--transport", "stdio", "--config", str(config)], business, {"AUTOGENESIS_ACCEPTANCE_API_KEY": canary}) as client:
        assert "result" in client.initialize()
        client.close_stdin()
        client.wait()
        client.assert_no_secret(canary)
