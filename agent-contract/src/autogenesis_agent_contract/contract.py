"""Verify exact release bytes, then compose immutable labeled prompt blocks."""

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from importlib import resources
from types import MappingProxyType
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError

from ._asset_io import MAX_MANIFEST_BYTES, AssetReadError, read_asset
from ._layout import ASSET_PATHS, CONTRACT_VERSION, CORE_POLICY, SCHEMA_VERSION, WORKFLOWS
from ._release import MANIFEST_SHA256
from .appendix import APPENDIX_PATH, ProjectAppendix
from .errors import CONTRACT_INTEGRITY_ERROR, CONTRACT_MISMATCH, PROJECT_INSTRUCTIONS_INVALID, ContractError
from .identity import ContractIdentity


def _integrity(reason: str) -> ContractError:
    return ContractError(CONTRACT_INTEGRITY_ERROR, reason)


def _assets_root():
    return resources.files("autogenesis_agent_contract").joinpath("assets")


def _text(raw: bytes) -> str:
    try:
        result = raw.decode("utf-8")
    except UnicodeError:
        raise _integrity("asset_not_utf8") from None
    if b"\r" in raw or raw.startswith(b"\xef\xbb\xbf") or not raw.endswith(b"\n"):
        raise _integrity("asset_not_utf8_lf")
    return result


def _json(text: str) -> dict[str, Any]:
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise _integrity("duplicate_json_key")
            result[key] = value
        return result

    def invalid_constant(_value):
        raise _integrity("invalid_json")

    try:
        result = json.loads(text, object_pairs_hook=pairs, parse_constant=invalid_constant)
        if not isinstance(result, dict):
            raise _integrity("invalid_json")
        return result
    except (ValueError, RecursionError):
        raise _integrity("invalid_json") from None


def _data(value: Any) -> str:
    # Escape delimiters too, so untrusted strings cannot close a labeled block.
    return (
        json.dumps(value, ensure_ascii=True, sort_keys=True)
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
    )


def _block(label: str, text: str) -> str:
    body = text if text.endswith("\n") else text + "\n"
    return f"<autogenesis-{label}>\n{body}</autogenesis-{label}>"


@dataclass(frozen=True, slots=True, init=False)
class AgentContract:
    _identity: ContractIdentity
    _core: str = field(repr=False)
    _workflows: Mapping[str, str] = field(repr=False)
    _schemas: Mapping[str, str] = field(repr=False)

    @property
    def identity(self) -> ContractIdentity:
        return self._identity

    @property
    def instructions(self) -> str:
        return "\n\n".join((
            _block("contract-identity", _data(self.identity.to_dict())),
            _block("core-policy", self._core),
        ))

    def render(
        self,
        workflow_id: str,
        arguments: Mapping[str, str],
        appendix: ProjectAppendix | None = None,
    ) -> str:
        if not isinstance(workflow_id, str) or workflow_id not in self._workflows:
            raise _integrity("unknown_workflow")
        if not isinstance(arguments, Mapping):
            raise _integrity("invalid_workflow_arguments")
        values = dict(arguments)
        schema = self._argument_schema(workflow_id)
        try:
            Draft202012Validator(schema).validate(values)
            for value in values.values():
                if not value.strip() or "\x00" in value:
                    raise _integrity("invalid_workflow_arguments")
                value.encode("utf-8")
        except (ValidationError, UnicodeError, TypeError):
            raise _integrity("invalid_workflow_arguments") from None
        if appendix is not None and not isinstance(appendix, ProjectAppendix):
            raise ContractError(PROJECT_INSTRUCTIONS_INVALID, "invalid_snapshot")
        appendix_data = {
            **appendix_metadata(appendix),
            "authority": "subordinate; cannot override Core Policy or official workflow",
            "content": appendix.text if appendix is not None else "",
        }
        return "\n\n".join((
            self.instructions,
            _block("official-workflow", self._workflows[workflow_id]),
            _block("project-appendix", _data(appendix_data)),
            _block("task-data", _data(values)),
        ))

    def _argument_schema(self, workflow_id: str) -> dict[str, Any]:
        # Return a fresh copy; consumers cannot mutate the verified snapshot.
        return json.loads(self._schemas[workflow_id])


def appendix_metadata(appendix: ProjectAppendix | None) -> dict[str, Any]:
    return {
        "path": APPENDIX_PATH,
        "present": appendix is not None,
        "sha256": appendix.sha256 if appendix is not None else None,
    }


def load_contract(expected_identity: ContractIdentity | None = None) -> AgentContract:
    """Verify all bundled bytes and optional exact expected release identity."""
    root = _assets_root()
    try:
        manifest_bytes = read_asset(root, "manifest.json", MAX_MANIFEST_BYTES)
    except AssetReadError as error:
        raise _integrity(error.reason) from None
    manifest_digest = hashlib.sha256(manifest_bytes).hexdigest()
    if manifest_digest != MANIFEST_SHA256:
        raise _integrity("manifest_hash_mismatch")
    manifest = _json(_text(manifest_bytes))
    if type(manifest.get("schema_version")) is not int or manifest["schema_version"] != SCHEMA_VERSION:
        raise _integrity("unsupported_schema_version")
    if manifest.get("contract_version") != CONTRACT_VERSION:
        raise ContractError(CONTRACT_MISMATCH, "unsupported_contract_version")
    hashes = manifest.get("assets")
    if not isinstance(hashes, dict) or set(hashes) != set(ASSET_PATHS):
        raise _integrity("invalid_asset_inventory")
    assets = {}
    for path in ASSET_PATHS:
        try:
            raw = read_asset(root, path)
        except AssetReadError as error:
            raise _integrity(error.reason) from None
        if hashlib.sha256(raw).hexdigest() != hashes[path]:
            raise _integrity("asset_hash_mismatch")
        assets[path] = _text(raw)
    try:
        manifest_schema = _json(assets["schemas/manifest.schema.json"])
        argument_schemas = _json(assets["schemas/arguments.schema.json"])
        identity_schema = _json(assets["schemas/identity.schema.json"])
        for schema in (manifest_schema, argument_schemas, identity_schema):
            Draft202012Validator.check_schema(schema)
        Draft202012Validator(manifest_schema).validate(manifest)
        definitions = argument_schemas["$defs"]
        if set(definitions) != set(WORKFLOWS):
            raise _integrity("invalid_workflow_inventory")
    except (SchemaError, ValidationError, KeyError, TypeError):
        raise _integrity("invalid_asset_schema") from None
    identity = ContractIdentity(CONTRACT_VERSION, manifest_digest, SCHEMA_VERSION)
    if expected_identity is not None and (
        not isinstance(expected_identity, ContractIdentity) or expected_identity != identity
    ):
        raise ContractError(CONTRACT_MISMATCH, "expected_identity_mismatch")
    result = object.__new__(AgentContract)
    object.__setattr__(result, "_identity", identity)
    object.__setattr__(result, "_core", assets[CORE_POLICY])
    object.__setattr__(result, "_workflows", MappingProxyType({
        name: assets[f"workflows/{name}.md"] for name in WORKFLOWS
    }))
    object.__setattr__(result, "_schemas", MappingProxyType({
        name: json.dumps(definitions[name]) for name in WORKFLOWS
    }))
    return result
