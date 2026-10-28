import json

import pytest

from autogenesis_agent_contract import SecretRef, serialize
from autogenesis_windows_mcp.config import ConfigurationError, load_app_config


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
def test_ordinary_custom_profile_fields_remain_literals(tmp_path, app_config, field, value):
    profile = {**app_config, field: value}
    assert load_app_config(None, write_config(tmp_path, {"app": profile})) == profile


@pytest.mark.parametrize("field", ["accessKey", "clientSecret", "userName", "api_key", "auth_token"])
def test_credential_profile_keys_require_and_retain_refs(tmp_path, app_config, field):
    profile = {**app_config, field: "${AUTOGENESIS_CONFIG_TEST_VALUE}"}
    loaded = load_app_config(None, write_config(tmp_path, {"app": profile}))
    assert isinstance(loaded[field], SecretRef)
    assert serialize(loaded[field]) == {"$secret": "env:AUTOGENESIS_CONFIG_TEST_VALUE"}

    profile[field] = "plaintext"
    with pytest.raises(ConfigurationError, match="AUTOGENESIS_SECRET_REFERENCE_REQUIRED"):
        load_app_config(None, write_config(tmp_path, {"app": profile}))


def test_selected_profile_preserves_recursive_environment_refs(tmp_path, app_config):
    selected = {
        **app_config,
        "exe": "$AUTOGENESIS_TEST_ROOT",
        "launch_args": ["${AUTOGENESIS_TEST_ARG}", "%AUTOGENESIS_TEST_OTHER%"],
        "custom": {"path": "$AUTOGENESIS_TEST_CUSTOM"},
    }
    path = write_config(tmp_path, {
        "selected": selected,
        "unused": {**app_config, "exe": "$AUTOGENESIS_TEST_UNSET"},
    })
    loaded = serialize(load_app_config("selected", path))
    assert loaded["exe"] == {"$secret": "env:AUTOGENESIS_TEST_ROOT"}
    assert loaded["launch_args"] == [
        {"$secret": "env:AUTOGENESIS_TEST_ARG"},
        {"$secret": "env:AUTOGENESIS_TEST_OTHER"},
    ]
    assert loaded["custom"] == {"path": {"$secret": "env:AUTOGENESIS_TEST_CUSTOM"}}
    # Unselected profiles are validated structurally but never resolved.
    assert serialize(load_app_config("unused", path))["exe"] == {"$secret": "env:AUTOGENESIS_TEST_UNSET"}


@pytest.mark.parametrize("profile", [
    None, [], {}, {"exe": "x"}, {"exe": "x", "window_title_re": ""},
    {"exe": "x", "window_title_re": ".*", "launch_args": "--bad"},
    {"exe": "x", "window_title_re": ".*", "launch_args": [42]},
    {"exe": "x", "window_title_re": ".*", "app_name": 4},
])
def test_invalid_profile_schema_fails_before_driver_startup(tmp_path, profile):
    with pytest.raises(ConfigurationError, match="AUTOGENESIS_CONFIG_INVALID"):
        load_app_config(None, write_config(tmp_path, {"app": profile}))


def test_invalid_regex_fails_before_startup(tmp_path, app_config):
    with pytest.raises(ConfigurationError, match="valid regular expression"):
        load_app_config(None, write_config(tmp_path, {"app": {**app_config, "window_title_re": "["}}))


def test_missing_malformed_and_secret_bearing_config_errors_are_sanitized(tmp_path):
    canary = "SYNTHETIC_CONFIG_CANARY"
    path = tmp_path / (canary + ".json")
    for content in (None, "{" + canary, json.dumps({canary: canary}),
                    json.dumps({"PYWINAUTO_CONFIG": {"apps_config": {canary: {"exe": canary}}}})):
        if content is not None:
            path.write_text(content, encoding="utf-8")
        with pytest.raises(ConfigurationError) as caught:
            load_app_config(canary, path)
        assert canary not in str(caught.value)
