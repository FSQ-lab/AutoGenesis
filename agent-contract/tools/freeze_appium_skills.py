"""Verify the vendored Appium Skills subset against its pinned upstream checkout."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import runpy
from pathlib import Path, PurePosixPath

from _files import atomic_write

PACKAGE = "agent-contract/src/autogenesis_agent_contract"
BUNDLE_RELATIVE = "skills/autogenesis-setup/references/appium-skills"
BUNDLE_MANIFEST = f"{BUNDLE_RELATIVE}/manifest.json"
SOURCE_METADATA = f"{BUNDLE_RELATIVE}/SOURCE.json"
SOURCE = "https://github.com/appium/skills"
COMMIT = "e907024c210fe024c956ed9c74146fc27b1dd013"
UPSTREAM_GIT_TREE = "26deb451d8c019ac0dbd70de832e6ae5be877383"
COMMIT_DATE = "2026-10-22T05:39:50Z"
LICENSE = "Apache-2.0"
DIGEST_ALGORITHM = "sha256-length-prefixed-path-and-content-v1"
UPSTREAM_ROOTS = ("contexts", "skills", "tools")
LOCAL_ONLY = ("NOTICE", "SOURCE.json")
_MAX_FILES = 512


def _asset_io(repo: Path) -> dict:
    return runpy.run_path(str(repo / PACKAGE / "_asset_io.py"))


def _relative(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("invalid upstream inventory path")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or path.as_posix() != value:
        raise ValueError("invalid upstream inventory path")
    if value != "LICENSE" and (not path.parts or path.parts[0] not in UPSTREAM_ROOTS):
        raise ValueError("upstream inventory path is outside the explicit allowlist")
    return value


def _metadata(repo: Path) -> dict:
    asset_io = _asset_io(repo)
    raw = asset_io["read_asset"](
        repo / PACKAGE / "assets", SOURCE_METADATA, asset_io["MAX_MANIFEST_BYTES"]
    )

    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate provenance key")
            result[key] = value
        return result

    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs)
    except (UnicodeError, ValueError, RecursionError):
        raise ValueError("invalid Appium Skills provenance metadata") from None
    fields = {
        "schema_version", "source", "commit", "commit_date", "license",
        "upstream_git_tree", "tree_digest_algorithm", "upstream_tree_sha256",
        "upstream_inventory", "modified_upstream_files",
    }
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError("invalid Appium Skills provenance metadata")
    if (
        type(value["schema_version"]) is not int
        or value["schema_version"] != 1
        or value["source"] != SOURCE
        or value["commit"] != COMMIT
        or value["commit_date"] != COMMIT_DATE
        or value["license"] != LICENSE
        or value["upstream_git_tree"] != UPSTREAM_GIT_TREE
        or value["tree_digest_algorithm"] != DIGEST_ALGORITHM
        or value["modified_upstream_files"] is not False
        or not isinstance(value["upstream_tree_sha256"], str)
        or len(value["upstream_tree_sha256"]) != 64
        or any(
            character not in "0123456789abcdef"
            for character in value["upstream_tree_sha256"]
        )
    ):
        raise ValueError("Appium Skills provenance identity differs from the pinned upstream")
    inventory_value = value["upstream_inventory"]
    if not isinstance(inventory_value, list) or not 0 < len(inventory_value) <= _MAX_FILES:
        raise ValueError("invalid Appium Skills upstream inventory")
    inventory = tuple(_relative(item) for item in inventory_value)
    if inventory != tuple(sorted(set(inventory))):
        raise ValueError("Appium Skills upstream inventory must be unique and sorted")
    value["upstream_inventory"] = inventory
    return value


def _scan(root: Path, inventory_roots: tuple[str, ...]) -> tuple[str, ...]:
    paths: list[str] = []
    entry_count = 0
    for name in inventory_roots:
        target = root / name
        if name in {"LICENSE", *LOCAL_ONLY, "manifest.json"}:
            entries = (target,)
        else:
            if not target.is_dir() or target.is_symlink():
                raise ValueError(f"required upstream root is missing or unsafe: {name}")
            entries = target.rglob("*")
        for path in entries:
            entry_count += 1
            if entry_count > _MAX_FILES * 4:
                raise ValueError("Appium Skills tree exceeds the bounded inventory")
            if path.is_symlink() or not (path.is_file() or path.is_dir()):
                raise ValueError("Appium Skills tree contains an unsafe path")
            if path.is_file():
                paths.append(path.relative_to(root).as_posix())
    if len(paths) > _MAX_FILES:
        raise ValueError("Appium Skills tree exceeds the bounded inventory")
    return tuple(sorted(paths))


def _scan_all(root: Path) -> tuple[str, ...]:
    if not root.is_dir() or root.is_symlink():
        raise ValueError("vendored Appium Skills root is missing or unsafe")
    paths: list[str] = []
    for entry_count, path in enumerate(root.rglob("*"), start=1):
        if entry_count > _MAX_FILES * 4:
            raise ValueError("Appium Skills tree exceeds the bounded inventory")
        if path.is_symlink() or not (path.is_file() or path.is_dir()):
            raise ValueError("Appium Skills tree contains an unsafe path")
        if path.is_file():
            paths.append(path.relative_to(root).as_posix())
    return tuple(sorted(paths))


def _git(root: Path, *arguments: str) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), *arguments],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise ValueError("unable to validate upstream Git identity") from None
    if result.returncode != 0:
        raise ValueError("unable to validate upstream Git identity")
    return result.stdout.strip()


def _verify_git_identity(root: Path) -> None:
    if not (root / ".git").exists():
        return
    if _git(root, "rev-parse", "HEAD^{commit}") != COMMIT:
        raise ValueError("upstream checkout is not at the pinned commit")
    if _git(root, "rev-parse", f"{COMMIT}^{{tree}}") != UPSTREAM_GIT_TREE:
        raise ValueError("upstream commit has the wrong Git tree object")
    remote = _git(root, "remote", "get-url", "origin")
    if remote not in {
        SOURCE,
        f"{SOURCE}.git",
        "git@github.com:appium/skills",
        "git@github.com:appium/skills.git",
        "ssh://git@github.com/appium/skills",
        "ssh://git@github.com/appium/skills.git",
    }:
        raise ValueError("upstream checkout origin is not the pinned repository")


def _tree_digest(contents: dict[str, bytes]) -> str:
    digest = hashlib.sha256(b"AutoGenesis Appium Skills subset v1\0")
    for relative in sorted(contents):
        encoded = relative.encode("utf-8")
        raw = contents[relative]
        digest.update(len(encoded).to_bytes(4, "big"))
        digest.update(encoded)
        digest.update(len(raw).to_bytes(8, "big"))
        digest.update(raw)
    return digest.hexdigest()


def bundle_bytes(repo: Path, upstream_root: Path | None = None) -> tuple[bytes, tuple[str, ...]]:
    root = repo / PACKAGE / "assets" / BUNDLE_RELATIVE
    provenance = _metadata(repo)
    expected = provenance["upstream_inventory"]
    local_actual = _scan_all(root)
    if local_actual != tuple(sorted((*expected, *LOCAL_ONLY, "manifest.json"))):
        raise ValueError("vendored snapshot has extra or missing assets")
    read = _asset_io(repo)["read_asset"]
    upstream_contents = {relative: read(root, relative) for relative in expected}
    if _tree_digest(upstream_contents) != provenance["upstream_tree_sha256"]:
        raise ValueError("vendored upstream tree digest differs from provenance metadata")
    if upstream_root is not None:
        upstream_root = upstream_root.resolve()
        root_resolved = root.resolve()
        if (
            upstream_root == root_resolved
            or upstream_root.is_relative_to(root_resolved)
            or root_resolved.is_relative_to(upstream_root)
        ):
            raise ValueError("upstream verification requires a separate checkout or exported tree")
        _verify_git_identity(upstream_root)
        upstream_actual = _scan(upstream_root, (*UPSTREAM_ROOTS, "LICENSE"))
        if upstream_actual != expected:
            raise ValueError("upstream checkout has extra or missing allowlisted assets")
        for relative, vendored in upstream_contents.items():
            upstream = read(upstream_root, relative)
            if vendored != upstream:
                raise ValueError(f"vendored Appium Skills asset differs from upstream: {relative}")
    local_paths = tuple(sorted((*expected, *LOCAL_ONLY)))
    hashes: dict[str, str] = {}
    for relative in local_paths:
        raw = read(root, relative)
        raw.decode("utf-8")
        if b"\r" in raw or raw.startswith(b"\xef\xbb\xbf") or not raw.endswith(b"\n"):
            raise ValueError("Pinned Appium Skills assets must be exact UTF-8/LF with a final LF")
        hashes[relative] = hashlib.sha256(raw).hexdigest()
    manifest = {
        "schema_version": 1,
        "source": SOURCE,
        "commit": COMMIT,
        "license": LICENSE,
        "assets": hashes,
    }
    return (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8"), local_paths


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--upstream-root", type=Path, required=True)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[2]
    try:
        manifest, _ = bundle_bytes(repo, args.upstream_root)
    except (OSError, UnicodeError, ValueError) as error:
        raise SystemExit(f"Appium Skills provenance error: {error}") from None
    output = f"{PACKAGE}/assets/{BUNDLE_MANIFEST}"
    if args.write:
        atomic_write(repo, output, manifest)
        print(f"Materialized Appium Skills snapshot {COMMIT} from verified upstream bytes.")
        return
    asset_io = _asset_io(repo)
    try:
        stored = asset_io["read_asset"](
            repo / PACKAGE / "assets", BUNDLE_MANIFEST, asset_io["MAX_MANIFEST_BYTES"]
        )
    except (OSError, ValueError):
        raise SystemExit("Appium Skills integrity error: manifest must be a bounded regular file.") from None
    if stored != manifest:
        raise SystemExit("Appium Skills drift: verified upstream bytes and snapshot manifest differ.")
    print(f"Appium Skills snapshot {COMMIT} matches the separately verified upstream checkout.")


if __name__ == "__main__":
    main()
