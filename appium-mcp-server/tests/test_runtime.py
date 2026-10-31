import json
import os
from pathlib import Path
import runpy
import signal
import threading
from unittest.mock import Mock

import anyio
import pytest
from watchdog.events import FileMovedEvent

from autogenesis_agent_contract import tool_execution
from autogenesis_appium_mcp import server
from autogenesis_appium_mcp import driver_session
from autogenesis_appium_mcp.driver_session import DriverSessionManager, SessionCloseError
from autogenesis_appium_mcp.utils.config_manager import ConfigFileHandler, ConfigManager
from conftest import reference_server


@pytest.mark.anyio
@pytest.mark.parametrize("platform,count", [("ios", 31), ("android", 30), ("mac", 35)])
async def test_versioned_tool_names_and_secret_ref_schemas_without_driver(platform, count, config_path, monkeypatch):
    forbidden = Mock(side_effect=AssertionError("Discovery attempted a device session"))
    monkeypatch.setattr("autogenesis_appium_mcp.driver_session.webdriver.Remote", forbidden)
    runtime = server.Runtime(platform, config_path)
    try:
        actual = {tool.name: tool.inputSchema for tool in await runtime.server.list_tools()}
        expected = {tool.name: tool.inputSchema for tool in await reference_server(platform).list_tools()}
        assert len(actual) == count and set(actual) == set(expected)
        changed = {"app_launch", "send_keys", "preview_code_changes", "confirm_code_changes", "send_keys_on_macos"}
        assert {name: schema for name, schema in actual.items() if name not in changed} == {
            name: schema for name, schema in expected.items() if name not in changed
        }
        for name in ({"send_keys"} | ({"send_keys_on_macos"} if platform == "mac" else set())):
            variants = actual[name]["properties"]["text"]["anyOf"]
            assert {variant.get("type", "ref") for variant in variants} == {"string", "ref"}
        argument_items = actual["app_launch"]["properties"]["arguments"]["anyOf"][0]["items"]
        assert argument_items == {"type": "string"}
        confirm = actual["confirm_code_changes"]["properties"]
        assert confirm["preview_id"]["default"] == ""
        assert confirm["digest"]["default"] == ""
        assert confirm["approved"]["default"] is False
        assert runtime.driver.device == platform
        assert runtime.driver._driver is None
        assert runtime.config._observer is None
        forbidden.assert_not_called()
    finally:
        runtime.close()


def test_cli_version_does_not_start_runtime(capsys, monkeypatch):
    monkeypatch.setattr(server, "Runtime", Mock(side_effect=AssertionError("version lookup started runtime")))
    with pytest.raises(SystemExit) as caught:
        server.parse_args(["--version"])
    assert caught.value.code == 0
    assert capsys.readouterr() == ("autogenesis-appium-mcp 0.6.0\n", "")


def test_platform_transport_and_config_selection(config_path, tmp_path, monkeypatch):
    defaults = server.parse_args([])
    assert (defaults.platform, defaults.transport, defaults.config, defaults.project_root) == ("ios", "stdio", None, None)
    selected = server.parse_args(["--platform", "mac", "--transport", "stdio", "--config", str(config_path), "--project-root", str(tmp_path)])
    assert (selected.platform, selected.transport, selected.config, selected.project_root) == ("mac", "stdio", str(config_path), str(tmp_path))
    monkeypatch.chdir(tmp_path)
    bundled = ConfigManager()
    assert bundled.initial_loaded and bundled._use_template
    assert set(bundled.get_config()) == {"ios", "android", "mac"}
    bundled.start_watching()
    assert bundled._observer is None
    bundled.stop_watching()
    local = tmp_path / "conf/appium_conf.json"
    local.parent.mkdir()
    local.write_bytes(config_path.read_bytes())
    manager = ConfigManager()
    assert manager.config_path == str(local)
    assert not manager._use_template
    manager.stop_watching()
    runtime = server.Runtime("android", Path("conf/appium_conf.json"))
    assert runtime.driver.device == "android"
    runtime.close()


def test_main_is_sync_and_always_closes(config_path, monkeypatch):
    import inspect
    assert not inspect.iscoroutinefunction(server.main)
    runtimes = []
    real_runtime = server.Runtime

    def factory(platform, config, business_root=None):
        runtime = real_runtime(platform, config, business_root=business_root)
        runtime.server.run = Mock(side_effect=KeyboardInterrupt)
        runtime.driver.session_close = Mock()
        runtimes.append(runtime)
        return runtime

    monkeypatch.setattr(server, "Runtime", factory)
    assert server.main(["--platform", "mac", "--config", str(config_path)]) == 0
    runtime = runtimes[-1]
    runtime.server.run.assert_called_once_with(transport="stdio")
    runtime.driver.session_close.assert_called_once()
    assert runtime._closed and runtime.config._observer is None
    runtime.close()
    runtime.driver.session_close.assert_called_once()


def test_source_entry_delegates_and_explicit_config_wins(config_path, monkeypatch):
    # The clean-wheel verifier copies only this entry script alongside the tests.
    script = Path(__file__).parents[1] / "simple_server.py"
    import sys
    monkeypatch.setattr(sys, "path", sys.path.copy())
    called = Mock(return_value=0)
    monkeypatch.setattr(server, "main", called)
    with pytest.raises(SystemExit) as result:
        runpy.run_path(str(script), run_name="__main__")
    assert result.value.code == 0
    called.assert_called_once_with(default_config=script.resolve().parent / "conf/appium_conf.json")


def test_legacy_config_fallback_and_explicit_override(config_path, tmp_path, monkeypatch):
    selected = []

    class FakeRuntime:
        def __init__(self, platform, path, business_root=None):
            selected.append(path)
            self.server = Mock()
        def close(self):
            pass

    monkeypatch.setattr(server, "Runtime", FakeRuntime)
    assert server.main([], default_config=config_path) == 0
    assert selected[-1] == config_path
    other = tmp_path / "explicit.json"
    assert server.main(["--config", str(other)], default_config=config_path) == 0
    assert selected[-1] == str(other)


def test_atomic_replace_reload_snapshot_and_rejection(config_path):
    runtime = server.Runtime("ios", config_path)
    try:
        replacement = runtime.config.get_config()
        replacement["ios"]["server_url"] = "http://127.0.0.1:4724"
        incoming = config_path.with_suffix(".tmp")
        incoming.write_text(json.dumps({"APPIUM_DRIVER_CONFIGS": replacement}))
        incoming.replace(config_path)
        ConfigFileHandler(runtime.config).on_any_event(FileMovedEvent(str(incoming), str(config_path)))
        assert runtime.driver.server_url == "http://127.0.0.1:4724"
        snapshot = runtime.config.get_config()
        snapshot["ios"]["server_url"] = "mutated"
        assert runtime.config.get_config()["ios"]["server_url"] != "mutated"
        config_path.write_text('{"APPIUM_DRIVER_CONFIGS": {"android": {"server_url": "http://127.0.0.1:9"}}}')
        assert runtime.config.reload_config() is False
        assert runtime.driver.server_url == "http://127.0.0.1:4724"
        assert "ios" in runtime.config.get_config()
        config_path.write_text("invalid JSON")
        assert runtime.config.reload_config() is False
        assert "ios" in runtime.config.get_config()
    finally:
        runtime.close()
    assert runtime.config.reload_config() is False


@pytest.mark.anyio
async def test_real_watcher_hot_reload_and_stop(config_path):
    runtime = server.Runtime("android", config_path)
    runtime.config.start_watching()
    observer = runtime.config._observer
    runtime.config.start_watching()
    assert runtime.config._observer is observer
    try:
        replacement = runtime.config.get_config()
        replacement["android"]["server_url"] = "http://127.0.0.1:4725"
        staged = config_path.with_suffix(".new")
        staged.write_text(json.dumps({"APPIUM_DRIVER_CONFIGS": replacement}))
        staged.replace(config_path)
        with anyio.fail_after(10):
            while runtime.driver.server_url != "http://127.0.0.1:4725":
                await anyio.sleep(0.05)
    finally:
        runtime.close()
    assert not observer.is_alive()
    assert runtime.config._observer is None
    assert runtime.driver._driver is None


@pytest.mark.parametrize("platform", ["ios", "android", "mac"])
def test_shutdown_quits_stale_driver_once(platform, config_path):
    runtime = server.Runtime(platform, config_path)
    driver = Mock()
    driver.get_window_size.side_effect = RuntimeError("Expired session")
    runtime.driver._driver = driver
    runtime.close()
    runtime.close()
    driver.quit.assert_called_once()
    driver.get_window_size.assert_not_called()
    assert runtime.driver._driver is None


def test_session_close_timeout_is_bounded_without_closing_app(config_path, monkeypatch):
    runtime = server.Runtime("mac", config_path)
    release = threading.Event()
    driver = Mock()
    driver.quit.side_effect = lambda: release.wait(timeout=1)
    runtime.driver._driver = driver
    monkeypatch.setattr(driver_session, "SESSION_CLOSE_TIMEOUT_SECONDS", 0.01)

    try:
        with pytest.raises(SessionCloseError, match="AUTOGENESIS_SESSION_CLOSE_TIMEOUT"):
            runtime.driver.session_close()
        driver.quit.assert_called_once()
        driver.terminate_app.assert_not_called()
        assert runtime.driver._driver is driver
    finally:
        release.set()
        runtime.driver.session_close()


def test_timed_out_close_must_settle_before_replacing_driver(config_path, monkeypatch):
    runtime = server.Runtime("mac", config_path)
    release = threading.Event()
    old_driver = Mock()
    old_driver.quit.side_effect = lambda: release.wait(timeout=1)
    runtime.driver._driver = old_driver
    replacement = Mock(capabilities={})
    remote = Mock(return_value=replacement)
    monkeypatch.setattr(driver_session.webdriver, "Remote", remote)
    monkeypatch.setattr(driver_session, "SESSION_CLOSE_TIMEOUT_SECONDS", 0.01)

    with pytest.raises(SessionCloseError, match="AUTOGENESIS_SESSION_CLOSE_TIMEOUT"):
        runtime.driver.session_close()
    with pytest.raises(SessionCloseError, match="AUTOGENESIS_SESSION_CLOSE_IN_PROGRESS"):
        runtime.driver.app_launch()
    remote.assert_not_called()

    release.set()
    runtime.driver._session_close_thread.join(timeout=1)
    with tool_execution(runtime.driver.app_launch, (), {}) as (args, kwargs):
        assert runtime.driver.app_launch(*args, **kwargs) is replacement
    old_driver.quit.assert_called_once()
    runtime.close()
    replacement.quit.assert_called_once()


def test_session_close_failure_is_stable_and_preserves_owned_driver(config_path):
    runtime = server.Runtime("mac", config_path)
    driver = Mock()
    driver.quit.side_effect = RuntimeError("private endpoint response")
    runtime.driver._driver = driver

    with pytest.raises(SessionCloseError, match="AUTOGENESIS_SESSION_CLOSE_FAILED") as caught:
        runtime.driver.session_close()
    assert "private endpoint response" not in str(caught.value)
    driver.quit.assert_called_once()
    driver.terminate_app.assert_not_called()
    assert runtime.driver._driver is driver

def test_reuse_activation_failure_destroys_old_session_before_replacement(config_path, monkeypatch):
    runtime = server.Runtime("ios", config_path)
    old_driver = Mock()
    old_driver.get_window_size.return_value = {"width": 1, "height": 1}
    old_driver.activate_app.side_effect = RuntimeError("activation failed")
    replacement = Mock(capabilities={})
    remote = Mock(return_value=replacement)
    monkeypatch.setattr(driver_session.webdriver, "Remote", remote)
    runtime.driver._driver = old_driver

    with tool_execution(runtime.driver.app_launch, (), {}) as (args, kwargs):
        assert runtime.driver.app_launch(*args, **kwargs) is replacement
    old_driver.quit.assert_called_once()
    remote.assert_called_once()
    assert runtime.driver._driver is replacement
    runtime.close()
    replacement.quit.assert_called_once()


def test_post_creation_failure_destroys_new_owned_session(config_path, monkeypatch):
    runtime = server.Runtime("mac", config_path)
    created = Mock(capabilities={"private": "value"})
    monkeypatch.setattr(driver_session.webdriver, "Remote", Mock(return_value=created))
    monkeypatch.setattr(driver_session, "sanitize_result", Mock(side_effect=RuntimeError("sanitize failed")))
    with tool_execution(runtime.driver.app_launch, (), {}) as (args, kwargs):
        with pytest.raises(RuntimeError, match="sanitize failed"):
            runtime.driver.app_launch(*args, **kwargs)
    created.quit.assert_called_once()
    created.terminate_app.assert_not_called()
    assert runtime.driver._driver is None

def test_constructor_registration_failure_closes_resources(config_path, monkeypatch):
    closed = Mock()
    monkeypatch.setattr(DriverSessionManager, "session_close", closed)
    monkeypatch.setattr(server, "register_mcp", Mock(side_effect=ValueError("registration failed")))
    with pytest.raises(ValueError):
        server.Runtime("ios", config_path)
    closed.assert_called_once()


def test_main_transport_failure_closes_watcher(config_path, monkeypatch):
    instances = []
    real = server.Runtime

    def factory(platform, path, business_root=None):
        runtime = real(platform, path, business_root=business_root)
        instances.append(runtime)
        def fail(**kwargs):
            runtime.config.start_watching()
            raise RuntimeError("transport failed")
        runtime.server.run = fail
        return runtime

    monkeypatch.setattr(server, "Runtime", factory)
    assert server.main(["--config", str(config_path)]) == 1
    assert instances[0]._closed and instances[0].config._observer is None


def test_watcher_start_failure_cleans_partial_observer(config_path, monkeypatch):
    from autogenesis_appium_mcp.utils import config_manager
    observer = Mock()
    observer.schedule.side_effect = RuntimeError("Watcher failure")
    observer.is_alive.return_value = False
    monkeypatch.setattr(config_manager, "Observer", Mock(return_value=observer))
    runtime = server.Runtime("ios", config_path)
    try:
        with pytest.raises(config_manager.ConfigurationError):
            runtime.config.start_watching()
        observer.stop.assert_called_once()
        assert runtime.config._observer is None
    finally:
        runtime.close()


def test_cleanup_releases_driver_even_if_watcher_stop_fails(config_path):
    runtime = server.Runtime("ios", config_path)
    runtime.config.stop_watching = Mock(side_effect=RuntimeError("Watcher stop failure"))
    runtime.driver.session_close = Mock()
    with pytest.raises(RuntimeError):
        runtime.close()
    runtime.driver.session_close.assert_called_once()


def test_session_deletion_failure_outweighs_watcher_failure(config_path):
    runtime = server.Runtime("ios", config_path)
    runtime.config.stop_watching = Mock(side_effect=RuntimeError("Watcher stop failure"))
    runtime.driver.session_close = Mock(side_effect=SessionCloseError("AUTOGENESIS_SESSION_CLOSE_FAILED"))

    with pytest.raises(SessionCloseError, match="AUTOGENESIS_SESSION_CLOSE_FAILED"):
        runtime.close()
    runtime.driver.session_close.assert_called_once()
    with pytest.raises(SessionCloseError, match="AUTOGENESIS_SESSION_CLOSE_FAILED"):
        runtime.close()


def test_interrupted_cleanup_remains_retryable(config_path):
    runtime = server.Runtime("ios", config_path)
    runtime.driver.session_close = Mock(side_effect=[KeyboardInterrupt(), None])

    with pytest.raises(KeyboardInterrupt):
        runtime.close()
    assert not runtime._closed
    runtime.close()
    assert runtime._closed
    assert runtime.driver.session_close.call_count == 2


@pytest.mark.skipif(os.name != "posix", reason="POSIX signal lifecycle")
def test_cleanup_masks_signals_during_session_state_transitions(config_path):
    runtime = server.Runtime("ios", config_path)
    observed = {}

    def close_session():
        observed["sigterm"] = signal.getsignal(signal.SIGTERM)
        observed["sigint"] = signal.getsignal(signal.SIGINT)

    runtime.driver.session_close = close_session
    runtime.close()
    assert observed == {"sigterm": signal.SIG_IGN, "sigint": signal.SIG_IGN}


@pytest.mark.anyio
@pytest.mark.parametrize("fail", [False, True])
async def test_registered_lifespan_starts_and_stops_watcher(config_path, fail):
    runtime = server.Runtime("mac", config_path)
    runtime.driver.session_close = Mock()
    observer = None
    try:
        async with runtime.lifespan(runtime.server):
            observer = runtime.config._observer
            assert observer.is_alive()
            if fail:
                raise RuntimeError("Injected transport failure")
    except RuntimeError:
        assert fail
    assert observer is not None and not observer.is_alive()
    assert runtime._closed and runtime.config._observer is None
    runtime.driver.session_close.assert_called_once()


def test_main_reports_cleanup_failure(config_path, monkeypatch):
    class FakeRuntime:
        def __init__(self, platform, path):
            self.server = Mock()
        def close(self):
            raise RuntimeError("Shutdown failed")
    monkeypatch.setattr(server, "Runtime", FakeRuntime)
    assert server.main(["--config", str(config_path)]) == 1


@pytest.mark.anyio
async def test_take_screenshot_executes_with_lazy_mocked_llm(config_path, tmp_path, monkeypatch):
    from autogenesis_appium_mcp.llm import chat
    from autogenesis_appium_mcp.tools import appium_driver_tool
    llm = Mock()
    llm.compress_image.return_value = b"compressed-test-image"
    constructor = Mock(return_value=llm)
    monkeypatch.setattr(chat, "LLMClient", constructor)
    runtime = server.Runtime("ios", config_path)
    driver = Mock()
    driver.get_screenshot_as_png.return_value = b"test-image"
    runtime.driver._driver = driver
    destination = tmp_path / "screenshot.png"
    try:
        assert "LLMClient" not in appium_driver_tool.__dict__
        constructor.assert_not_called()
        response = await runtime.server.call_tool("take_screenshot", {"save_path": str(destination)})
        content = response[0] if isinstance(response, tuple) else response
        result = json.loads(content[0].text)
        assert result["status"] == "success"
        driver.get_screenshot_as_png.assert_called_once_with()
        constructor.assert_called_once_with()
        llm.compress_image.assert_called_once_with(image_data=b"test-image")
        assert destination.read_bytes() == b"compressed-test-image"
    finally:
        runtime.close()
