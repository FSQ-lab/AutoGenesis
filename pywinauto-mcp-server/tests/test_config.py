import json

import pytest

from autogenesis_windows_mcp.config import ConfigurationError, load_app_config
from autogenesis_windows_mcp.security import scrub


def write_config(tmp_path, profiles):
    path = tmp_path / "apps.json"
    path.write_text(json.dumps({"PYWINAUTO_CONFIG": {"apps_config": profiles}}), encoding="utf-8")
    return path


def test_first_profile_and_explicit_selection_preserve_multi_app_semantics(tmp_path, app_config):
    second = {**app_config, "app_name": "second", "custom": {"unchanged": True}}
    path = write_config(tmp_path, {"first": app_config, "second": second})
    assert load_app_config(None, path) == app_config
    assert load_app_config("second", path) == second
    with pytest.raises(ConfigurationError, match="does not select"):
        load_app_config("missing", path)


@pytest.mark.parametrize("field,value", [("token_count", "status"), ("tokenizers_parallelism", "false")])
def test_custom_profile_fields_do_not_poison_response_redaction(tmp_path, app_config, field, value):
    profile = {**app_config, field: value}
    assert load_app_config(None, write_config(tmp_path, {"app": profile})) == profile
    response = {"status": "success", "data": {field: value, "echo": value}}
    assert scrub(response) == response


@pytest.mark.parametrize("field", ["accessKey", "clientSecret", "userName", "api_key", "auth_token"])
def test_credential_profile_keys_remain_protected(tmp_path, app_config, field, monkeypatch):
    import uuid
    canary = uuid.uuid4().hex
    monkeypatch.setenv("AUTOGENESIS_CONFIG_TEST_VALUE", canary)
    profile = {**app_config, field: "$AUTOGENESIS_CONFIG_TEST_VALUE"}
    load_app_config(None, write_config(tmp_path, {"app": profile}))
    result = scrub({"status": "success", "data": {field: canary, "echo": canary}})
    if canary in json.dumps(result):
        pytest.fail("Credential profile value crossed the redaction boundary.", pytrace=False)
    assert result == {"status": "success", "data": {field: "[REDACTED]", "echo": "[REDACTED]"}}


def test_selected_profile_recursive_env_expansion_and_unused_profile(tmp_path, monkeypatch, app_config):
    monkeypatch.setenv("AUTOGENESIS_TEST_ROOT", "C:/business")
    monkeypatch.delenv("AUTOGENESIS_TEST_UNSET", raising=False)
    selected = {**app_config, "exe": "$AUTOGENESIS_TEST_ROOT/app.exe", "launch_args": ["${AUTOGENESIS_TEST_ROOT}", "%AUTOGENESIS_TEST_ROOT%"], "custom": {"path": "$AUTOGENESIS_TEST_ROOT"}}
    selected["launch_args"][0] = "$" + "{AUTOGENESIS_TEST_ROOT}"
    path = write_config(tmp_path, {"selected": selected, "unused": {**app_config, "exe": "$AUTOGENESIS_TEST_UNSET"}})
    expanded = load_app_config("selected", path)
    assert expanded["exe"] == "C:/business/app.exe"
    assert expanded["launch_args"] == ["C:/business", "C:/business"]
    assert expanded["custom"] == {"path": "C:/business"}
    with pytest.raises(ConfigurationError, match="unset environment variable"):
        load_app_config("unused", path)


@pytest.mark.parametrize("profile", [None, [], {}, {"exe": "x"}, {"exe": "x", "window_title_re": ""}, {"exe": "x", "window_title_re": ".*", "launch_args": "--bad"}, {"exe": "x", "window_title_re": ".*", "launch_args": [42]}, {"exe": "x", "window_title_re": ".*", "app_name": 4}])
def test_invalid_profile_schema_fails_before_driver_startup(tmp_path, profile):
    path = write_config(tmp_path, {"app": profile})
    with pytest.raises(ConfigurationError, match="AUTOGENESIS_CONFIG_INVALID"):
        load_app_config(None, path)


def test_invalid_regex_and_empty_env_fail_before_startup(tmp_path, monkeypatch, app_config):
    path = write_config(tmp_path, {"app": {**app_config, "window_title_re": "["}})
    with pytest.raises(ConfigurationError, match="valid regular expression"):
        load_app_config(None, path)
    monkeypatch.setenv("AUTOGENESIS_TEST_EMPTY", "")
    path = write_config(tmp_path, {"app": {**app_config, "exe": "$AUTOGENESIS_TEST_EMPTY"}})
    with pytest.raises(ConfigurationError, match="empty required value"):
        load_app_config(None, path)


def test_missing_malformed_and_secret_bearing_config_errors_are_sanitized(tmp_path):
    import uuid
    canary = uuid.uuid4().hex
    path = tmp_path / (canary + ".json")
    for content in (None, "{" + canary, json.dumps({canary: canary}), json.dumps({"PYWINAUTO_CONFIG": {"apps_config": {canary: {"exe": canary}}}})):
        if content is not None:
            path.write_text(content, encoding="utf-8")
        with pytest.raises(ConfigurationError) as caught:
            load_app_config(canary, path)
        if canary in str(caught.value):
            pytest.fail("Configuration diagnostics disclosed a secret.", pytrace=False)
