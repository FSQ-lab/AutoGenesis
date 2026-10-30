import json
import sys
from pathlib import Path
from types import SimpleNamespace


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
        handle = 301
        element_info = SimpleNamespace(handle=301, process_id=302, runtime_id=(303,))

        def wrapper_object(self):
            return self
        def wait(self, state, timeout):
            pass

    class FakeApplication:
        def __init__(self, backend):
            assert backend == "uia"
            self.process = 301

        def start(self, command):
            start_calls.append(command)
            return self

        def connect(self, **kwargs):
            assert kwargs == {"handle": 301}
            self.process = 302
            return self

        def window(self, **kwargs):
            return FakeWindow()

    class FakeDesktop:
        def __init__(self, backend):
            assert backend == "uia"

        def windows(self, **kwargs):
            return [FakeWindow()]

    class FakeProcess:
        def __init__(self, process_id):
            self.process_id = process_id

        def ppid(self):
            return {302: 301}.get(self.process_id, 0)

        def create_time(self):
            return {301: 10.0, 302: 11.0}[self.process_id]

    class FakeTime:
        def __init__(self, value):
            self.value = value

        def timestamp(self):
            return self.value

    class FakeHandle:
        def Close(self):
            pass

    process_handle = FakeHandle()

    def create_process(*args):
        start_calls.append(args[1])
        return process_handle, FakeHandle(), 301, 1

    monkeypatch.setattr(app_session.win32process, "CreateProcess", create_process)
    monkeypatch.setattr(
        app_session.win32process,
        "GetProcessTimes",
        lambda handle: {"CreationTime": FakeTime(10.0), "ExitTime": FakeTime(12.0)},
    )


    monkeypatch.setattr(app_session, "Application", FakeApplication)
    monkeypatch.setattr(app_session, "Desktop", FakeDesktop)
    monkeypatch.setattr(app_session.psutil, "Process", FakeProcess)
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
async def test_launch_preserves_the_window_that_passed_readiness(monkeypatch):
    from autogenesis_windows_mcp import app_session
    from autogenesis_agent_contract import tool_execution

    manager = app_session.AppSessionManager({
        "exe": r"C:\Windows\System32\verified-window.exe",
        "window_title_re": ".*Initial title.*",
        "launch_args": [],
    })
    connect_calls = 0
    window_queries = []
    state = {"title_available": True}

    class FakeElementInfo:
        def __init__(self, handle, process_id, runtime_id):
            self.handle = handle
            self.process_id = process_id
            self.runtime_id = runtime_id

    original_element_info = FakeElementInfo(101, 202, (42, 101))

    class FakeWindow:
        handle = 101
        element_info = original_element_info

        def wrapper_object(self):
            return self

    verified_window = FakeWindow()

    class StaleWindow:
        handle = 99
        element_info = FakeElementInfo(99, 303, (42, 99))

    stale_window = StaleWindow()

    class FakeDesktop:
        def __init__(self, backend):
            assert backend == "uia"

        def windows(self, **kwargs):
            window_queries.append("title")
            assert window_queries.count("title") == 1
            if not state["title_available"]:
                raise app_session.ElementNotFoundError("title changed after readiness")
            return [stale_window, verified_window]

    class FakeProcess:
        def __init__(self, process_id):
            self.process_id = process_id

        def ppid(self):
            return {202: 11, 303: 11}.get(self.process_id, 0)

        def create_time(self):
            return {11: 10.0, 202: 11.0, 303: 9.0}[self.process_id]

    class FakeTime:
        def __init__(self, value):
            self.value = value

        def timestamp(self):
            return self.value

    class FakeHandle:
        def Close(self):
            pass

    process_handle = FakeHandle()

    monkeypatch.setattr(
        app_session.win32process,
        "CreateProcess",
        lambda *args: (process_handle, FakeHandle(), 11, 1),
    )
    monkeypatch.setattr(
        app_session.win32process,
        "GetProcessTimes",
        lambda handle: {"CreationTime": FakeTime(10.0), "ExitTime": FakeTime(12.0)},
    )


    class BoundWindow:
        def __init__(self, predicate):
            self.predicate = predicate

        def wrapper_object(self):
            if not self.predicate(verified_window.element_info):
                raise app_session.ElementNotFoundError("bound window identity changed")
            return verified_window

        def wait(self, state_name, timeout):
            self.wrapper_object()
            if state_name == "enabled":
                state["title_available"] = False

        def child_window(self, **kwargs):
            assert kwargs == {
                "title": "",
                "control_type": "Pane",
                "class_name": "Chrome_WidgetWin_1",
                "found_index": 0,
            }
            return BoundWindow(self.predicate)

        def exists(self, timeout):
            self.wrapper_object()
            return True


    class FakeApplication:
        def __init__(self, backend):
            assert backend == "uia"
            self.process = 11

        def start(self, command):
            return self

        def connect(self, **kwargs):
            nonlocal connect_calls
            assert kwargs == {"handle": 101}
            connect_calls += 1
            self.process = 202
            return self

        def window(self, **kwargs):
            window_queries.append("identity")
            return BoundWindow(kwargs["predicate_func"])

    monkeypatch.setattr(app_session, "Application", FakeApplication)
    monkeypatch.setattr(app_session, "Desktop", FakeDesktop)
    monkeypatch.setattr(app_session.psutil, "Process", FakeProcess)
    monkeypatch.setattr(app_session.time, "sleep", lambda duration: None)
    monkeypatch.setattr(manager, "kill_app_process_by_path", lambda: None)

    def app_launch():
        pass

    with tool_execution(app_launch, (), {}):
        assert await manager.app_launch() is True
        assert (await manager.get_main_window()).wrapper_object() is verified_window
        assert manager.get_screenshot_window().wrapper_object() is verified_window
        assert await manager.app_launch() is False
        binding_generation = manager._binding.generation
        assert manager._binding.process_id == 202
    assert connect_calls == 1
    assert window_queries == ["title", "identity", "identity"]

    verified_window.element_info = FakeElementInfo(101, 202, (42, 101))
    with pytest.raises(RuntimeError, match="Verified main window binding is unavailable"):
        await manager.get_main_window()
    assert manager._binding is None
    assert manager._app is None
    assert manager._session_generation > binding_generation
    assert window_queries[-1] == "identity"

    connect_calls = 0
    window_queries.clear()
    state["title_available"] = True
    verified_window.element_info = original_element_info
    with tool_execution(app_launch, (), {}):
        assert await manager.app_launch() is True
        closing_generation = manager._binding.generation
        await manager.app_close()
    assert manager._binding is None
    assert manager._app is None
    assert manager._session_generation > closing_generation
    with pytest.raises(RuntimeError, match="Verified main window binding is unavailable"):
        await manager.get_main_window()


def test_launcher_provenance_survives_exit_but_rejects_pid_reincarnation(monkeypatch):
    from autogenesis_windows_mcp import app_session

    creation_times = {202: 11.0}

    class FakeProcess:
        def __init__(self, process_id):
            self.process_id = process_id

        def create_time(self):
            if self.process_id not in creation_times:
                raise app_session.psutil.NoSuchProcess(self.process_id)
            return creation_times[self.process_id]

        def ppid(self):
            return {202: 11, 303: 11}.get(self.process_id, 0)

    monkeypatch.setattr(app_session.psutil, "Process", FakeProcess)

    class FakeTime:
        def timestamp(self):
            return 12.0

    process_handle = object()
    monkeypatch.setattr(
        app_session.win32process,
        "GetProcessTimes",
        lambda handle: {"ExitTime": FakeTime()},
    )

    assert app_session.AppSessionManager._belongs_to_launch(202, 11, 10.0, process_handle)
    creation_times[303] = 13.0
    assert not app_session.AppSessionManager._belongs_to_launch(303, 11, 10.0, process_handle)
    creation_times[11] = 20.0
    assert not app_session.AppSessionManager._belongs_to_launch(11, 11, 10.0, process_handle)


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
