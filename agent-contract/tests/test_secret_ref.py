import json

import pytest

from autogenesis_agent_contract import (
    SECRET_BINDING_REQUIRED,
    SECRET_REFERENCE_REQUIRED,
    SecretRef,
    SecretReferenceError,
    UnboundSecret,
    apply_bindings,
    mark_secret,
    protect_config,
    public_view,
    record_arguments,
    resolve,
    sanitize_result,
    serialize,
    tool_execution,
    unresolved_bindings,
)


def ref(name="LOGIN_PASSWORD"):
    return SecretRef(**{"$secret": f"env:{name}"})


def test_reference_round_trip_and_config_protection(monkeypatch):
    protected = protect_config({
        "server_url": "${APPIUM_URL}",
        "bstack:options": {"accessKey": "$BROWSERSTACK_ACCESS_KEY"},
        "deviceName": "Pixel",
    })
    assert serialize(protected) == {
        "server_url": {"$secret": "env:APPIUM_URL"},
        "bstack:options": {"accessKey": {"$secret": "env:BROWSERSTACK_ACCESS_KEY"}},
        "deviceName": "Pixel",
    }
    monkeypatch.setenv("APPIUM_URL", "https://example.invalid/wd/hub")
    monkeypatch.setenv("BROWSERSTACK_ACCESS_KEY", "private")
    with tool_execution(lambda config: config, (), {"config": protected}) as (args, kwargs):
        resolved = args[0]
    assert resolved["bstack:options"]["accessKey"] == "private"
    assert public_view(protected) == serialize(protected)


@pytest.mark.parametrize("config", [
    {"accessKey": "plaintext"},
    {"server_url": "https://user:password@example.invalid/wd/hub"},
    {"server_url": "https://example.invalid/wd/hub?token=plaintext"},
    {"proxy": "socks5://user:password@example.invalid"},
    {"endpoint": "https://example.invalid/#access_token=plaintext"},
    {"encoded": '{"proxy":"socks5://user:password@example.invalid"}'},
])
def test_persisted_plaintext_credentials_are_rejected(config):
    with pytest.raises(SecretReferenceError) as caught:
        protect_config(config)
    assert caught.value.code == SECRET_REFERENCE_REQUIRED

    with pytest.raises(SecretReferenceError) as nested:
        protect_config({"proxy": {"endpoint": "https://user:password@example.invalid"}})
    assert nested.value.code == SECRET_REFERENCE_REQUIRED
    assert "plaintext" not in str(caught.value)
    projected = public_view({"proxy": "socks5://user:password@example.invalid"})
    assert "user" not in projected["proxy"] and "password" not in projected["proxy"]


def test_tool_execution_resolves_refs_but_recording_preserves_them(monkeypatch):
    monkeypatch.setenv("LOGIN_PASSWORD", "private")

    def enter_text(content: str | SecretRef, title="Password"):
        return content

    secret = ref()
    with tool_execution(enter_text, (), {"content": secret, "title": "Password"}) as (args, kwargs):
        assert args[0] == "private"
        assert record_arguments(enter_text, args, kwargs) == {
            "content": secret,
            "title": "Password",
        }
        assert sanitize_result({"status": "success", "echo": "private", "public": "application"}) == {
            "status": "success",
            "echo": "[REDACTED]",
            "public": "application",
        }



def test_discovered_plaintext_becomes_unbound_without_retaining_value():
    def enter_text(content: str, note: str = ""):
        return content

    with tool_execution(enter_text, (), {"content": "private"}) as (args, kwargs):
        mark_secret("private", "content")
        recorded = record_arguments(enter_text, args, kwargs)
        assert recorded == {
            "content": UnboundSecret(**{"$secret": "unbound:enter_text.content"})
        }
        assert "private" not in json.dumps(serialize(recorded))

    with tool_execution(enter_text, (), {"content": "private", "note": "enter private now"}) as (args, kwargs):
        mark_secret("private", "content")
        embedded = record_arguments(enter_text, args, kwargs)
        assert embedded["note"] == "enter private now"

    assert unresolved_bindings(recorded) == ("enter_text.content",)
    with pytest.raises(SecretReferenceError) as caught:
        with tool_execution(lambda plan: plan, (), {"plan": recorded}):
            pass
    assert caught.value.code == SECRET_BINDING_REQUIRED



def test_bindings_are_exact_and_replayable(monkeypatch):
    plan = {
        "content": UnboundSecret(**{"$secret": "unbound:enter_text.content"}),
        "public": "application",
    }
    bound = apply_bindings(plan, {"enter_text.content": ref()})
    assert serialize(bound) == {
        "content": {"$secret": "env:LOGIN_PASSWORD"},
        "public": "application",
    }
    monkeypatch.setenv("LOGIN_PASSWORD", "a")
    with tool_execution(lambda config: config, (), {"config": bound}) as (args, kwargs):
        resolved = args[0]
    assert resolved == {"content": "a", "public": "application"}



def test_reference_requires_structurally_sensitive_target(monkeypatch):
    from autogenesis_agent_contract import require_sensitive_target

    monkeypatch.setenv("LOGIN_PASSWORD", "private")

    def enter_text(content: str | SecretRef):
        return content

    with tool_execution(enter_text, (), {"content": ref()}):
        require_sensitive_target("content", "Password", "passwordInput")
        with pytest.raises(SecretReferenceError) as caught:
            require_sensitive_target("content", "Search", "searchInput")
        assert caught.value.code == "AUTOGENESIS_SECRET_REFERENCE_INVALID"

def test_sanitize_result_is_structural_and_call_local(monkeypatch):
    monkeypatch.setenv("LOGIN_PASSWORD", "success")

    def tool(password: str | SecretRef):
        return password

    with tool_execution(tool, (), {"password": ref()}) as (args, kwargs):
        value = {
            "status": "success",
            "administrator": "administrator",
            "credential": "success",
            "url": "https://user:success@example.invalid/?token=success",
        }
        assert sanitize_result(value) == {
            "status": "success",
            "administrator": "administrator",
            "credential": "[REDACTED]",
            "url": "https://[REDACTED]:[REDACTED]@example.invalid/?token=%5BREDACTED%5D",
        }

    # No global remembered-secret state survives the tool call.
    assert sanitize_result({"value": "success"}) == {"value": "success"}
