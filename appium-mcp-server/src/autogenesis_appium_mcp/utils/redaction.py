"""Conservative redaction at diagnostic and MCP tool boundaries."""

import json
import os
import re
import threading
from collections import OrderedDict
from contextlib import contextmanager
from contextvars import ContextVar
from urllib.parse import parse_qsl, quote, unquote, urlsplit
import xml.etree.ElementTree as ET

REDACTED = "[REDACTED]"
_CREDENTIAL_NAMES = {
    "apikey", "accesskey", "secretkey", "privatekey", "password", "passwd", "pwd",
    "secret", "clientsecret", "credential", "credentials", "token", "accesstoken", "refreshtoken", "idtoken",
    "authorization", "proxyauthorization", "cookie", "setcookie", "username",
}
_ENV_CREDENTIAL = re.compile(r"(?:^|_)(?:API_KEY|ACCESS_KEY|SECRET_KEY|PRIVATE_KEY|PASSWORD|PASSWD|SECRET|CLIENT_SECRET|TOKEN|ACCESS_TOKEN|REFRESH_TOKEN|USERNAME)$", re.I)


def credential_key(key):
    name = str(key).rsplit(":", 1)[-1]
    return re.sub(r"[^a-z0-9]", "", name.lower()) in _CREDENTIAL_NAMES
_lock = threading.RLock()
# LRU retention protects later snapshots/previews without unlimited process memory.
# Evicted/oversized secrets cannot be recognized in unrelated future free text;
# current payloads and tool arguments remain protected independently of retention.
_MAX_VALUES = 256
_MAX_VALUE_BYTES = 64 * 1024
_values = OrderedDict()
_tool_values = ContextVar("appium_tool_secrets", default=None)
_CONFIG_KEYS = {
    "APPIUM_DRIVER_CONFIGS", "ios", "android", "mac", "platformName", "automationName",
    "deviceName", "platformVersion", "server_url", "bundleId", "appPackage", "appActivity",
    "bstack:options", "userName", "accessKey", "appium:app", "appium:fullReset",
    "autoLaunch", "appium:newCommandTimeout", "appium:sessionTimeout",
    "appium:printPageSourceOnFindFailure", "orientation", "language", "locale",
    "shouldUseSingletonTestManager", "waitForQuiescence", "showServerLogs",
    "projectName", "buildName", "buildIdentifier", "appiumVersion", "idleTimeout",
    "interactiveDebugging", "browserstack.resignApp",
}



def remember(value, *, current=None):
    """Retain explicitly identified credentials, including superseded config credentials."""
    if isinstance(value, dict):
        for child in value.values():
            remember(child, current=current)
    elif isinstance(value, (tuple, list)):
        for child in value:
            remember(child, current=current)
    elif isinstance(value, str) and value:
        if current is not None:
            current.add(value)
        active = _tool_values.get()
        if active is not None:
            active.add(value)
        size = len(value.encode("utf-8", errors="surrogatepass"))
        with _lock:
            if size > _MAX_VALUE_BYTES:
                return
            _values[value] = size
            _values.move_to_end(value)
            while len(_values) > _MAX_VALUES or sum(_values.values()) > _MAX_VALUE_BYTES:
                _values.popitem(last=False)


def remember_environment():
    for key, value in os.environ.items():
        if _ENV_CREDENTIAL.search(key):
            remember(value)


def _strings(value):
    if isinstance(value, dict):
        for child in value.values():
            yield from _strings(child)
    elif isinstance(value, (tuple, list)):
        for child in value:
            yield from _strings(child)
    elif isinstance(value, str) and value:
        yield value


def configuration_secrets(value):
    """Inspect actual config/argument structure; ordinary strings are opaque."""
    if isinstance(value, dict):
        for key, child in value.items():
            if credential_key(key) and not isinstance(child, bool):
                yield from _strings(child)
            elif key == "server_url" and isinstance(child, str):
                try:
                    url = urlsplit(child)
                    for private in (url.username, url.password):
                        if private:
                            yield unquote(private)
                    for name, private in parse_qsl(url.query):
                        if credential_key(name):
                            yield private
                except ValueError:
                    pass
            yield from configuration_secrets(child)
    elif isinstance(value, list):
        for child in value:
            yield from configuration_secrets(child)


def remember_configuration(value, *, current=None):
    for secret in configuration_secrets(value):
        remember(secret, current=current)


def _output_secrets(value, *, parse_strings=True):
    # Serialized responses may be masked structurally without registering their
    # JSON-looking ordinary text as a credential for future calls.
    yield from configuration_secrets(value)
    if isinstance(value, dict):
        for child in value.values():
            yield from _output_secrets(child, parse_strings=parse_strings)
    elif isinstance(value, (tuple, list)):
        for child in value:
            yield from _output_secrets(child, parse_strings=parse_strings)
    elif isinstance(value, str) and parse_strings:
        try:
            parsed = json.loads(value)
        except (ValueError, TypeError):
            return
        if parsed != value:
            yield from _output_secrets(parsed)


def remember_tool_arguments(arguments):
    # Text, locators, steps, titles and other ordinary arguments are not credentials.
    current = set()
    remember_configuration(arguments, current=current)
    return current


@contextmanager
def tool_redaction(arguments):
    # Keep in-flight discoveries until recording/output completes, even on eviction.
    current = _tool_values.get()
    if current is None:
        current = set()
    current.update(remember_tool_arguments(arguments))
    token = _tool_values.set(current)
    try:
        yield
    finally:
        _tool_values.reset(token)


def password_control(attributes):
    flags = (attributes.get("password"), attributes.get("secure"))
    types = {str(attributes.get(key, "")).lower() for key in ("type", "class", "role", "subrole")}
    return any(value is True or value == "true" for value in flags) or bool(types & {
        "xcuielementtypesecuretextfield", "axsecuretextfield", "securetextfield",
        "android.widget.passwordedittext",
    })


def _secure_element(element):
    return password_control(element.attrib) or password_control({"type": element.tag})


def remember_password_controls(value, *, current=None, parse_strings=True):
    if isinstance(value, dict):
        if password_control(value):
            remember(value.get("text"), current=current)
            remember(value.get("value"), current=current)
        for child in value.values():
            remember_password_controls(child, current=current, parse_strings=parse_strings)
    elif isinstance(value, (list, tuple)):
        for child in value:
            remember_password_controls(child, current=current, parse_strings=parse_strings)
    elif isinstance(value, str) and parse_strings and value.lstrip().startswith("<"):
        try:
            root = ET.fromstring(value)
        except ET.ParseError:
            return
        for element in root.iter():
            if _secure_element(element):
                remember(element.attrib.get("text"), current=current)
                remember(element.attrib.get("value"), current=current)
                if element.text and element.text.strip():
                    remember(element.text, current=current)


def _secret_variants(values):
    variants = set()
    for secret in values:
        for variant in {secret, json.dumps(secret, ensure_ascii=True)[1:-1], quote(secret, safe="")}:
            if variant:
                variants.add(variant)
    # Keep credential-bearing matchers local, outside the process-global re cache.
    return sorted(variants, key=len, reverse=True)


def _replace(value, variants):
    matches = []
    for variant in variants:
        offset = 0
        while (start := value.find(variant, offset)) >= 0:
            end = start + len(variant)
            # Unicode letters/digits are not boundaries; quotes, _, /, :, =, @ are.
            if ((start == 0 or not value[start - 1].isalnum()) and
                    (end == len(value) or not value[end].isalnum())):
                matches.append((start, end))
            offset = start + 1
    if not matches:
        return value
    merged = []
    for start, end in sorted(matches):
        if merged and start < merged[-1][1]:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))
    pieces, cursor = [], 0
    # One pass over original spans avoids rewriting inserted redaction markers.
    for start, end in merged:
        pieces.extend((value[cursor:start], REDACTED))
        cursor = end
    pieces.append(value[cursor:])
    return "".join(pieces)


def redact_text(value):
    with _lock:
        values = set(_values)
    values.update(_tool_values.get() or ())
    return _replace(value, _secret_variants(values))


def _redact_xml(value, pattern):
    try:
        root = ET.fromstring(value)
    except ET.ParseError:
        # A partial tree cannot establish which content belongs to a password.
        return "<hierarchy><summary>Page source unavailable</summary></hierarchy>"
    changed = False
    for element in root.iter():
        secure = _secure_element(element)
        for key, original in list(element.attrib.items()):
            sanitized = REDACTED if secure and key in {"text", "value"} and original else _replace(original, pattern)
            if sanitized != original:
                element.set(key, sanitized)
                changed = True
        for field in ("text", "tail"):
            original = getattr(element, field)
            if original:
                sanitized = REDACTED if secure and field == "text" and original.strip() else _replace(original, pattern)
                if sanitized != original:
                    setattr(element, field, sanitized)
                    changed = True
    # Only serialize changed trees; ordinary page source retains its exact form.
    return ET.tostring(root, encoding="unicode") if changed else value


def sanitize_page_source(value):
    """Sanitize decoded XML controls before any lossy transformation or output."""
    if not value or not value.strip():
        return value
    current = set()
    remember_password_controls(value, current=current)
    current.update(_tool_values.get() or ())
    with _lock:
        current.update(_values)
    return _redact_xml(value, _secret_variants(current))


def redact(value, *, secrets=(), parse_strings=True):
    """Protect the current payload even when its secrets exceed retention bounds."""
    current = set(secrets)
    current.update(_tool_values.get() or ())
    current.update(_output_secrets(value, parse_strings=parse_strings))
    controls = value
    # Decode only the serialized response root, never ordinary nested text.
    while parse_strings and isinstance(controls, str):
        try:
            decoded = json.loads(controls)
        except (ValueError, TypeError):
            break
        if decoded == controls:
            break
        controls = decoded
    remember_password_controls(controls, current=current, parse_strings=parse_strings)
    with _lock:
        current.update(_values)
    return _redact(value, _secret_variants(current), parse_strings=parse_strings)


def _redact(value, pattern, *, parse_strings=True):
    if isinstance(value, dict):
        return {
            key: (
                child if key == "status" and isinstance(child, str) and child in {"success", "error", "failed"}
                else REDACTED if credential_key(key) and not isinstance(child, bool)
                else "Operation failed" if key == "error" and child
                else _redact(child, pattern, parse_strings=parse_strings)
            )
            for key, child in value.items()
        }
    if isinstance(value, (list, tuple)):
        return type(value)(_redact(child, pattern, parse_strings=parse_strings) for child in value)
    if isinstance(value, str):
        if not parse_strings:
            return _replace(value, pattern)
        # Preserve the legacy JSON-string response convention, including nesting.
        try:
            parsed = json.loads(value)
        except (ValueError, TypeError):
            if value.lstrip().startswith("<"):
                return _redact_xml(value, pattern)
            return _replace(value, pattern)
        if not isinstance(parsed, (dict, list, str)):
            return _replace(value, pattern)
        if parsed != value:
            sanitized = _redact(parsed, pattern)
            return value if sanitized == parsed else json.dumps(sanitized, ensure_ascii=False)
        return _replace(value, pattern)
    return value


def config_view(value):
    """Mask every string, even under an unrecognized capability key."""
    if isinstance(value, dict):
        # Capability names can themselves contain user data; only expose known names.
        return {key if key in _CONFIG_KEYS else REDACTED: config_view(child) for key, child in value.items()}
    if isinstance(value, (list, tuple)):
        return [config_view(child) for child in value]
    # Numbers and booleans may also be private under arbitrary capability names.
    return REDACTED
