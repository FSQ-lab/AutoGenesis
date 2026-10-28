import io
import json
import logging
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from mcp.server.fastmcp.exceptions import ToolError

from autogenesis_agent_contract import (
    SecretRef, SecretReferenceError, UnboundSecret, apply_bindings,
    prepare_generation_preview, serialize,
)
from autogenesis_windows_mcp.utils.element_util import extract_element_info_from_pwa
from autogenesis_windows_mcp.utils.logger import _SafeDiagnostic, log_tool_call

PRIVATE = "SYNTHETIC_WINDOWS_PRIVATE_CANARY"


@pytest.mark.anyio
async def test_tool_secret_ref_is_call_local_and_logs_are_payload_free(monkeypatch, caplog):
    monkeypatch.setenv("AUTOGENESIS_WINDOWS_PASSWORD", PRIVATE)

    @log_tool_call
    async def echo(content: str | SecretRef):
        return {"status": "success", "data": {"echo": content, "public": "application"}}

    with caplog.at_level(logging.INFO):
        result = await echo(content=SecretRef(**{"$secret": "env:AUTOGENESIS_WINDOWS_PASSWORD"}))
    assert result == {
        "status": "success",
        "data": {"echo": "[REDACTED]", "public": "application"},
    }
    assert PRIVATE not in json.dumps(result)

    @log_tool_call
    async def later(text: str):
        return {"status": "success", "data": text}

    assert await later(text=PRIVATE) == {"status": "success", "data": PRIVATE}

@pytest.mark.anyio
async def test_protocol_writer_preserves_binding_error_and_masks_arbitrary_error():
    from autogenesis_windows_mcp.cli import _ProtocolWriter

    class Stream:
        def __init__(self):
            self.values = []

        async def write(self, value):
            self.values.append(value)

    writer = object.__new__(_ProtocolWriter)
    writer.stream = Stream()
    await writer.write(json.dumps({
        "jsonrpc": "2.0", "id": 1,
        "result": {"isError": True, "content": [{"type": "text", "text":
            "AUTOGENESIS_SECRET_BINDING_REQUIRED: enter_text.content"}]},
    }))
    await writer.write(json.dumps({
        "jsonrpc": "2.0", "id": 2,
        "result": {"isError": True, "content": [{"type": "text", "text": PRIVATE}]},
    }))
    first, second = [json.loads(value) for value in writer.stream.values]
    assert first["result"]["content"][0]["text"] == "AUTOGENESIS_SECRET_BINDING_REQUIRED: enter_text.content"
    assert PRIVATE not in json.dumps(second)



@pytest.mark.anyio
async def test_server_masks_non_secretref_tool_errors_for_every_transport():
    from autogenesis_windows_mcp.server import WindowsMCP

    server = WindowsMCP("error-boundary")
    with pytest.raises(Exception) as caught:
        await server.call_tool(PRIVATE, {"text": PRIVATE})
    assert PRIVATE not in str(caught.value)
    assert "check the tool name" in str(caught.value)

def test_third_party_diagnostics_drop_payload_and_traceback():
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.addFilter(_SafeDiagnostic())
    record = logging.LogRecord("httpx", logging.ERROR, "", 1, "request %s", (PRIVATE,), None)
    handler.handle(record)
    assert PRIVATE not in stream.getvalue()
    assert "Runtime diagnostic withheld" in stream.getvalue()


class Element:
    def __init__(self, title, value, automation_id="", control_type="Edit", children=()):
        self._title = title
        self._value = value
        self._children = list(children)
        self.element_info = SimpleNamespace(
            control_type=control_type, automation_id=automation_id,
            class_name="Edit", runtime_id=(id(self),),
        )

    def rectangle(self):
        return SimpleNamespace(left=0, top=0, right=10, bottom=10)

    def window_text(self):
        return self._title

    def get_value(self):
        return self._value

    def children(self):
        return self._children


def test_password_control_snapshot_is_structural_not_global():
    root = Element("Root", "public", children=[
        Element("Password", PRIVATE, automation_id="passwordInput"),
        Element("Search", "application", automation_id="searchInput"),
    ])
    snapshot = extract_element_info_from_pwa(root, runtime_ids=[])
    password, search = snapshot["children"]
    assert password["value"] == "[REDACTED]"
    assert password["title"] == "[REDACTED]"
    assert search["value"] == "application"
    assert PRIVATE not in json.dumps(snapshot)


def test_unbound_generation_value_requires_explicit_ref(monkeypatch):
    plan = {
        "tool_name": "enter_text",
        "tool_params": {"content": UnboundSecret(**{"$secret": "unbound:enter_text.content"})},
    }
    with pytest.raises(SecretReferenceError, match="AUTOGENESIS_SECRET_BINDING_REQUIRED"):
        apply_bindings(plan, None)
    bound = apply_bindings(plan, {
        "enter_text.content": SecretRef(**{"$secret": "env:AUTOGENESIS_WINDOWS_PASSWORD"}),
    })
    assert serialize(bound)["tool_params"]["content"] == {
        "$secret": "env:AUTOGENESIS_WINDOWS_PASSWORD",
    }

@pytest.mark.windows
@pytest.mark.skipif(sys.platform != "win32", reason="Windows driver modules")
@pytest.mark.anyio
async def test_generation_confirmation_rejects_stale_base(tmp_path, app_config):
    from autogenesis_windows_mcp.app_session import AppSessionManager
    from autogenesis_windows_mcp.server import WindowsMCP
    from autogenesis_windows_mcp.tools.gen_code_tool import register_gen_code_tools

    manager = AppSessionManager(app_config)
    server = WindowsMCP("stale-generation")
    register_gen_code_tools(server, manager, tmp_path)
    destination = tmp_path / "steps.py"
    destination.write_text("base\n", encoding="utf-8")
    preview = prepare_generation_preview(tmp_path, destination, "session", "generated\n")
    manager.pending_write = preview
    manager.proposed_changes = ["generated"]
    destination.write_text("changed\n", encoding="utf-8")

    with pytest.raises(ToolError, match="AUTOGENESIS_GENERATION_PREVIEW_STALE"):
        await server.call_tool("confirm_code_changes", {
            "preview_id": preview.preview_id,
            "digest": preview.digest,
            "approved": True,
        })
    assert destination.read_text(encoding="utf-8") == "changed\n"



@pytest.mark.windows
@pytest.mark.skipif(sys.platform != "win32", reason="Windows driver modules")
@pytest.mark.anyio
async def test_real_enter_text_records_unbound_then_bound_ref(tmp_path, app_config, monkeypatch):
    from autogenesis_windows_mcp.app_session import AppSessionManager
    from autogenesis_windows_mcp.server import WindowsMCP
    from autogenesis_windows_mcp.tools.common_tool import register_common_tools
    from autogenesis_windows_mcp.tools.gen_code_tool import register_gen_code_tools

    manager = AppSessionManager(app_config)
    manager.gen_code_id = "acceptance"
    manager.steps_dir = str(tmp_path)
    manager.step_file_target = str(tmp_path / "steps.py")
    element = Mock()
    wrapper = Mock()
    element.wrapper_object.return_value = wrapper
    async def find(*args, **kwargs):
        return element, True, {}, {}
    monkeypatch.setattr("autogenesis_windows_mcp.tools.common_tool.find_element_by_kwargs", find)
    monkeypatch.setattr(manager, "get_main_window", Mock())

    server = WindowsMCP("secret-ref-generation")
    register_common_tools(server, manager)
    register_gen_code_tools(server, manager, tmp_path)
    await server.call_tool("enter_text", {
        "caller": "test", "control_framework": "pywinauto", "title": "Password",
        "content": PRIVATE, "control_type": "Edit", "automation_id": "passwordInput",
        "step": "When enter a password", "need_snapshot": 0,
    })
    cache = serialize(manager.gen_code_cache)
    assert PRIVATE not in json.dumps(cache)
    assert cache[0]["tool_params"]["content"] == {"$secret": "unbound:enter_text.content"}
    monkeypatch.setenv("AUTOGENESIS_WINDOWS_PASSWORD", PRIVATE)
    preview_result = await server.call_tool("preview_code_changes", {
        "secret_bindings": {"enter_text.content": {"$secret": "env:AUTOGENESIS_WINDOWS_PASSWORD"}},
    })
    preview_content = preview_result[0] if isinstance(preview_result, tuple) else preview_result
    if isinstance(preview_content, list):
        preview_content = preview_content[0]
    preview = json.loads(preview_content.text)["data"]
    assert PRIVATE not in json.dumps(preview) and "env:AUTOGENESIS_WINDOWS_PASSWORD" in preview["diff_preview"]
    target = manager.step_file_target
    with pytest.raises(ToolError, match="AUTOGENESIS_GENERATION_APPROVAL_REQUIRED"):
        await server.call_tool("confirm_code_changes", {})
    await server.call_tool("confirm_code_changes", {
        "preview_id": preview["preview_id"],
        "digest": preview["digest"],
        "approved": True,
    })
    assert target and open(target, encoding="utf-8").read() == preview["append_payload"]
