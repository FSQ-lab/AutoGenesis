"""Verify and expose the immutable official Appium Agent Skills snapshot."""

from __future__ import annotations

import hashlib
import json
import re
import posixpath
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Mapping

from ._asset_io import MAX_MANIFEST_BYTES, AssetReadError, read_asset
from ._layout import APPIUM_SKILLS_MANIFEST, APPIUM_SKILLS_ROOT
from .contract import AgentContract, load_contract
from .errors import CONTRACT_INTEGRITY_ERROR, ContractError

SOURCE = "https://github.com/appium/skills"
COMMIT = "e907024c210fe024c956ed9c74146fc27b1dd013"
LICENSE = "Apache-2.0"
NODE_MAJORS = (20, 22, 24)
_MAX_FILES = 512
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
SUPPORTED_WORKFLOWS = MappingProxyType({
    "appium-troubleshooting": "skills/appium-troubleshooting/SKILL.md",
    "setup-mac2": "skills/setup-mac2/SKILL.md",
    "setup-uiautomator2": "skills/setup-uiautomator2/SKILL.md",
    "setup-xcuitest": "skills/setup-xcuitest/SKILL.md",
    "xcuitest-real-device-config": "skills/xcuitest-real-device-config/SKILL.md",
})
_ASSET_REFERENCE = re.compile(r"(?<![A-Za-z0-9_.\-/])(?:contexts|tools)/[A-Za-z0-9_.\-/]+")
_IMPORT_REFERENCE = re.compile(r"(?:from\s+|import\s*\(|import\s+|require\s*\()[\"']([^\"']+)[\"']")
_EXCLUDED_TOOLS = frozenset({
    "tools/appium/setup/scripts/check-node-env.mjs",
    "tools/appium/setup/scripts/smoke-appium-server.mjs",
})




@dataclass(frozen=True, slots=True)
class AppiumWorkflow:
    workflow_id: str
    entrypoint: str
    content: bytes = field(repr=False)
    required_contexts: tuple[str, ...]
    optional_contexts: tuple[str, ...]
    tools: tuple[str, ...]
    assets: Mapping[str, str]


def _declared_contexts(text: str, key: str) -> tuple[str, ...]:
    prefix = f"  {key}: "
    rows = [line[len(prefix):] for line in text.splitlines() if line.startswith(prefix)]
    if len(rows) > 1:
        raise _integrity("invalid_appium_workflow_metadata")
    if not rows:
        return ()
    value = rows[0]
    if len(value) < 2 or value[0] != "'" or value[-1] != "'":
        raise _integrity("invalid_appium_workflow_metadata")
    try:
        paths = json.loads(value[1:-1])
    except (TypeError, ValueError):
        raise _integrity("invalid_appium_workflow_metadata") from None
    if not isinstance(paths, list) or any(not isinstance(path, str) for path in paths):
        raise _integrity("invalid_appium_workflow_metadata")
    return tuple(paths)



def _transitive_assets(bundle: "AppiumSkillsBundle", roots: tuple[str, ...]) -> tuple[str, ...]:
    selected = set(roots)
    pending = list(roots)
    while pending:
        relative = pending.pop()
        try:
            text = bundle._contents[relative].decode("utf-8")
        except (KeyError, UnicodeError):
            raise _integrity("invalid_appium_workflow_inventory") from None
        references = {
            value.rstrip("`.,;:)")
            for value in _ASSET_REFERENCE.findall(text)
        }
        if relative.endswith((".js", ".mjs")):
            parent = PurePosixPath(relative).parent
            for value in _IMPORT_REFERENCE.findall(text):
                if not value.startswith("."):
                    continue
                candidate = posixpath.normpath((parent / value).as_posix())
                candidates = (candidate, candidate + ".js", candidate + ".mjs", candidate + ".json")
                matches = tuple(path for path in candidates if path in bundle._contents)
                if len(matches) != 1:
                    raise _integrity("invalid_appium_workflow_inventory")
                references.add(matches[0])
        references.difference_update(_EXCLUDED_TOOLS)
        if any(path not in bundle._contents for path in references):
            raise _integrity("invalid_appium_workflow_inventory")
        for path in references:
            if path not in selected:
                selected.add(path)
                pending.append(path)
    return tuple(sorted(selected))

def _load_workflow(bundle: "AppiumSkillsBundle", workflow_id: str) -> AppiumWorkflow:
    if not isinstance(workflow_id, str) or workflow_id not in SUPPORTED_WORKFLOWS:
        raise _integrity("unsupported_appium_workflow")
    entrypoint = SUPPORTED_WORKFLOWS[workflow_id]
    try:
        content = bundle._contents[entrypoint]
        text = content.decode("utf-8")
    except (KeyError, UnicodeError):
        raise _integrity("invalid_appium_workflow_inventory") from None
    required = _declared_contexts(text, "renma.requires-context")
    optional = _declared_contexts(text, "renma.optional-context")
    referenced_tools = {path.rstrip("`.,;:)") for path in _ASSET_REFERENCE.findall(text) if path.startswith("tools/")}
    direct_tools = tuple(sorted(referenced_tools - _EXCLUDED_TOOLS))
    direct = (entrypoint, *required, *optional, *direct_tools)
    if len(direct) != len(set(direct)) or any(path not in bundle._contents for path in direct):
        raise _integrity("invalid_appium_workflow_inventory")
    selected = _transitive_assets(bundle, direct)
    tools = tuple(path for path in selected if path.startswith("tools/"))
    return AppiumWorkflow(
        workflow_id=workflow_id,
        entrypoint=entrypoint,
        content=content,
        required_contexts=required,
        optional_contexts=optional,
        tools=tools,
        assets=MappingProxyType({path: bundle.assets[path] for path in selected}),
    )


@dataclass(frozen=True, slots=True)
class AppiumSkillsBundle:
    source: str
    commit: str
    license: str
    node_majors: tuple[int, ...]
    assets: Mapping[str, str]
    _contents: Mapping[str, bytes] = field(repr=False)

    def read_asset(self, relative: str) -> bytes:
        """Return a held, verified snapshot asset without filesystem access."""
        if not isinstance(relative, str) or relative not in self._contents:
            raise _integrity("invalid_appium_skills_asset")
        return self._contents[relative]
    def load_workflow(self, workflow_id: str) -> AppiumWorkflow:
        """Load one supported authenticated official workflow by exact ID."""
        return _load_workflow(self, workflow_id)


def _assets_root():
    return resources.files("autogenesis_agent_contract").joinpath("assets")


def _integrity(reason: str) -> ContractError:
    return ContractError(CONTRACT_INTEGRITY_ERROR, reason)


def _manifest(raw: bytes) -> dict:
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError
            result[key] = value
        return result

    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=pairs,
            parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()),
        )
    except (UnicodeError, ValueError, RecursionError):
        raise _integrity("invalid_appium_skills_manifest") from None
    if not isinstance(value, dict):
        raise _integrity("invalid_appium_skills_manifest")
    return value


def _relative(value: object) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise _integrity("invalid_appium_skills_inventory")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or path.as_posix() != value:
        raise _integrity("invalid_appium_skills_inventory")
    return value


def load_appium_skills(contract: AgentContract | None = None) -> AppiumSkillsBundle:
    """Verify the pinned snapshot and retain its immutable asset bytes."""
    if contract is None:
        contract = load_contract()
    elif not isinstance(contract, AgentContract):
        raise _integrity("invalid_contract")
    assets_root = _assets_root()
    try:
        root_path = Path(assets_root)
        raw = contract._read_verified_asset(APPIUM_SKILLS_MANIFEST)
    except (TypeError, ContractError):
        raise _integrity("appium_skills_unreadable") from None
    manifest = _manifest(raw)
    if set(manifest) != {"schema_version", "source", "commit", "license", "assets"}:
        raise _integrity("invalid_appium_skills_manifest")
    if (
        manifest["schema_version"] != 1
        or manifest["source"] != SOURCE
        or manifest["commit"] != COMMIT
        or manifest["license"] != LICENSE
        or not isinstance(manifest["assets"], dict)
        or not 0 < len(manifest["assets"]) <= _MAX_FILES
    ):
        raise _integrity("invalid_appium_skills_manifest")
    expected: dict[str, str] = {}
    for name, digest in manifest["assets"].items():
        relative = _relative(name)
        if not isinstance(digest, str) or _DIGEST.fullmatch(digest) is None:
            raise _integrity("invalid_appium_skills_inventory")
        expected[relative] = digest
    bundle_root = root_path / APPIUM_SKILLS_ROOT
    try:
        entries = tuple(bundle_root.rglob("*"))
        actual: set[str] = set()
        if len(entries) > _MAX_FILES * 4:
            raise _integrity("invalid_appium_skills_inventory")
        for entry in entries:
            if entry.is_symlink():
                raise _integrity("unsafe_appium_skills_path")
            if entry.is_file():
                relative = entry.relative_to(bundle_root).as_posix()
                if relative != "manifest.json":
                    actual.add(relative)
            elif not entry.is_dir():
                raise _integrity("unsafe_appium_skills_path")
        if actual != set(expected):
            raise _integrity("invalid_appium_skills_inventory")
        contents: dict[str, bytes] = {}
        for relative, digest in expected.items():
            content = read_asset(bundle_root, relative)
            if hashlib.sha256(content).hexdigest() != digest:
                raise _integrity("appium_skills_hash_mismatch")
            contents[relative] = content
    except ContractError:
        raise
    except (OSError, AssetReadError, ValueError):
        raise _integrity("appium_skills_unreadable") from None
    return AppiumSkillsBundle(
        source=SOURCE,
        commit=COMMIT,
        license=LICENSE,
        node_majors=NODE_MAJORS,
        assets=MappingProxyType(expected),
        _contents=MappingProxyType(contents),
    )
