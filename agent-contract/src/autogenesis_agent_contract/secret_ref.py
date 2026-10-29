"""Lossless secret references shared by AutoGenesis runtimes.

Plaintext exists only inside an active tool execution. Persistent state contains
ordinary literals, :class:`SecretRef`, or :class:`UnboundSecret` values.
"""

from __future__ import annotations

import inspect
import json
import os
import re
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Iterator, Mapping, TypeAlias
from pydantic import BaseModel, ConfigDict, Field, RootModel, field_validator
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


SECRET_REFERENCE_REQUIRED = "AUTOGENESIS_SECRET_REFERENCE_REQUIRED"
SECRET_BINDING_REQUIRED = "AUTOGENESIS_SECRET_BINDING_REQUIRED"
SECRET_REFERENCE_INVALID = "AUTOGENESIS_SECRET_REFERENCE_INVALID"
SECRET_RESOLUTION_FAILED = "AUTOGENESIS_SECRET_RESOLUTION_FAILED"
_SAFE_SECRET_ERROR = re.compile(
    r"(AUTOGENESIS_(?:"
    r"SECRET_(?:REFERENCE_REQUIRED|BINDING_REQUIRED|REFERENCE_INVALID|RESOLUTION_FAILED)(?:: [A-Za-z0-9_.:-]+)?"
    r"|GENERATION_(?:PREVIEW_REQUIRED|APPROVAL_REQUIRED|PREVIEW_MISMATCH|PREVIEW_STALE|DESTINATION_INVALID|WRITE_FAILED)"
    r"))"
)
REDACTED = "[REDACTED]"

_ENV_REFERENCE = re.compile(r"^env:([A-Za-z_][A-Za-z0-9_]*)$")
_UNBOUND_REFERENCE = re.compile(r"^unbound:([A-Za-z0-9_.:-]+)$")
_ENV_PLACEHOLDERS = (
    re.compile(r"^\$\{([A-Za-z_][A-Za-z0-9_]*)\}$"),
    re.compile(r"^\$([A-Za-z_][A-Za-z0-9_]*)$"),
    re.compile(r"^%([A-Za-z_][A-Za-z0-9_]*)%$"),
)
_URL_PATTERN = re.compile(r"(?i)[a-z][a-z0-9+.-]*://[^\s\"'<>]+")
_CREDENTIAL_NAMES = {
    "apikey", "accesskey", "secretkey", "privatekey", "password", "passwd",
    "pwd", "secret", "clientsecret", "credential", "credentials", "token",
    "accesstoken", "refreshtoken", "idtoken", "authtoken", "authorization",
    "proxyauthorization", "cookie", "setcookie", "username",
}
_CONTROL_SUFFIXES = re.compile(r"(?:_?(?:INPUT|TEXT|BOX|FIELD|EDIT|CONTROL|ENTRY))+(?:_?[0-9]+)?$")


class SecretReferenceError(ValueError):
    """Stable, payload-free error for reference and binding failures."""

    def __init__(self, code: str, binding: str | None = None):
        self.code = code
        self.binding = binding
        message = code if binding is None else f"{code}: {binding}"
        super().__init__(message)


class SecretRef(BaseModel):
    """A serializable reference whose plaintext is resolved only for execution."""

    model_config = ConfigDict(frozen=True, extra="forbid", populate_by_name=True)

    reference: str = Field(alias="$secret", pattern=r"^env:[A-Za-z_][A-Za-z0-9_]*$")

    @field_validator("reference")
    @classmethod
    def validate_reference(cls, value: str) -> str:
        if not isinstance(value, str) or _ENV_REFERENCE.fullmatch(value) is None:
            raise ValueError("SecretRef must use env:NAME")
        return value

    @property
    def environment_name(self) -> str:
        match = _ENV_REFERENCE.fullmatch(self.reference)
        assert match is not None
        return match.group(1)

    def to_data(self) -> dict[str, str]:
        return self.model_dump(by_alias=True)


class UnboundSecret(BaseModel):
    """A recording-time binding requirement; never accepted for execution."""

    model_config = ConfigDict(frozen=True, extra="forbid", populate_by_name=True)

    reference: str = Field(alias="$secret", pattern=r"^unbound:[A-Za-z0-9_.:-]+$")

    @field_validator("reference")
    @classmethod
    def validate_reference(cls, value: str) -> str:
        if not isinstance(value, str) or _UNBOUND_REFERENCE.fullmatch(value) is None:
            raise ValueError("UnboundSecret must use unbound:IDENTIFIER")
        return value

    @property
    def binding_id(self) -> str:
        match = _UNBOUND_REFERENCE.fullmatch(self.reference)
        assert match is not None
        return match.group(1)

    def to_data(self) -> dict[str, str]:
        return self.model_dump(by_alias=True)

class SecretBindings(RootModel[dict[str, SecretRef]]):
    """Preview-time bindings; references are data and are not resolved here."""

    model_config = ConfigDict(frozen=True)


SecretInput: TypeAlias = str | SecretRef
SecretBinding: TypeAlias = SecretRef | UnboundSecret


def credential_key(key: object) -> bool:
    name = str(key).rsplit(":", 1)[-1]
    normalized = re.sub(r"[^a-z0-9]", "", name.lower())
    return normalized in _CREDENTIAL_NAMES


def _normalized_name(name: object) -> str:
    value = str(name)
    value = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", value)
    value = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", value)
    return re.sub(r"[^A-Za-z0-9]+", "_", value).strip("_").upper()


def sensitive_control(*identifiers: object) -> bool:
    for identifier in identifiers:
        normalized = _normalized_name(identifier)
        stem = _CONTROL_SUFFIXES.sub("", normalized)
        if credential_key(normalized) or credential_key(stem) or re.search(r"PASSWORD|PASSWD", normalized):
            return True
    return False


def environment_reference(value: object) -> SecretRef | None:
    if isinstance(value, SecretRef):
        return value
    if isinstance(value, Mapping) and set(value) == {"$secret"}:
        reference = value.get("$secret")
        if isinstance(reference, str) and _ENV_REFERENCE.fullmatch(reference):
            return SecretRef.model_validate(value)
        return None
    if isinstance(value, str):
        for pattern in _ENV_PLACEHOLDERS:
            match = pattern.fullmatch(value)
            if match:
                return SecretRef(**{"$secret": f"env:{match.group(1)}"})
    return None


def secret_binding(value: object) -> SecretBinding | None:
    if isinstance(value, (SecretRef, UnboundSecret)):
        return value
    if isinstance(value, Mapping) and set(value) == {"$secret"}:
        reference = value.get("$secret")
        try:
            if isinstance(reference, str) and _ENV_REFERENCE.fullmatch(reference):
                return SecretRef.model_validate(value)
            if isinstance(reference, str) and _UNBOUND_REFERENCE.fullmatch(reference):
                return UnboundSecret.model_validate(value)
        except ValueError as error:
            raise SecretReferenceError(SECRET_REFERENCE_INVALID) from error
        raise SecretReferenceError(SECRET_REFERENCE_INVALID)
    return None


def _url_has_credentials(value: str) -> bool:
    try:
        parsed = urlsplit(value)
    except ValueError:
        return True
    query = parse_qsl(parsed.query, keep_blank_values=True)
    fragment = parse_qsl(parsed.fragment, keep_blank_values=True)
    return parsed.username is not None or parsed.password is not None or any(
        credential_key(name) for name, _ in (*query, *fragment)
    )


def _contains_credential_url(value: str) -> bool:
    return any(_url_has_credentials(match.group(0).rstrip(")}],")) for match in _URL_PATTERN.finditer(value))

def contains_credential_url(value: str) -> bool:
    return _contains_credential_url(value)


def _path_name(path: tuple[object, ...]) -> str:
    return ".".join(str(item) for item in path) or "value"


def protect_config(value: Any, path: tuple[object, ...] = ()) -> Any:
    """Convert env placeholders to refs and reject persisted plaintext credentials."""
    binding = secret_binding(value)
    if binding is not None:
        if isinstance(binding, UnboundSecret):
            raise SecretReferenceError(SECRET_REFERENCE_REQUIRED, _path_name(path))
        return binding
    reference = environment_reference(value)
    if reference is not None:
        return reference
    if isinstance(value, str) and _contains_credential_url(value):
        raise SecretReferenceError(SECRET_REFERENCE_REQUIRED, _path_name(path))
    if isinstance(value, dict):
        protected = {}
        for key, child in value.items():
            child_path = (*path, key)
            converted = protect_config(child, child_path)
            if credential_key(key) and not isinstance(child, bool) and not isinstance(converted, SecretRef):
                raise SecretReferenceError(SECRET_REFERENCE_REQUIRED, _path_name(child_path))
            protected[key] = converted
        return protected
    if isinstance(value, list):
        return [protect_config(child, (*path, index)) for index, child in enumerate(value)]
    if isinstance(value, tuple):
        return tuple(protect_config(child, (*path, index)) for index, child in enumerate(value))
    return value


def serialize(value: Any) -> Any:
    if isinstance(value, (SecretRef, UnboundSecret)):
        return value.to_data()
    if isinstance(value, BaseModel):
        return serialize(value.model_dump(by_alias=True))
    if isinstance(value, dict):
        return {key: serialize(child) for key, child in value.items()}
    if isinstance(value, list):
        return [serialize(child) for child in value]
    if isinstance(value, tuple):
        return tuple(serialize(child) for child in value)
    return value


@dataclass
class _ExecutionScope:
    tool_name: str
    original_arguments: dict[str, Any]
    plaintext: set[str] = field(default_factory=set)
    discovered: set[str] = field(default_factory=set)
    discovered_parameters: set[str] = field(default_factory=set)


_execution_scope: ContextVar[_ExecutionScope | None] = ContextVar("autogenesis_secret_execution", default=None)


def _resolve(value: Any, environment: Mapping[str, str], plaintext: set[str]) -> Any:
    binding = secret_binding(value)
    if isinstance(binding, UnboundSecret):
        raise SecretReferenceError(SECRET_BINDING_REQUIRED, binding.binding_id)
    if isinstance(binding, SecretRef):
        resolved = environment.get(binding.environment_name)
        if not resolved:
            raise SecretReferenceError(SECRET_RESOLUTION_FAILED, binding.reference)
        plaintext.add(resolved)
        return resolved
    if isinstance(value, dict):
        return {key: _resolve(child, environment, plaintext) for key, child in value.items()}
    if isinstance(value, list):
        return [_resolve(child, environment, plaintext) for child in value]
    if isinstance(value, tuple):
        return tuple(_resolve(child, environment, plaintext) for child in value)
    return value


def resolve(value: Any, environment: Mapping[str, str] | None = None) -> Any:
    scope = _execution_scope.get()
    if scope is None:
        raise SecretReferenceError(SECRET_RESOLUTION_FAILED, "execution_scope")
    plaintext: set[str] = set()
    result = _resolve(value, os.environ if environment is None else environment, plaintext)
    scope.plaintext.update(plaintext)
    return result


@contextmanager
def tool_execution(func, args: tuple[Any, ...], kwargs: dict[str, Any]) -> Iterator[tuple[tuple[Any, ...], dict[str, Any]]]:
    """Resolve refs for one tool call while retaining only safe originals."""
    signature = inspect.signature(func)
    bound = signature.bind_partial(*args, **kwargs)
    scope = _ExecutionScope(func.__name__, dict(bound.arguments))
    token = _execution_scope.set(scope)
    try:
        for name, value in tuple(bound.arguments.items()):
            bound.arguments[name] = _resolve(value, os.environ, scope.plaintext)
        yield bound.args, bound.kwargs
    finally:
        _execution_scope.reset(token)


def mark_secret(value: object, parameter: str | None = None) -> None:
    """Mark structurally discovered plaintext inside the active call only."""
    scope = _execution_scope.get()
    if scope is not None and isinstance(value, str) and value:
        scope.discovered.add(value)
        if parameter:
            scope.discovered_parameters.add(parameter)


def execution_plaintext() -> frozenset[str]:
    scope = _execution_scope.get()
    return frozenset() if scope is None else frozenset(scope.plaintext | scope.discovered)


def input_reference(parameter: str) -> SecretRef | None:
    scope = _execution_scope.get()
    if scope is None:
        return None
    binding = secret_binding(scope.original_arguments.get(parameter))
    return binding if isinstance(binding, SecretRef) else None


def require_sensitive_target(parameter: str, *identifiers: object) -> None:
    if input_reference(parameter) is not None and not sensitive_control(*identifiers):
        raise SecretReferenceError(SECRET_REFERENCE_INVALID, parameter)


def _record(value: Any, path: tuple[object, ...], discovered: set[str]) -> Any:
    binding = secret_binding(value)
    if binding is not None:
        return binding
    if isinstance(value, str) and value in discovered:
        return UnboundSecret(**{"$secret": f"unbound:{_path_name(path)}"})
    if isinstance(value, dict):
        return {key: _record(child, (*path, key), discovered) for key, child in value.items()}
    if isinstance(value, list):
        return [_record(child, (*path, index), discovered) for index, child in enumerate(value)]
    if isinstance(value, tuple):
        return tuple(_record(child, (*path, index), discovered) for index, child in enumerate(value))
    return value


def record_arguments(func, args: tuple[Any, ...], kwargs: dict[str, Any]) -> dict[str, Any]:
    scope = _execution_scope.get()
    if scope is not None and scope.tool_name == func.__name__:
        original = scope.original_arguments
    else:
        original = dict(inspect.signature(func).bind_partial(*args, **kwargs).arguments)
    return {
        name: _record(
            value,
            (func.__name__, name),
            scope.discovered if scope is not None and name in scope.discovered_parameters else set(),
        )
        for name, value in original.items()
    }


def mark_control_argument_secret(arguments: Mapping[str, Any], parameter: str) -> None:
    if sensitive_control(*(arguments.get(key, "") for key in ("title", "name", "automation_id", "control_type"))):
        value = arguments.get(parameter)
        if isinstance(value, str):
            mark_secret(value, parameter)


def unresolved_bindings(value: Any) -> tuple[str, ...]:
    found: set[str] = set()

    def visit(child: Any) -> None:
        binding = secret_binding(child)
        if isinstance(binding, UnboundSecret):
            found.add(binding.binding_id)
            return
        if isinstance(child, dict):
            for item in child.values():
                visit(item)
        elif isinstance(child, (list, tuple)):
            for item in child:
                visit(item)

    visit(value)
    return tuple(sorted(found))


def normalize_bindings(bindings: Mapping[str, Any] | SecretBindings | None) -> dict[str, SecretRef]:
    normalized: dict[str, SecretRef] = {}
    source = bindings.root if isinstance(bindings, SecretBindings) else bindings or {}
    for binding_id, value in source.items():
        reference = secret_binding(value)
        if not isinstance(reference, SecretRef):
            raise SecretReferenceError(SECRET_REFERENCE_INVALID, str(binding_id))
        normalized[str(binding_id)] = reference
    return normalized


def apply_bindings(value: Any, bindings: Mapping[str, Any] | SecretBindings | None) -> Any:
    normalized = normalize_bindings(bindings)
    required = set(unresolved_bindings(value))
    reauthor = sorted(binding for binding in required if binding.startswith("reauthor."))
    if reauthor:
        raise SecretReferenceError(SECRET_REFERENCE_REQUIRED, reauthor[0])
    missing = required - set(normalized)
    extra = set(normalized) - required
    if missing:
        raise SecretReferenceError(SECRET_BINDING_REQUIRED, sorted(missing)[0])
    if extra:
        raise SecretReferenceError(SECRET_REFERENCE_INVALID, sorted(extra)[0])

    def replace(child: Any) -> Any:
        binding = secret_binding(child)
        if isinstance(binding, UnboundSecret):
            return normalized[binding.binding_id]
        if isinstance(child, dict):
            return {key: replace(item) for key, item in child.items()}
        if isinstance(child, list):
            return [replace(item) for item in child]
        if isinstance(child, tuple):
            return tuple(replace(item) for item in child)
        return child

    return replace(value)


def public_view(value: Any, path: tuple[object, ...] = ()) -> Any:
    binding = secret_binding(value)
    if binding is not None:
        return binding.to_data()
    if isinstance(value, dict):
        result = {}
        for key, child in value.items():
            child_path = (*path, key)
            if credential_key(key) and not isinstance(child, bool):
                child_binding = secret_binding(child)
                result[key] = child_binding.to_data() if child_binding is not None else {
                    "$secret": f"unbound:{_path_name(child_path)}"
                }
            else:
                result[key] = public_view(child, child_path)
        return result
    if isinstance(value, list):
        return [public_view(child, (*path, index)) for index, child in enumerate(value)]
    if isinstance(value, tuple):
        return [public_view(child, (*path, index)) for index, child in enumerate(value)]
    if isinstance(value, str) and "://" in value:
        return _safe_urls(value, set())
    return value


def _safe_url(value: str, secrets: set[str]) -> str:
    try:
        parsed = urlsplit(value)
    except ValueError:
        return REDACTED
    hostname = parsed.hostname or ""
    port = f":{parsed.port}" if parsed.port is not None else ""
    userinfo = ""
    if parsed.username is not None:
        userinfo = REDACTED
        if parsed.password is not None:
            userinfo += ":" + REDACTED
        userinfo += "@"
    query = urlencode([
        (name, REDACTED if item in secrets or credential_key(name) else item)
        for name, item in parse_qsl(parsed.query, keep_blank_values=True)
    ])
    fragment_items = parse_qsl(parsed.fragment, keep_blank_values=True)
    fragment = urlencode([
        (name, REDACTED if item in secrets or credential_key(name) else item)
        for name, item in fragment_items
    ]) if fragment_items else parsed.fragment
    return urlunsplit((parsed.scheme, userinfo + hostname + port, parsed.path, query, fragment))


def _safe_urls(value: str, secrets: set[str]) -> str:
    return _URL_PATTERN.sub(lambda match: _safe_url(match.group(0), secrets), value)


def sanitize_result(value: Any) -> Any:
    """Defensive, call-local masking for observation output only."""
    scope = _execution_scope.get()
    secrets = set() if scope is None else scope.plaintext | scope.discovered

    def sanitize(child: Any) -> Any:
        if isinstance(child, dict):
            return {
                key: (
                    item if key == "status" and isinstance(item, str) and item in {"success", "error", "failed"}
                    else REDACTED if credential_key(key) and not isinstance(item, bool)
                    else "Operation failed" if key == "error" and item
                    else sanitize(item)
                )
                for key, item in child.items()
            }
        if isinstance(child, list):
            return [sanitize(item) for item in child]
        if isinstance(child, tuple):
            return tuple(sanitize(item) for item in child)
        if isinstance(child, str):
            try:
                decoded = json.loads(child)
            except (TypeError, ValueError):
                if child in secrets:
                    return REDACTED
                return _safe_urls(child, secrets)
            if isinstance(decoded, (dict, list)):
                sanitized = sanitize(decoded)
                return child if sanitized == decoded else json.dumps(sanitized, ensure_ascii=False)
            return REDACTED if child in secrets else child
        return child

    return sanitize(value)


def safe_secret_error(error: object) -> str | None:
    """Project only allowlisted, payload-free repair information."""
    match = _SAFE_SECRET_ERROR.search(str(error))
    return match.group(1) if match else None
