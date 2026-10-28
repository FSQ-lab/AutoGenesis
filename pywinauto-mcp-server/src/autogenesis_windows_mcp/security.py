"""Secret-safe runtime boundaries. No arbitrary values in diagnostics."""

import json
import os
import re
from urllib.parse import quote

REDACTED = "[REDACTED]"
_SECRET_KEY = re.compile(
    r"(?:^|_)(?:PASSWORD|PASSWD|SECRET|TOKEN|CREDENTIALS?|API_?KEY|ACCESS_KEY|PRIVATE_KEY|AUTHORIZATION|USER_?NAME)$"
)
# Environment names identify credentials by complete names/suffixes, never by
# a bare substring such as TOKEN in TOKENIZERS_PARALLELISM.
_ENV_SECRET_KEY = re.compile(
    r"(?:^|_)(?:TOKEN|PASSWORD|PASSWD|SECRET|API_?KEY|AUTHORIZATION|CREDENTIALS?|SECRET_ACCESS_KEY|PRIVATE_KEY)$", re.I
)
_CONTROL_SUFFIXES = re.compile(r"(?:_?(?:INPUT|TEXT|BOX|FIELD|EDIT|CONTROL|ENTRY))+(?:_?[0-9]+)?$")
_secrets: set[str] = set()


def _normalized_name(name: str) -> str:
    name = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", name)
    name = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", name)
    return re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_").upper()


def _is_secret_key(name: str) -> bool:
    return bool(_SECRET_KEY.search(_normalized_name(name)))


def _is_credential_control(name: str) -> bool:
    normalized = _normalized_name(name)
    # UI identifiers may concatenate widget suffixes (passwordbox, secretInput).
    # This heuristic is intentionally separate from strict config/tool keys.
    credential = _CONTROL_SUFFIXES.sub("", normalized)
    return (
        _is_secret_key(name)
        or _is_secret_key(credential)
        or bool(re.search(r"password|passwd", name, re.I))
    )


def remember_secret(value) -> None:
    if isinstance(value, str) and value:
        _secrets.update((value, json.dumps(value, ensure_ascii=False)[1:-1], repr(value)[1:-1], quote(value, safe="")))
    elif isinstance(value, dict):
        for item in value.values():
            remember_secret(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            remember_secret(item)


def remember_config_secrets(config) -> None:
    for key, value in os.environ.items():
        if _ENV_SECRET_KEY.search(key):
            remember_secret(value)
    if isinstance(config, dict):
        for key, value in config.items():
            if _is_secret_key(key):
                remember_secret(value)
            else:
                remember_config_secrets(value)
    elif isinstance(config, list):
        for value in config:
            remember_config_secrets(value)


def remember_tool_inputs(arguments: dict) -> None:
    # Ordinary launch arguments and tool text are application data. Logs and
    # errors already omit those values; only credential provenance makes a
    # supplied value eligible for persistent response redaction.
    for key, value in arguments.items():
        if _is_secret_key(key):
            remember_secret(value)
    # Password/credential controls must remain protected in subsequent UI
    # snapshots and generation, without treating ordinary search text as a
    # permanent secret or changing its replay behavior.
    if any(_is_credential_control(str(arguments.get(key, ""))) for key in ("title", "name", "automation_id", "control_type")):
        remember_secret(arguments.get("content"))


def scrub(value):
    """Redact known secrets and sensitive mapping values before publication."""
    if isinstance(value, str):
        for secret in sorted(_secrets, key=len, reverse=True):
            value = value.replace(secret, REDACTED)
        return re.sub(r"(https?://)[^/@\s]+:[^/@\s]+@", r"\1[REDACTED]@", value)
    if isinstance(value, dict):
        return {
            key: REDACTED if _is_secret_key(str(key)) or key in {"config", "apps_config", "PYWINAUTO_CONFIG"} else scrub(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [scrub(item) for item in value]
    if isinstance(value, tuple):
        return tuple(scrub(item) for item in value)
    return value


def scrub_tool_result(value):
    """Preserve JSON response keys when a tool returns serialized JSON."""
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except ValueError:
            pass
        else:
            if isinstance(decoded, (dict, list)):
                return json.dumps(scrub(decoded), ensure_ascii=False)
    return scrub(value)


def safe_error(_error=None) -> str:
    return "Automation operation failed; sensitive details withheld."
