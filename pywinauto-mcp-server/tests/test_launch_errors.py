import json
import sys

import pytest

pytestmark = [pytest.mark.windows, pytest.mark.skipif(sys.platform != "win32", reason="Real Windows driver imports required")]


class FakeManager:
    def __init__(self, failure=None):
        self.failure = failure
        self.gen_code_id = None
        self.gen_code_cache = []
        self.recording_warnings = []

    def start_tool_execution(self, tool_name):
        return True

    def finish_tool_execution(self, tool_name):
        pass

    async def app_launch(self):
        if self.failure is not None:
            raise self.failure
        return True

    async def get_main_window(self):
        raise AssertionError("Snapshot access was not expected")


async def call_app_launch(manager, monkeypatch=None, snapshot_failure=None):
    from autogenesis_windows_mcp.server import WindowsMCP
    from autogenesis_windows_mcp.tools import common_tool

    if snapshot_failure is not None:
        async def fail_snapshot(resp, app_manager, need_snapshot):
            resp["data"] = {"partial_snapshot": str(snapshot_failure)}
            raise snapshot_failure

        monkeypatch.setattr(common_tool, "fill_snapshot", fail_snapshot)

    server = WindowsMCP("launch-error-contract")
    common_tool.register_common_tools(server, manager)
    result = await server.call_tool("app_launch", {"caller": "contract", "need_snapshot": int(snapshot_failure is not None)})
    content = result[0] if isinstance(result, tuple) else result
    content = content[0] if isinstance(content, list) else content
    return json.loads(content.text)


EXPECTED = {
    "PROCESS_START_FAILED": ("process_start", False, "Application process could not be started."),
    "ELEVATION_REQUIRED": ("process_start", False, "Application launch requires elevation."),
    "WINDOW_NOT_FOUND": ("window_discovery", True, "Application window was not found before the launch deadline."),
    "WINDOW_AMBIGUOUS": ("window_discovery", False, "Application profile matched multiple launched windows."),
    "WINDOW_NOT_VISIBLE": ("window_readiness", True, "Application window did not become visible before the launch deadline."),
    "WINDOW_NOT_ENABLED": ("window_readiness", True, "Application window did not become enabled before the launch deadline."),
    "WINDOW_BIND_FAILED": ("window_binding", True, "Application window could not be bound before the launch deadline."),
    "WINDOW_CONNECTION_LOST": ("window_connection", True, "The verified application window is no longer available."),
    "SNAPSHOT_FAILED": ("snapshot", True, "Application snapshot extraction failed."),
    "INTERNAL_ERROR": ("internal", False, "Application launch failed internally."),
}


LEAK_MARKERS = (
    r"C:\Sensitive\private-app.exe",
    "SYNTHETIC_PRIVATE_WINDOW_TITLE",
    "--token=SYNTHETIC_PRIVATE_ARGUMENT",
    "SYNTHETIC_EXCEPTION_TEXT",
    "Traceback (most recent call last)",
    "SYNTHETIC_SECRET_CANARY",
    "SYNTHETIC_PRIVATE_UI_VALUE",
)


def assert_no_launch_details(value):
    if isinstance(value, dict):
        values = value.values()
    elif isinstance(value, (list, tuple)):
        values = value
    else:
        values = (value,)
    for item in values:
        if isinstance(item, (dict, list, tuple)):
            assert_no_launch_details(item)
        elif isinstance(item, str):
            for marker in LEAK_MARKERS:
                assert marker not in item


@pytest.mark.anyio
@pytest.mark.parametrize("code", EXPECTED)
async def test_app_launch_serializes_only_the_fixed_error_contract(code, caplog):
    from autogenesis_windows_mcp.launch_errors import LaunchErrorCode, LaunchFailure

    details = " | ".join(LEAK_MARKERS)
    failure = LaunchFailure(LaunchErrorCode[code])
    failure.__cause__ = RuntimeError(details)
    payload = await call_app_launch(FakeManager(failure))
    stage, retryable, description = EXPECTED[code]

    assert payload == {
        "status": "error",
        "error": description,
        "error_code": code,
        "stage": stage,
        "retryable": retryable,
        "data": {},
    }
    assert_no_launch_details(payload)
    assert_no_launch_details(caplog.text)


@pytest.mark.anyio
async def test_unknown_exception_fails_closed_without_exception_content(caplog):
    details = " | ".join(LEAK_MARKERS)
    payload = await call_app_launch(FakeManager(RuntimeError(details)))

    assert payload == {
        "status": "error",
        "error": EXPECTED["INTERNAL_ERROR"][2],
        "error_code": "INTERNAL_ERROR",
        "stage": "internal",
        "retryable": False,
        "data": {},
    }
    assert_no_launch_details(payload)
    assert_no_launch_details(caplog.text)


@pytest.mark.anyio
async def test_mismatched_launch_error_description_remains_sanitized():
    from autogenesis_windows_mcp.utils.logger import log_tool_call

    canary = "SYNTHETIC_SPOOFED_LAUNCH_DESCRIPTION_CANARY"

    @log_tool_call
    async def spoofed_tool():
        return json.dumps({
            "status": "error",
            "error": canary,
            "error_code": "WINDOW_NOT_FOUND",
            "stage": "window_discovery",
            "retryable": True,
            "data": {},
        })

    payload = json.loads(await spoofed_tool())
    assert payload["error"] == "Operation failed"
    assert canary not in json.dumps(payload)


@pytest.mark.anyio
async def test_snapshot_exception_has_its_own_safe_stage(monkeypatch, caplog):
    details = " | ".join(LEAK_MARKERS)
    payload = await call_app_launch(
        FakeManager(), monkeypatch=monkeypatch, snapshot_failure=RuntimeError(details)
    )

    assert payload == {
        "status": "error",
        "error": EXPECTED["SNAPSHOT_FAILED"][2],
        "error_code": "SNAPSHOT_FAILED",
        "stage": "snapshot",
        "retryable": True,
        "data": {},
    }
    assert_no_launch_details(payload)
    assert_no_launch_details(caplog.text)


@pytest.mark.parametrize(
    "state,code",
    [
        ("PROCESS_STARTED", "WINDOW_NOT_FOUND"),
        ("WINDOW_FOUND", "WINDOW_BIND_FAILED"),
        ("CONNECTED", "WINDOW_BIND_FAILED"),
        ("EXISTS", "WINDOW_NOT_VISIBLE"),
        ("VISIBLE", "WINDOW_NOT_ENABLED"),
        ("ENABLED", "WINDOW_BIND_FAILED"),
        ("BOUND", "WINDOW_BIND_FAILED"),
    ],
)
def test_deadline_deepest_state_determines_failure_code(state, code):
    from autogenesis_windows_mcp import app_session

    failure = app_session._LaunchTimeout(app_session._LaunchState[state])
    assert failure.code.value == code
    assert failure.deepest_state is app_session._LaunchState[state]


@pytest.mark.anyio
@pytest.mark.parametrize(
    "error,code",
    [
        (type("ElevationError", (OSError,), {"winerror": 740})("localized canary"), "ELEVATION_REQUIRED"),
        (OSError("SYNTHETIC_PROCESS_START_CANARY"), "PROCESS_START_FAILED"),
    ],
)
async def test_process_start_failure_uses_structural_classification(monkeypatch, error, code):
    from autogenesis_agent_contract import tool_execution
    from autogenesis_windows_mcp import app_session
    from autogenesis_windows_mcp.launch_errors import LaunchFailure

    manager = app_session.AppSessionManager({
        "exe": r"C:\private\sensitive-application.exe",
        "window_title_re": ".*Sensitive title.*",
        "launch_args": ["--secret", "private-value"],
    })
    monkeypatch.setattr(manager, "kill_app_process_by_path", lambda: None)
    monkeypatch.setattr(app_session.win32process, "CreateProcess", lambda *args: (_ for _ in ()).throw(error))

    def app_launch():
        pass

    with tool_execution(app_launch, (), {}):
        with pytest.raises(LaunchFailure) as caught:
            await manager.app_launch()

    assert caught.value.code.value == code
    assert vars(caught.value) == {}
