"""Validated multi-application configuration, with secret-safe diagnostics."""

import json
import os
import re
from importlib.resources import files
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from .security import remember_config_secrets


class ConfigurationError(ValueError):
    """Only fixed diagnostic strings may cross this boundary."""


def expand_env_vars(obj: Any) -> Any:
    """Expand existing $NAME, dollar-braced NAME, and Windows %NAME% references."""
    if isinstance(obj, dict):
        return {key: expand_env_vars(value) for key, value in obj.items()}
    if isinstance(obj, list):
        return [expand_env_vars(value) for value in obj]
    if isinstance(obj, str):
        expanded = os.path.expandvars(obj)
        return re.sub(r"%([A-Za-z_][A-Za-z0-9_]*)%", lambda m: os.environ.get(m[1], m[0]), expanded)
    return obj


def _has_unresolved_env(obj: Any) -> bool:
    if isinstance(obj, dict):
        return any(_has_unresolved_env(value) for value in obj.values())
    if isinstance(obj, list):
        return any(_has_unresolved_env(value) for value in obj)
    return isinstance(obj, str) and bool(re.search(
        r"\$[A-Za-z_][A-Za-z0-9_]*|\$\{[^}]+\}|%[A-Za-z_][A-Za-z0-9_]*%", obj
    ))


def load_app_config(app_name: str | None, file_path: str | Path | None = None) -> dict:
    """Use the named profile, or the first profile in JSON insertion order.

    Validate every profile before startup; expand only the selected profile so
    unused profiles may reference environment variables that are not set.
    Extra project/profile keys remain supported for existing configurations.
    """
    assets = files("autogenesis_windows_mcp").joinpath("conf")
    try:
        raw = Path(file_path).read_text(encoding="utf-8-sig") if file_path is not None else assets.joinpath("pywinauto_conf.json").read_text(encoding="utf-8")
        config = json.loads(raw)
    except (OSError, UnicodeError, ValueError):
        raise ConfigurationError("AUTOGENESIS_CONFIG_INVALID: configuration must be a readable UTF-8 JSON file.") from None

    schema = json.loads(assets.joinpath("config.schema.json").read_text(encoding="utf-8"))
    if not Draft202012Validator(schema).is_valid(config):
        raise ConfigurationError(
            "AUTOGENESIS_CONFIG_INVALID: PYWINAUTO_CONFIG.apps_config must contain profiles with nonempty exe and window_title_re strings; launch_args must be a string array and app_name a string."
        ) from None
    profiles = config["PYWINAUTO_CONFIG"]["apps_config"]
    selected = next(iter(profiles)) if not app_name else app_name
    if selected not in profiles:
        raise ConfigurationError("AUTOGENESIS_CONFIG_INVALID: --app does not select a configured profile.") from None
    expanded = expand_env_vars(profiles[selected])
    if _has_unresolved_env(expanded):
        raise ConfigurationError("AUTOGENESIS_CONFIG_INVALID: the selected profile references an unset environment variable.") from None
    if not Draft202012Validator(schema["$defs"]["profile"]).is_valid(expanded):
        raise ConfigurationError("AUTOGENESIS_CONFIG_INVALID: expanded profile contains an empty required value.") from None
    try:
        re.compile(expanded["window_title_re"])
    except re.error:
        raise ConfigurationError("AUTOGENESIS_CONFIG_INVALID: window_title_re must be a valid regular expression.") from None
    remember_config_secrets(expanded)
    return expanded
