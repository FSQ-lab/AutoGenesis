import json
import sys
from pathlib import Path

import pytest
from mcp.server.fastmcp.exceptions import ToolError
from autogenesis_agent_contract import ContractError, RuntimeContractRequirement, load_contract

from autogenesis_windows_mcp import server as runtime

pytestmark = [pytest.mark.windows, pytest.mark.skipif(sys.platform != "win32", reason="Real Windows driver imports required")]


@pytest.mark.anyio
async def test_versioned_tool_names_and_secret_ref_schemas(app_config):
    expected = json.loads((Path(__file__).parent / "fixtures/legacy_tool_schemas.json").read_text(encoding="utf-8"))["tools"]
    server = runtime.create_server(app_config)
    actual = {tool.name: tool.inputSchema for tool in await server.list_tools()}
    assert len(actual) == 22 and set(actual) == set(expected)
    changed = {"enter_text", "preview_code_changes", "confirm_code_changes"}
    assert {name: schema for name, schema in actual.items() if name not in changed} == {
        name: schema for name, schema in expected.items() if name not in changed
    }
    assert actual["preview_code_changes"]["properties"]["secret_bindings"]["default"] is None
    variants = actual["enter_text"]["properties"]["content"]["anyOf"]
    assert {variant.get("type", "ref") for variant in variants} == {"string", "ref"}
    confirm = actual["confirm_code_changes"]["properties"]
    assert confirm["preview_id"]["default"] == ""
    assert confirm["digest"]["default"] == ""
    assert confirm["approved"]["default"] is False
    assert not any("config" in name for name in actual)

@pytest.mark.anyio
async def test_launch_expands_environment_refs_without_mutating_config(monkeypatch):
    from autogenesis_agent_contract import protect_config, serialize, tool_execution
    from autogenesis_windows_mcp import app_session

    monkeypatch.delenv("WINDIR", raising=False)
    monkeypatch.setenv("SYSTEMROOT", r"C:\Windows")
    monkeypatch.setenv("LOCALAPPDATA", r"C:\Users\acceptance\AppData\Local")
    monkeypatch.setenv("AUTOGENESIS_TEST_SECRET", "resolved-secret")
    protected = protect_config({
        "exe": r"%WINDIR%\System32\notepad.exe",
        "window_title_re": ".*AutoGenesis acceptance.*",
        "launch_args": [
            r"--state=%LOCALAPPDATA%\AutoGenesis",
            "$AUTOGENESIS_TEST_SECRET",
        ],
    })
    manager = app_session.AppSessionManager(protected)
    start_calls = []

    class FakeWindow:
        def wait(self, state, timeout):
            pass

    class FakeApplication:
        def __init__(self, backend):
            assert backend == "uia"

        def start(self, command):
            start_calls.append(command)

        def connect(self, **kwargs):
            return self

        def window(self, **kwargs):
            return FakeWindow()

    monkeypatch.setattr(app_session, "Application", FakeApplication)
    monkeypatch.setattr(app_session.time, "sleep", lambda duration: None)
    monkeypatch.setattr(manager, "kill_app_process_by_path", lambda: None)

    def app_launch():
        pass

    with tool_execution(app_launch, (), {}):
        assert await manager.app_launch() is True

    assert start_calls == [
        r"C:\Windows\System32\notepad.exe --state=C:\Users\acceptance\AppData\Local\AutoGenesis resolved-secret"
    ]
    assert serialize(manager.config) == {
        "exe": r"%WINDIR%\System32\notepad.exe",
        "window_title_re": ".*AutoGenesis acceptance.*",
        "launch_args": [
            r"--state=%LOCALAPPDATA%\AutoGenesis",
            {"$secret": "env:AUTOGENESIS_TEST_SECRET"},
        ],
    }


@pytest.mark.anyio
async def test_document_input_and_value_assertion_use_uia_value_pattern(monkeypatch, app_config):
    from autogenesis_windows_mcp.app_session import AppSessionManager
    from autogenesis_windows_mcp.server import WindowsMCP
    from autogenesis_windows_mcp.tools import common_tool, verify_tool

    expected = "AutoGenesis Windows acceptance 20261030"

    class ValuePattern:
        CurrentIsReadOnly = False
        CurrentValue = ""

        def SetValue(self, value):
            self.CurrentValue = value

    class DocumentWrapper:
        iface_value = ValuePattern()

        def get_value(self):
            raise AttributeError("UIAWrapper has no get_value")

    class Element:
        def wrapper_object(self):
            return wrapper

        def __getattr__(self, name):
            return getattr(wrapper, name)

    class AsyncioStub:
        @staticmethod
        async def sleep(duration):
            pass

    wrapper = DocumentWrapper()

    async def find(*args, **kwargs):
        return Element(), True, {}, {}

    manager = AppSessionManager(app_config)
    server = WindowsMCP("modern-notepad-regression")
    common_tool.register_common_tools(server, manager)
    verify_tool.register_verify_tools(server, manager)
    monkeypatch.setattr(common_tool, "find_element_by_kwargs", find)
    monkeypatch.setattr(verify_tool, "find_element_by_kwargs", find)
    monkeypatch.setattr(common_tool, "asyncio", AsyncioStub())

    async def call(name, arguments):
        result = await server.call_tool(name, arguments)
        content = result[0] if isinstance(result, tuple) else result
        content = content[0] if isinstance(content, list) else content
        return json.loads(content.text)

    target = {
        "caller": "test",
        "control_framework": "pywinauto",
        "control_type": "Document",
        "automation_id": "",
        "control_idx": 1,
        "class_name": "RichEditD2DPT",
        "need_snapshot": 0,
    }
    entered = await call("enter_text", {**target, "title": "", "content": expected})
    verified = await call("verify_element_value", {
        **target,
        "name": "",
        "element_value": "",
        "expected_value": expected,
    })

    assert entered["status"] == "success"
    assert wrapper.iface_value.CurrentValue == expected
    assert verified["status"] == "success"


@pytest.mark.anyio
async def test_generation_destination_cannot_escape_business_project(app_config, tmp_path):
    server = runtime.create_server(app_config, business_root=tmp_path)
    outside = tmp_path.parent / f"{tmp_path.name}-outside" / "steps.py"
    with pytest.raises(ToolError, match="AUTOGENESIS_GENERATION_DESTINATION_INVALID"):
        await server.call_tool("before_gen_code", {"step_file": str(outside)})
    assert not outside.parent.exists()



@pytest.mark.anyio
async def test_canonical_instructions_prompts_and_identity_use_merged_adapter(app_config):
    server = runtime.create_server(app_config)
    contract = load_contract()
    assert server.instructions == contract.instructions
    assert runtime.RUNTIME_CONTRACT == RuntimeContractRequirement("2.0.0", "4367a2e388d0d5cb41a415b25b6a58e25025f1da6749bfdffe87a37c60a0c9d3")
    assert {prompt.name: [(arg.name, arg.required) for arg in prompt.arguments] for prompt in await server.list_prompts()} == {
        "execute_scenario": [("scenario_text", True), ("feature_file_path", False)],
        "generate_scenario_test": [("scenario_text", True), ("feature_file_path", True)],
        "execute_natural_language_task": [("task_text", True)],
    }
    for name, arguments in {
        "execute_scenario": {"scenario_text": "Given an application"},
        "generate_scenario_test": {"scenario_text": "Given an application", "feature_file_path": "features/demo.feature"},
        "execute_natural_language_task": {"task_text": "Inspect the application"},
    }.items():
        result = await server.get_prompt(name, arguments)
        assert result.messages[0].content.text == contract.render(name, arguments)
    resources = await server.list_resources()
    assert [str(resource.uri) for resource in resources] == ["autogenesis://agent-contract/identity"]
    contents = list(await server.read_resource("autogenesis://agent-contract/identity"))
    identity = json.loads(contents[0].content)
    assert {key: identity[key] for key in contract.identity.to_dict()} == contract.identity.to_dict()


@pytest.mark.parametrize("version,digest", [("3.0.0", "4367a2e388d0d5cb41a415b25b6a58e25025f1da6749bfdffe87a37c60a0c9d3"), ("2.0.0", "0" * 64)])
def test_contract_drift_fails_closed_before_driver_import(monkeypatch, app_config, version, digest):
    monkeypatch.setattr(runtime, "RUNTIME_CONTRACT", RuntimeContractRequirement(version, digest))
    with pytest.raises(ContractError):
        runtime.create_server(app_config)
