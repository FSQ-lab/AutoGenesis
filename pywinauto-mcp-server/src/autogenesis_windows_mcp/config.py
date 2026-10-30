"""Validated multi-application configuration, with secret-safe diagnostics."""

from autogenesis_agent_contract import SecretRef, SecretReferenceError, protect_config
import json
import re
from importlib.resources import files
from pathlib import Path


from jsonschema import Draft202012Validator




class ConfigurationError(ValueError):
    """Only fixed diagnostic strings may cross this boundary."""




def load_app_config(app_name: str | None, file_path: str | Path | None = None) -> dict:
    """Use the named profile, or the first profile in JSON insertion order.

    Validate every profile before startup; preserve environment references in
    the selected profile so unused profiles need no local secret resolution.
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
            "AUTOGENESIS_CONFIG_INVALID: PYWINAUTO_CONFIG.apps_config must contain profiles with nonempty exe and window_title_re strings; launch_args must be a string array, app_name a string, and launch_timeout_seconds an integer from 1 through 120."
        ) from None
    profiles = config["PYWINAUTO_CONFIG"]["apps_config"]
    selected = next(iter(profiles)) if not app_name else app_name
    if selected not in profiles:
        raise ConfigurationError("AUTOGENESIS_CONFIG_INVALID: --app does not select a configured profile.") from None
    try:
        protected = protect_config(profiles[selected])
    except SecretReferenceError as error:
        raise ConfigurationError(str(error)) from None
    window_title = protected["window_title_re"]
    if isinstance(window_title, str):
        try:
            re.compile(window_title)
        except re.error:
            raise ConfigurationError("AUTOGENESIS_CONFIG_INVALID: window_title_re must be a valid regular expression.") from None
    elif not isinstance(window_title, SecretRef):
        raise ConfigurationError("AUTOGENESIS_CONFIG_INVALID: window_title_re must be a string or SecretRef.")
    return protected
