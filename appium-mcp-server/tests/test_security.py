import ast
import io
import json
import logging
import os
from unittest.mock import Mock

import pytest
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

from autogenesis_agent_contract import SecretRef, SecretReferenceError, serialize
from autogenesis_appium_mcp import server
from autogenesis_appium_mcp.tools.config_tool import register_config_tools
from autogenesis_appium_mcp.utils.config_manager import ConfigManager
from autogenesis_appium_mcp.utils.logger import SafeFormatter, log_tool_call
from autogenesis_appium_mcp.utils.page_source import sanitize_page_source

PRIVATE = "SYNTHETIC_APPIUM_PRIVATE_9EA174"


def ref(name="AUTOGENESIS_TEST_PASSWORD"):
    return {"$secret": f"env:{name}"}


def result_payload(result):
    content = result[0] if isinstance(result, tuple) else result
    return json.loads(content[0].text)


def test_config_retains_refs_and_rejects_plaintext_credentials(tmp_path, monkeypatch):
    monkeypatch.setenv("BROWSERSTACK_ACCESS_KEY", PRIVATE)
    path = tmp_path / "appium.json"
    path.write_text(json.dumps({"APPIUM_DRIVER_CONFIGS": {"ios": {
        "server_url": "http://127.0.0.1:9",
        "bstack:options": {"accessKey": "${BROWSERSTACK_ACCESS_KEY}"},
    }}}))
    manager = ConfigManager(path)
    try:
        config = manager.get_platform_config("ios")
        assert serialize(config["bstack:options"]["accessKey"]) == ref("BROWSERSTACK_ACCESS_KEY")
        assert PRIVATE not in json.dumps(serialize(manager.get_config()))

        path.write_text(json.dumps({"APPIUM_DRIVER_CONFIGS": {"ios": {
            "server_url": "http://127.0.0.1:9", "accessKey": PRIVATE,
        }}}))
        assert manager.reload_config() is False
        assert serialize(manager.get_platform_config("ios")["bstack:options"]["accessKey"]) == ref("BROWSERSTACK_ACCESS_KEY")
    finally:
        manager.stop_watching()


@pytest.mark.anyio
async def test_config_tool_returns_refs_not_resolved_values(tmp_path, monkeypatch):
    monkeypatch.setenv("BROWSERSTACK_ACCESS_KEY", PRIVATE)
    path = tmp_path / "appium.json"
    path.write_text(json.dumps({"APPIUM_DRIVER_CONFIGS": {"ios": {
        "server_url": "http://127.0.0.1:9",
        "bstack:options": {"accessKey": "${BROWSERSTACK_ACCESS_KEY}"},
    }}}))
    manager = ConfigManager(path)
    mcp = FastMCP("config-secret-ref")
    register_config_tools(mcp, manager)
    try:
        result = await mcp.call_tool("get_current_config", {"platform": "ios"})
        rendered = str(result)
        assert PRIVATE not in rendered
        assert "env:BROWSERSTACK_ACCESS_KEY" in rendered
    finally:
        manager.stop_watching()


def test_payload_free_diagnostics_never_render_arguments():
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(SafeFormatter())
    record = logging.LogRecord("httpx", logging.ERROR, "", 1, "request %s", (PRIVATE,), None)
    handler.handle(record)
    assert PRIVATE not in stream.getvalue()
    assert "Runtime dependency diagnostic" in stream.getvalue()


@pytest.mark.anyio
async def test_secret_ref_executes_records_previews_confirms_and_replays(config_path, tmp_path, monkeypatch):
    from autogenesis_appium_mcp.tools import appium_driver_tool

    monkeypatch.setenv("AUTOGENESIS_TEST_PASSWORD", PRIVATE)
    runtime = server.Runtime("ios", config_path)
    driver = Mock()
    element = Mock()
    element.get_attribute.side_effect = lambda name: "true" if name == "password" else ""
    wait = Mock()
    wait.until.return_value = element
    monkeypatch.setattr(appium_driver_tool, "WebDriverWait", Mock(return_value=wait))
    driver.page_source = '<hierarchy><node password="true" text="' + PRIVATE + '"/></hierarchy>'
    runtime.driver._driver = driver
    destination = tmp_path / "steps/replay.py"

    try:
        await runtime.server.call_tool("before_gen_code", {"step_file": str(destination)})
        response = await runtime.server.call_tool("send_keys", {
            "caller": "test", "locator_value": "password", "locator_strategy": "id",
            "text": ref(), "step": "When enter the bound password",
        })
        assert result_payload(response)["status"] == "success"
        element.send_keys.assert_called_once_with(PRIVATE)
        recorded = runtime.driver.gen_code_cache[0]["tool_params"]["text"]
        assert isinstance(recorded, SecretRef)
        assert serialize(recorded) == ref()
        assert PRIVATE not in json.dumps(serialize(runtime.driver.gen_code_cache))

        preview = result_payload(await runtime.server.call_tool("preview_code_changes", {}))
        assert "env:AUTOGENESIS_TEST_PASSWORD" in preview["data"]["diff_preview"]
        assert PRIVATE not in json.dumps(preview)
        proposed = "".join(runtime.driver.proposed_changes)
        assert "env:AUTOGENESIS_TEST_PASSWORD" in proposed
        assert "[REDACTED]" not in proposed

        await runtime.server.call_tool("confirm_code_changes", {})
        written = destination.read_text()
        assert PRIVATE not in written and "[REDACTED]" not in written
        append_payload = preview["data"]["append_payload"]
        tree = ast.parse(written)
        refs = [node for node in ast.walk(tree) if isinstance(node, ast.Dict)
                and any(isinstance(key, ast.Constant) and key.value == "$secret" for key in node.keys)]
        assert refs

        # Replay uses the persisted reference and resolves it only for execution.
        assert written == append_payload
        element.send_keys.reset_mock()
        runtime.driver.gen_code_id = None
        await runtime.server.call_tool("send_keys", {
            "caller": "replay", "locator_value": "password", "locator_strategy": "id",
            "text": ref(),
        })
        element.send_keys.assert_called_once_with(PRIVATE)
    finally:
        runtime.close()


@pytest.mark.anyio
async def test_plaintext_secure_input_requires_binding_before_preview(config_path, tmp_path, monkeypatch):
    from autogenesis_appium_mcp.tools import appium_driver_tool

    runtime = server.Runtime("ios", config_path)
    driver = Mock()
    element = Mock()
    element.get_attribute.side_effect = lambda name: "true" if name == "password" else ""
    wait = Mock()
    wait.until.return_value = element
    monkeypatch.setattr(appium_driver_tool, "WebDriverWait", Mock(return_value=wait))
    driver.page_source = '<hierarchy><node password="true" text="' + PRIVATE + '"/></hierarchy>'
    runtime.driver._driver = driver
    destination = tmp_path / "steps/replay.py"
    monkeypatch.setenv("AUTOGENESIS_BOUND_PASSWORD", PRIVATE)

    try:
        await runtime.server.call_tool("before_gen_code", {"step_file": str(destination)})
        await runtime.server.call_tool("send_keys", {
            "caller": "test", "locator_value": "password", "locator_strategy": "id",
            "text": PRIVATE, "step": "When enter a password",
        })
        cache = serialize(runtime.driver.gen_code_cache)
        assert PRIVATE not in json.dumps(cache)

        with pytest.raises(ToolError, match="AUTOGENESIS_SECRET_BINDING_REQUIRED"):
            await runtime.server.call_tool("preview_code_changes", {})
        assert not destination.exists()

        preview = result_payload(await runtime.server.call_tool("preview_code_changes", {
            "secret_bindings": {"send_keys.text": ref("AUTOGENESIS_BOUND_PASSWORD")},
        }))
        assert "env:AUTOGENESIS_BOUND_PASSWORD" in preview["data"]["diff_preview"]
        append_payload = preview["data"]["append_payload"]
        await runtime.server.call_tool("confirm_code_changes", {})
        written = destination.read_text()
        assert PRIVATE not in written
        assert written == append_payload
        assert "env:AUTOGENESIS_BOUND_PASSWORD" in written
    finally:
        runtime.close()


@pytest.mark.anyio
async def test_embedded_plaintext_secret_requires_step_reauthoring(config_path, tmp_path, monkeypatch):
    from autogenesis_appium_mcp.tools import appium_driver_tool

    runtime = server.Runtime("ios", config_path)
    element = Mock()
    element.get_attribute.side_effect = lambda name: "true" if name == "password" else ""
    wait = Mock()
    wait.until.return_value = element
    monkeypatch.setattr(appium_driver_tool, "WebDriverWait", Mock(return_value=wait))
    runtime.driver._driver = Mock(page_source='<hierarchy><node password="true"/></hierarchy>')
    try:
        await runtime.server.call_tool("before_gen_code", {"step_file": str(tmp_path / "steps.py")})
        await runtime.server.call_tool("send_keys", {
            "caller": "test", "locator_value": "password", "locator_strategy": "id",
            "text": PRIVATE, "step": f'When enter "{PRIVATE}"',
        })
        cache = serialize(runtime.driver.gen_code_cache)
        assert PRIVATE not in json.dumps(cache)
        assert cache[0]["step"] == "Secret-bearing step requires re-authoring"
        assert cache[0]["secret_requirements"] == [{"$secret": "unbound:reauthor.send_keys.step"}]
        with pytest.raises(ToolError, match="AUTOGENESIS_SECRET_REFERENCE_REQUIRED: reauthor.send_keys.step"):
            await runtime.server.call_tool("preview_code_changes", {
                "secret_bindings": {"send_keys.text": ref("AUTOGENESIS_BOUND_PASSWORD")},
            })
    finally:
        runtime.close()

@pytest.mark.anyio
async def test_server_masks_non_secretref_tool_errors_for_every_transport(config_path):
    runtime = server.Runtime("ios", config_path)
    try:
        with pytest.raises(ToolError) as caught:
            await runtime.server.call_tool(PRIVATE, {"text": PRIVATE})
        assert PRIVATE not in str(caught.value)
        assert str(caught.value) == "AutoGenesis tool request failed"
    finally:
        runtime.close()

@pytest.mark.anyio
async def test_stdio_preserves_binding_error_and_masks_arbitrary_tool_error():
    from autogenesis_appium_mcp.stdio import Stdout

    read_fd, write_fd = os.pipe()
    try:
        writer = Stdout(write_fd)
        await writer.write(json.dumps({
            "jsonrpc": "2.0", "id": 1,
            "result": {"isError": True, "content": [{"type": "text", "text":
                "Error executing tool: AUTOGENESIS_SECRET_BINDING_REQUIRED: send_keys.text"}]},
        }))
        await writer.write(json.dumps({
            "jsonrpc": "2.0", "id": 2,
            "result": {"isError": True, "content": [{"type": "text", "text": PRIVATE}]},
        }))
        os.close(write_fd)
        write_fd = None
        frames = [json.loads(line) for line in os.read(read_fd, 8192).decode().splitlines()]
        assert frames[0]["result"]["content"][0]["text"] == "AUTOGENESIS_SECRET_BINDING_REQUIRED: send_keys.text"
        assert PRIVATE not in json.dumps(frames[1])
    finally:
        os.close(read_fd)
        if write_fd is not None:
            os.close(write_fd)




@pytest.mark.anyio
async def test_secret_ref_rejects_non_secure_appium_target(config_path, monkeypatch):
    from autogenesis_appium_mcp.tools import appium_driver_tool

    monkeypatch.setenv("AUTOGENESIS_TEST_PASSWORD", PRIVATE)
    runtime = server.Runtime("ios", config_path)
    element = Mock()
    element.get_attribute.return_value = ""
    wait = Mock()
    wait.until.return_value = element
    monkeypatch.setattr(appium_driver_tool, "WebDriverWait", Mock(return_value=wait))
    runtime.driver._driver = Mock(page_source='<hierarchy><node text="ordinary"/></hierarchy>')
    try:
        with pytest.raises(ToolError, match="AUTOGENESIS_SECRET_REFERENCE_INVALID: text"):
            await runtime.server.call_tool("send_keys", {
                "caller": "test", "locator_value": "search", "locator_strategy": "id", "text": ref(),
            })
    finally:
        runtime.close()


@pytest.mark.anyio
async def test_driver_retains_no_resolved_capability_plaintext(tmp_path, monkeypatch):
    from autogenesis_appium_mcp import driver_session

    monkeypatch.setenv("APPIUM_ACCESS_KEY", PRIVATE)
    config = tmp_path / "appium.json"
    config.write_text(json.dumps({"APPIUM_DRIVER_CONFIGS": {"ios": {
        "server_url": "http://127.0.0.1:9",
        "platformName": "ios",
        "accessKey": "${APPIUM_ACCESS_KEY}",
    }}}))
    remote = Mock()
    remote.capabilities = {"customEcho": PRIVATE, "accessKey": PRIVATE}
    remote.page_source = '<hierarchy><node text="ordinary"/></hierarchy>'
    monkeypatch.setattr(driver_session.webdriver, "Remote", Mock(return_value=remote))
    runtime = server.Runtime("ios", config)
    try:
        payload = result_payload(await runtime.server.call_tool("app_launch", {}))
        assert payload["status"] == "success"
        assert PRIVATE not in json.dumps(remote.capabilities)
        assert remote.capabilities["customEcho"] == "[REDACTED]"
    finally:
        runtime.close()

@pytest.mark.anyio
async def test_ios_dismiss_alert_structurally_sanitizes_page_source(config_path, monkeypatch):
    from autogenesis_appium_mcp.tools import ios_driver_tool

    runtime = server.Runtime("ios", config_path)
    alert = Mock()
    driver = Mock(page_source='<hierarchy><node password="true" value="' + PRIVATE + '"/></hierarchy>')
    driver.switch_to.alert = alert
    wait = Mock()
    wait.until.return_value = True
    monkeypatch.setattr(ios_driver_tool, "WebDriverWait", Mock(return_value=wait))
    runtime.driver._driver = driver
    try:
        payload = result_payload(await runtime.server.call_tool("dismiss_alert", {"caller": "test"}))
        assert PRIVATE not in json.dumps(payload)
        assert "[REDACTED]" in payload["data"]["page_source"]
        alert.dismiss.assert_called_once_with()
    finally:
        runtime.close()


@pytest.mark.anyio
async def test_blind_text_entry_requires_reauthoring_before_preview(config_path, tmp_path):
    runtime = server.Runtime("ios", config_path)
    runtime.driver._driver = Mock()
    try:
        await runtime.server.call_tool("before_gen_code", {"step_file": str(tmp_path / "steps.py")})
        await runtime.server.call_tool("directly_send_keys", {
            "caller": "test", "text": PRIVATE, "step": "When type into the focused field",
        })
        assert runtime.driver.gen_code_cache == []
        with pytest.raises(ToolError, match="AUTOGENESIS_SECRET_REFERENCE_REQUIRED: reauthor.directly_send_keys"):
            await runtime.server.call_tool("preview_code_changes", {})
    finally:
        runtime.close()

@pytest.mark.parametrize("encoded", ["p&amp;ss", "p&#38;ss", "p&#x26;ss", "&#97;"])
def test_secure_xml_entities_are_structurally_sanitized(encoded):
    import xml.etree.ElementTree as ET

    source = ('<hierarchy><node password="true" text="' + encoded + '" value="' + encoded +
              '" label="' + encoded + '" content-desc="' + encoded + '">' + encoded +
              '</node><node text="application data"/></hierarchy>')
    output = sanitize_page_source(source)
    tree = ET.fromstring(output)
    assert tree[0].get("text") == tree[0].get("value") == tree[0].get("label") == tree[0].get("content-desc") == tree[0].text == "[REDACTED]"
    assert tree[1].get("text") == "application data"


def test_malformed_page_source_fails_closed():
    assert sanitize_page_source('<hierarchy><node password="true" text="' + PRIVATE + '"') == (
        "<hierarchy><summary>Page source unavailable</summary></hierarchy>"
    )


def test_startup_error_is_private_and_stdout_empty(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(server, "configure_logging", lambda: None)
    path = tmp_path / (PRIVATE + ".json")
    path.write_text(PRIVATE)
    assert server.main(["--config", str(path)]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert PRIVATE not in captured.err


def test_llm_client_retains_reference_not_api_key(monkeypatch):
    from autogenesis_appium_mcp.llm import chat

    monkeypatch.setenv("AZURE_OPENAI_API_KEY", PRIVATE)
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://example.invalid")
    monkeypatch.setattr(chat, "load_dotenv", lambda: None)
    client = chat.LLMClient()
    assert not hasattr(client, "api_key")
    assert serialize(client.api_key_ref) == {"$secret": "env:AZURE_OPENAI_API_KEY"}
