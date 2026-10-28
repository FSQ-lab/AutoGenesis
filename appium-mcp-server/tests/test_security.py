import io
import json
import logging
from unittest.mock import Mock

import pytest
from mcp.server.fastmcp import FastMCP

from autogenesis_appium_mcp import server
from autogenesis_appium_mcp.tools.config_tool import register_config_tools
from autogenesis_appium_mcp.utils.config_manager import ConfigManager
from autogenesis_appium_mcp.utils.logger import SafeFormatter, log_tool_call
from autogenesis_appium_mcp.utils.redaction import config_view, redact

PRIVATE = "SYNTHETIC_APPIUM_PRIVATE_9EA174"


def test_recursive_config_masking_including_unknown_keys_and_url():
    value = {
        "server_url": "https://user:" + PRIVATE + "@localhost/?token=" + PRIVATE,
        "bstack:options": {"accessKey": PRIVATE, PRIVATE: [PRIVATE, {"notes": PRIVATE}]},
        "arguments": ["--password=" + PRIVATE], "text": PRIVATE,
    }
    assert PRIVATE not in json.dumps(config_view(value))
    assert config_view(value)["server_url"] == "[REDACTED]"


def test_env_reference_resolution_and_bad_reload_are_private(tmp_path, monkeypatch, caplog):
    monkeypatch.setenv("APPIUM_TEST_ACCESS_KEY", PRIVATE)
    path = tmp_path / "appium.json"
    reference = "$" + "{APPIUM_TEST_ACCESS_KEY}"
    path.write_text(json.dumps({"APPIUM_DRIVER_CONFIGS": {"ios": {
        "server_url": "http://127.0.0.1:9", "bstack:options": {"accessKey": reference},
    }}}))
    manager = ConfigManager(path)
    assert manager.initial_loaded
    assert manager.get_platform_config("ios")["bstack:options"]["accessKey"] == PRIVATE
    monkeypatch.delenv("APPIUM_TEST_ACCESS_KEY")
    assert manager.reload_config() is False
    assert PRIVATE not in caplog.text
    manager.stop_watching()


@pytest.mark.anyio
async def test_config_tools_never_return_private_data(tmp_path):
    path = tmp_path / "appium.json"
    path.write_text(json.dumps({"APPIUM_DRIVER_CONFIGS": {"ios": {
        "server_url": PRIVATE, "bstack:options": {"accessKey": PRIVATE}, PRIVATE: PRIVATE,
    }}}))
    manager = ConfigManager(path)
    mcp = FastMCP("config-redaction")
    register_config_tools(mcp, manager)
    try:
        for name, arguments in [
            ("get_current_config", {}), ("get_current_config", {"platform": "ios"}),
            ("get_current_config", {"platform": PRIVATE}), ("reload_config", {}),
        ]:
            result = await mcp.call_tool(name, arguments)
            assert PRIVATE not in str(result)
    finally:
        manager.stop_watching()


@pytest.mark.anyio
async def test_tool_logs_results_and_errors_redact_private_arguments(caplog):
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(SafeFormatter())
    logger = logging.getLogger("autogenesis_appium_mcp")
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    try:
        @log_tool_call
        async def sample(text, nested):
            logger.warning("Driver response %s", text)
            return {"text": text, "nested": nested}
        output = await sample(text=PRIVATE, nested={"accessKey": PRIVATE, "items": [PRIVATE]})
        assert PRIVATE not in json.dumps(output) + stream.getvalue()

        @log_tool_call
        async def failing(text):
            raise RuntimeError(text)
        with pytest.raises(RuntimeError) as caught:
            await failing(text=PRIVATE)
        assert PRIVATE not in str(caught.value) + stream.getvalue()
    finally:
        logger.removeHandler(handler)
        logger.setLevel(logging.NOTSET)


@pytest.mark.anyio
async def test_sdk_validation_and_unknown_tool_errors_are_private(config_path):
    runtime = server.Runtime("ios", config_path)
    try:
        for name, arguments in [
            (PRIVATE, {}), ("get_current_config", {"platform": {PRIVATE: PRIVATE}}),
        ]:
            with pytest.raises(ValueError) as caught:
                await runtime.server.call_tool(name, arguments)
            assert PRIVATE not in str(caught.value)
    finally:
        runtime.close()


@pytest.mark.anyio
@pytest.mark.parametrize("secret,public", [("admin", "administrator"), ("success", "successful")])
async def test_retained_words_preserve_public_text_and_controlled_status(secret, public):
    @log_tool_call
    async def credential_tool(password):
        return {"status": "success", "data": {"public": public, "echo": password}}

    first = await credential_tool(password=secret)
    assert first == {"status": "success", "data": {"public": public, "echo": "[REDACTED]"}}
    later = redact({"status": "success", "data": {secret: public, "code": "password = '" + secret + "'",
                   "url": "https://user:" + secret + "@example.test/?password=" + secret}})
    assert later["status"] == "success"
    assert later["data"][secret] == public
    assert later["data"]["code"] == "password = '[REDACTED]'"
    assert later["data"]["url"] == "https://user:[REDACTED]@example.test/?password=[REDACTED]"


@pytest.mark.anyio
async def test_json_looking_ordinary_arguments_never_register_credentials():
    from autogenesis_appium_mcp.utils import redaction

    @log_tool_call
    async def ordinary_text(text):
        return {"status": "success", "data": {"text": "administrator", "standalone": "admin"}}

    before = redaction._values.copy()
    for text in ('{"token":"admin"}', '{token:admin}', '[{"password":"admin"}]'):
        output = await ordinary_text(text=text)
        assert output["data"] == {"text": "administrator", "standalone": "admin"}
        assert redaction._values == before
    redaction.remember_configuration({"text": '{"token":"admin"}'})
    assert redaction._values == before
    # Serialized output can be masked structurally without poisoning future calls.
    assert "admin" not in redaction.redact('{"token":"admin"}')
    assert redaction._values == before
    assert redaction.redact({"data": "admin"}) == {"data": "admin"}


@pytest.mark.anyio
@pytest.mark.parametrize("mode", ["password", "short_password", "overflow_password", "public", "public_json_control", "public_json_token"])
async def test_record_preview_confirm_file_redacts_only_actual_passwords(config_path, tmp_path, monkeypatch, mode):
    import ast
    import xml.etree.ElementTree as ET
    from autogenesis_appium_mcp.tools import appium_driver_tool
    from autogenesis_appium_mcp.utils import redaction
    private = mode in {"password", "short_password", "overflow_password"}
    value = {"short_password": "a", "public": "a", "public_json_control": '{"password":true,"text":"a"}',
             "public_json_token": '{"token":"admin"}'}.get(mode, PRIVATE)
    if mode == "overflow_password":
        monkeypatch.setattr(redaction, "_MAX_VALUE_BYTES", 1)
    root = ET.Element("hierarchy")
    ET.SubElement(root, "node", {"text": value, **({"password": "true"} if private else {})})
    source = ET.tostring(root, encoding="unicode")
    driver = Mock(page_source=source)
    element = Mock()
    wait = Mock()
    wait.until.return_value = element
    monkeypatch.setattr(appium_driver_tool, "WebDriverWait", Mock(return_value=wait))
    runtime = server.Runtime("ios", config_path)
    runtime.driver._driver = driver
    destination = tmp_path / "steps/replay.py"

    async def call(name, arguments):
        result = await runtime.server.call_tool(name, arguments)
        content = result[0] if isinstance(result, tuple) else result
        payload = json.loads(content[0].text)
        assert payload["status"] == "success"
        return payload

    try:
        await call("before_gen_code", {"step_file": str(destination)})
        await call("send_keys", {"caller": "test", "locator_value": "password-input" if private else "title-input",
                   "locator_strategy": "id", "text": value, "step": "When enter public label"})
        element.send_keys.assert_called_once_with(value)
        expected = "[REDACTED]" if private else value
        assert runtime.driver.gen_code_cache[0]["tool_params"]["text"] == expected
        assert redaction._tool_values.get() is None
        if not private:
            assert "a" not in redaction._values and "admin" not in redaction._values
            assert redact({"data": ["a", "admin"]}) == {"data": ["a", "admin"]}
        if mode == "overflow_password":
            assert value not in redaction._values
        preview = await call("preview_code_changes", {})
        proposed = "".join(runtime.driver.proposed_changes)
        assert "enter public label" in preview["data"]["diff_preview"]
        if private:
            assert "'text': '" + value + "'" not in proposed
            assert "'text': '[REDACTED]'" in preview["data"]["diff_preview"]
            assert "'text': '[REDACTED]'" in proposed
        await call("confirm_code_changes", {})
        written = destination.read_text()
        assert "enter public label" in written
        tree = ast.parse(written)
        recorded_text = [v.value for node in ast.walk(tree) if isinstance(node, ast.Dict)
                         for k, v in zip(node.keys, node.values)
                         if isinstance(k, ast.Constant) and k.value == "text" and isinstance(v, ast.Constant)]
        assert recorded_text == [expected]
        if private and value != "a":
            assert value not in json.dumps(preview) + proposed + written
    finally:
        runtime.close()


def test_startup_error_is_private_and_stdout_empty(tmp_path, capsys, monkeypatch):
    # Do not replace pytest's capture handlers when exercising main in-process.
    monkeypatch.setattr(server, "configure_logging", lambda: None)
    path = tmp_path / (PRIVATE + ".json")
    path.write_text(PRIVATE)
    assert server.main(["--config", str(path)]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert PRIVATE not in captured.err


def test_escaped_nested_credentials_and_diagnostic_tracebacks():
    value = PRIVATE + "\\quoted"
    payload = json.dumps({"nested": json.dumps({"password": value})})
    assert PRIVATE not in redact(payload)
    try:
        raise ValueError(PRIVATE)
    except ValueError:
        import sys
        record = logging.LogRecord("driver", logging.ERROR, "", 1, "Driver failed", (), sys.exc_info())
    assert PRIVATE not in SafeFormatter().format(record)


def test_llm_initialization_does_not_log_api_key_or_client_state(monkeypatch, caplog):
    from autogenesis_appium_mcp.llm import chat
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", PRIVATE)
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://example.invalid")
    monkeypatch.setattr(chat, "load_dotenv", lambda: None)
    with caplog.at_level(logging.INFO):
        client = chat.LLMClient()
    assert client.api_key == PRIVATE
    assert PRIVATE not in caplog.text


def test_invalid_cli_choice_does_not_echo_private_input(capsys):
    with pytest.raises(SystemExit) as caught:
        server.parse_args(["--platform", PRIVATE])
    assert caught.value.code == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert PRIVATE not in captured.err


def test_contract_startup_errors_keep_sanitized_machine_code(config_path, monkeypatch, capsys):
    from autogenesis_agent_contract import RuntimeContractRequirement
    monkeypatch.setattr(server, "REQUIREMENT", RuntimeContractRequirement("2.0.0", server.REQUIREMENT.manifest_sha256))
    assert server.main(["--config", str(config_path)]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    diagnostic = json.loads(captured.err)
    assert diagnostic["code"] == "AUTOGENESIS_CONTRACT_MISMATCH"
    assert PRIVATE not in captured.err


@pytest.mark.anyio
async def test_common_tool_arguments_preserve_unrelated_response_fields_and_code(config_path):
    runtime = server.Runtime("ios", config_path)
    payload = {
        "status": "success",
        "data": {"title": "application", "text": "a", "keyboard": "available", "token_count": 3,
                 "step": "a normal step", "generated_code": "data = 'a'\nassert data == 'a'\n"},
    }

    @runtime.server.tool()
    @log_tool_call
    async def normal_input(text: str, title: str, locator: str, step: str) -> str:
        return json.dumps(json.dumps(payload))

    @runtime.server.tool()
    @log_tool_call
    async def later_output() -> str:
        return json.dumps(json.dumps(payload))

    try:
        first = await runtime.server.call_tool("normal_input", {"text": "a", "title": "ok", "locator": "title", "step": "a"})
        later = await runtime.server.call_tool("later_output", {})
        for response in (first, later):
            content = response[0] if isinstance(response, tuple) else response
            assert json.loads(content[0].text) == payload
        from autogenesis_appium_mcp.utils import redaction
        assert "a" not in redaction._values
        assert "ok" not in redaction._values
        # Query text and unfamiliar capability labels are ordinary data too.
        redaction.remember_configuration({"title": "a", "server_url": "http://localhost/?q=ok"})
        assert redact(payload) == payload
    finally:
        runtime.close()


@pytest.mark.parametrize("control", [
    {"password": True, "text": PRIVATE},
    {"type": "XCUIElementTypeSecureTextField", "value": PRIVATE},
    {"subrole": "AXSecureTextField", "value": PRIVATE},
])
def test_actual_password_control_content_is_private(control):
    output = redact({"status": "success", "data": {"control": control, "echo": PRIVATE}})
    assert PRIVATE not in json.dumps(output)
    assert output["status"] == "success"
    assert output["data"]["control"].get("type") == control.get("type")


def test_password_xml_is_private_but_normal_page_source_is_unchanged():
    normal = '<node type="TextField" text="a" value="status" />'
    assert redact(normal) == normal
    source = '<hierarchy><node password="true" text="' + PRIVATE + '"/><node text="a"/></hierarchy>'
    output = redact({"status": "success", "data": {"page_source": source}})
    assert PRIVATE not in json.dumps(output)
    import xml.etree.ElementTree as ET
    assert ET.fromstring(output["data"]["page_source"])[1].get("text") == "a"


@pytest.mark.anyio
async def test_rejected_requests_cannot_poison_later_outputs(config_path):
    from autogenesis_appium_mcp.utils import redaction
    runtime = server.Runtime("ios", config_path)
    observed = []
    payload = {"status": "success", "data": {"title": "application", "text": "a", "generated_code": "data = 'a'\n"}}

    @runtime.server.tool()
    @log_tool_call
    async def credential_input(access_key: str) -> str:
        observed.append(access_key in redaction._values)
        return json.dumps(json.dumps({"status": "success", "data": {"echo": access_key}}))

    @runtime.server.tool()
    @log_tool_call
    async def frozen_output() -> str:
        return json.dumps(json.dumps(payload))

    try:
        before = redaction._values.copy()
        for name, arguments in [
            ("not_registered", {"token": "a"}),
            ("credential_input", {"access_key": {"token": "a"}}),
        ]:
            with pytest.raises(ValueError):
                await runtime.server.call_tool(name, arguments)
            assert redaction._values == before
        output = await runtime.server.call_tool("frozen_output", {})
        content = output[0] if isinstance(output, tuple) else output
        assert json.loads(content[0].text) == payload
        protected = await runtime.server.call_tool("credential_input", {"access_key": PRIVATE})
        assert observed == [True]
        assert PRIVATE not in str(protected)
    finally:
        runtime.close()


@pytest.mark.parametrize("summary_only", [False, True])
def test_raw_password_page_source_is_private_before_file_and_summary(tmp_path, monkeypatch, summary_only):
    from autogenesis_appium_mcp.utils import element_util, response_format
    raw = '<hierarchy><node password="true" text="' + PRIVATE + '"/><node text="ordinary"/></hierarchy>'
    destination = tmp_path / "page-source.xml"
    sinks = []

    def simplify(source):
        sinks.append(source)
        # Simulate the original loss of password-control metadata during simplification.
        return source.replace('password="true"', '')

    def summarize(source):
        sinks.append(source)
        return {"summary": source}

    monkeypatch.setattr(element_util, "simplify_page_source", simplify)
    monkeypatch.setattr(element_util, "summarize_page_source", summarize)
    response = response_format.init_tool_response()
    response_format.handle_page_source(response, raw, str(destination), summary_only)
    assert sinks and all(PRIVATE not in value for value in sinks)
    assert PRIVATE not in destination.read_text()
    assert PRIVATE not in json.dumps(response)
    assert "ordinary" in destination.read_text()
    assert 'password="true"' in sinks[0]


@pytest.mark.anyio
@pytest.mark.parametrize("source", ["credential", "password_control"])
async def test_valid_short_secrets_redact_boundaries_without_corrupting_future_output(config_path, source):
    runtime = server.Runtime("ios", config_path)
    payload = {
        "status": "success",
        "data": {"a": "mapping key", "text": "status data application", "token_count": 1,
                 "standalone": "a", "quoted": "data = 'a'", "unicode_word": "éaé",
                 "url": "https://a:a@example.test/a?password=a#token=a"},
    }

    @runtime.server.tool()
    @log_tool_call
    async def accept_credential(access_key: str) -> str:
        return json.dumps(json.dumps({"status": "success", "data": {"echo": access_key}}))

    @runtime.server.tool()
    @log_tool_call
    async def secure_control() -> str:
        return json.dumps(json.dumps({"status": "success", "data": {"password": True, "text": "a", "value": "a"}}))

    @runtime.server.tool()
    @log_tool_call
    async def snapshot_preview() -> str:
        return json.dumps(json.dumps(payload))

    try:
        result = await runtime.server.call_tool(
            "accept_credential" if source == "credential" else "secure_control",
            {"access_key": "a"} if source == "credential" else {},
        )
        content = result[0] if isinstance(result, tuple) else result
        initial = json.loads(content[0].text)
        assert "a" not in initial["data"].values()
        later = await runtime.server.call_tool("snapshot_preview", {})
        content = later[0] if isinstance(later, tuple) else later
        output = json.loads(content[0].text)
        assert output == {
            "status": "success",
            "data": {"a": "mapping key", "text": "status data application", "token_count": 1,
                     "standalone": "[REDACTED]", "quoted": "data = '[REDACTED]'", "unicode_word": "éaé",
                     "url": "https://[REDACTED]:[REDACTED]@example.test/[REDACTED]?password=[REDACTED]#token=[REDACTED]"},
        }
    finally:
        runtime.close()


def test_secret_registry_bounds_count_bytes_and_refreshes_recent_values(monkeypatch):
    from autogenesis_appium_mcp.utils import redaction
    monkeypatch.setattr(redaction, "_MAX_VALUES", 3)
    monkeypatch.setattr(redaction, "_MAX_VALUE_BYTES", 12)
    for value in ("one", "two", "three"):
        redaction.remember_tool_arguments({"password": value})
    redaction.remember_tool_arguments({"password": "one"})
    redaction.remember_tool_arguments({"password": "four"})
    assert list(redaction._values) == ["three", "one", "four"]
    assert len(redaction._values) <= 3
    assert sum(len(value.encode("utf-8")) for value in redaction._values) <= 12
    redaction.remember_tool_arguments({"password": "éééé"})
    assert list(redaction._values) == ["four", "éééé"]
    assert sum(len(value.encode("utf-8")) for value in redaction._values) == 12
    huge = PRIVATE * 10
    output = redaction.redact({"password": huge, "echo": huge})
    assert huge not in redaction._values
    assert PRIVATE not in json.dumps(output)
    assert len(redaction._values) <= 3
    assert sum(len(value.encode("utf-8")) for value in redaction._values) <= 12


@pytest.mark.anyio
async def test_oversized_valid_tool_credential_is_private_without_retention(monkeypatch):
    from autogenesis_appium_mcp.utils import redaction
    monkeypatch.setattr(redaction, "_MAX_VALUE_BYTES", 8)

    @log_tool_call
    async def echo(access_key):
        return {"data": {"echo": access_key}}

    output = await echo(access_key=PRIVATE)
    assert PRIVATE not in json.dumps(output)
    assert PRIVATE not in redaction._values


def test_only_accepted_resolved_config_snapshots_register_secrets(config_path, monkeypatch):
    from autogenesis_appium_mcp.utils import redaction
    runtime = server.Runtime("ios", config_path)
    accepted = runtime.config.get_config()
    before = redaction._values.copy()
    missing = "$" + "{APPIUM_MISSING_SECRET}"
    monkeypatch.delenv("APPIUM_MISSING_SECRET", raising=False)
    try:
        for invalid in (
            {"invalid": {"server_url": "http://localhost", "token": "a"}},
            {"ios": {"server_url": "http://localhost", "token": "a", "password": missing}},
            {"ios": {"token": "a"}},
            {"android": {"server_url": "http://localhost", "token": "a"}},
        ):
            config_path.write_text(json.dumps({"APPIUM_DRIVER_CONFIGS": invalid}))
            assert runtime.config.reload_config() is False
            assert redaction._values == before
            assert runtime.config.get_config() == accepted
        monkeypatch.setenv("APPIUM_ACCEPTED_SECRET", "a")
        reference = "$" + "{APPIUM_ACCEPTED_SECRET}"
        accepted["ios"]["accessKey"] = reference
        config_path.write_text(json.dumps({"APPIUM_DRIVER_CONFIGS": accepted}))
        assert runtime.config.reload_config() is True
        assert "a" in redaction._values
        assert reference not in redaction._values
        assert redaction.redact({"status": "success", "data": "application", "echo": "a"}) == {
            "status": "success", "data": "application", "echo": "[REDACTED]",
        }
    finally:
        runtime.close()


@pytest.mark.parametrize("encoded,decoded", [
    ("p&amp;ss", "p&ss"), ("p&#38;ss", "p&ss"), ("p&#x26;ss", "p&ss"), ("&#97;", "a"),
])
@pytest.mark.parametrize("summary_only,write_file", [(False, False), (True, False), (False, True), (True, True)])
def test_xml_entities_and_short_labels_are_private_in_every_sink(tmp_path, encoded, decoded, summary_only, write_file):
    import xml.etree.ElementTree as ET
    from autogenesis_appium_mcp.utils.response_format import handle_page_source, init_tool_response
    source = ('<hierarchy><node password="true" text="' + encoded + '" value="' + encoded + '">' + encoded +
              '</node><node text="status data application"/></hierarchy>')
    destination = tmp_path / "page-source.xml"
    response = init_tool_response()
    handle_page_source(response, source, str(destination) if write_file else "", summary_only)
    if summary_only:
        summary = response["data"]["page_source_summary"]
        assert '"[REDACTED]"' in summary
        assert '"' + decoded + '"' not in summary
        assert "status data application" in summary
    outputs = []
    if not summary_only:
        outputs.append(response["data"]["page_source"])
    if write_file:
        outputs.append(destination.read_text())
    for output in outputs:
        tree = ET.fromstring(output)
        assert tree[0].get("text") == tree[0].get("value") == tree[0].text == "[REDACTED]"
        assert tree[1].get("text") == "status data application"
    assert encoded not in json.dumps(response)


@pytest.mark.parametrize("summary_only", [False, True])
def test_malformed_page_source_fails_closed_before_all_sinks(tmp_path, summary_only):
    from autogenesis_appium_mcp.utils import element_util, response_format
    raw = '<hierarchy><node password="true" text="' + PRIVATE + '"'
    destination = tmp_path / "unparseable.xml"
    response = response_format.init_tool_response()
    response_format.handle_page_source(response, raw, str(destination), summary_only)
    assert PRIVATE not in destination.read_text() + json.dumps(response)
    assert PRIVATE not in element_util.simplify_page_source(raw)
    assert PRIVATE not in element_util.summarize_page_source(raw)


@pytest.mark.anyio
async def test_direct_platform_tool_sanitizes_large_source_before_losing_secure_attributes(config_path, monkeypatch):
    from autogenesis_appium_mcp.utils import element_util, redaction
    # Disable cross-call retention: this regression must prove structural protection.
    monkeypatch.setattr(redaction, "_MAX_VALUE_BYTES", 1)
    node = '<node password="true" text="' + PRIVATE + '" extra="' + "x" * 400 + '"/>'
    raw = '<hierarchy>' + node * 200 + '<node text="ordinary"/></hierarchy>'
    assert len(raw) > 60000
    seen = []
    original_strip = element_util._strip_attributes

    def strip(element):
        seen.append(True)
        assert PRIVATE not in element_util.ET.tostring(element, encoding="unicode")
        return original_strip(element)

    monkeypatch.setattr(element_util, "_strip_attributes", strip)
    runtime = server.Runtime("android", config_path)
    driver = Mock(page_source=raw)
    runtime.driver._driver = driver
    try:
        response = await runtime.server.call_tool("press_key", {"caller": "test", "text": "66"})
        content = response[0] if isinstance(response, tuple) else response
        result = json.loads(content[0].text)
        assert result["status"] == "success"
        assert PRIVATE not in json.dumps(result)
        assert "ordinary" in result["data"]["page_source"]
        assert seen
        driver.press_keycode.assert_called_once_with(66)
    finally:
        runtime.close()
