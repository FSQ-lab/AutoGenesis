"""Build and verify exact target wheelhouses for one Candidate workflow run."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import platform
import re
import runpy
import shutil
import socket
import subprocess
import sys
import tempfile
import venv
import zipfile
from email.parser import BytesParser
from pathlib import Path

try:
    from packaging.requirements import Requirement
    from packaging.tags import compatible_tags, cpython_tags, mac_platforms, parse_tag
    from packaging.utils import canonicalize_name, parse_wheel_filename
    from packaging.version import Version
except ModuleNotFoundError:
    from pip._vendor.packaging.requirements import Requirement
    from pip._vendor.packaging.tags import compatible_tags, cpython_tags, mac_platforms, parse_tag
    from pip._vendor.packaging.utils import canonicalize_name, parse_wheel_filename
    from pip._vendor.packaging.version import Version

from _files import atomic_write
from install_prompt import REPOSITORY

EXPECTED = {
    "autogenesis-agent-contract": "2.1.0",
    "autogenesis-appium-mcp": "0.5.0",
    "autogenesis-windows-mcp": "0.5.0",
    "autogenesis-cli": "0.2.0",
}
PLATFORMS = {
    "autogenesis-agent-contract": ("darwin", "win32"),
    "autogenesis-appium-mcp": ("darwin", "win32"),
    "autogenesis-windows-mcp": ("win32",),
    "autogenesis-cli": ("darwin", "win32"),
}
TARGETS = {
    "darwin-arm64-py311": {
        "implementation": "CPython",
        "python_version": "3.11",
        "sys_platform": "darwin",
        "platform": "macos",
        "architecture": "arm64",
        "deployment_version": "15.0",
        "os_name": "posix",
        "platform_system": "Darwin",
        "platform_machine": "arm64",
    },
    "win32-amd64-py312": {
        "implementation": "CPython",
        "python_version": "3.12",
        "sys_platform": "win32",
        "platform": "windows",
        "architecture": "amd64",
        "os_name": "nt",
        "platform_system": "Windows",
        "platform_machine": "AMD64",
    },
}
SOURCE = {"host": "pypi.org", "class": "default-public", "index": "https://pypi.org/simple"}
BASE_MANIFEST = "candidate-base-manifest.json"
WHEELHOUSE_MANIFEST = "wheelhouse-manifest.json"
LOCK_NAME = "candidate-dependencies.lock"
_MAX_LOCK_BYTES = 4 * 1024 * 1024
_MAX_MANIFEST_BYTES = 4 * 1024 * 1024
_MAX_WHEEL_BYTES = 128 * 1024 * 1024
_MAX_WHEELS = 256
_MAX_WHEELHOUSE_BYTES = 512 * 1024 * 1024
_HASH = re.compile(r"--hash=sha256:([0-9a-f]{64})(?:\s|$)")


class WheelhouseError(ValueError):
    """One fixed diagnostic boundary for untrusted package input."""


def canonical_json(document: object) -> bytes:
    return (json.dumps(document, indent=2, sort_keys=True) + "\n").encode("utf-8")


def read_regular(path: Path, maximum: int) -> bytes:
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    try:
        expected = os.lstat(path)
        if not os.path.isfile(path) or os.path.islink(path) or expected.st_size <= 0 or expected.st_size > maximum:
            raise WheelhouseError("input must be a bounded regular non-symlink file")
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_BINARY", 0) | nofollow)
        try:
            opened = os.fstat(descriptor)
            if (opened.st_dev, opened.st_ino, opened.st_size) != (expected.st_dev, expected.st_ino, expected.st_size):
                raise WheelhouseError("input changed before read")
            raw = bytearray()
            while len(raw) <= maximum:
                chunk = os.read(descriptor, min(1024 * 1024, maximum + 1 - len(raw)))
                if not chunk:
                    break
                raw.extend(chunk)
            final = os.fstat(descriptor)
        finally:
            os.close(descriptor)
    except OSError:
        raise WheelhouseError("input could not be read securely") from None
    if (
        len(raw) != expected.st_size
        or len(raw) > maximum
        or (final.st_dev, final.st_ino, final.st_size) != (expected.st_dev, expected.st_ino, expected.st_size)
    ):
        raise WheelhouseError("input changed during read")
    return bytes(raw)


def _read_json(path: Path) -> dict:
    raw = read_regular(path, _MAX_MANIFEST_BYTES)
    try:
        document = json.loads(raw)
    except (UnicodeError, json.JSONDecodeError):
        raise WheelhouseError("manifest is not canonical JSON") from None
    if not isinstance(document, dict) or canonical_json(document) != raw:
        raise WheelhouseError("manifest is not canonical JSON")
    return document


def provenance(commit: str, run_id: str, run_attempt: str, artifact: str) -> dict[str, str]:
    if re.fullmatch(r"[0-9a-f]{40}", commit) is None:
        raise WheelhouseError("commit must be an exact lowercase Git commit")
    if not run_id.isdigit() or int(run_id) < 1 or not run_attempt.isdigit() or int(run_attempt) < 1:
        raise WheelhouseError("workflow run identity must contain positive integers")
    return {
        "repository": REPOSITORY,
        "workflow_run_id": run_id,
        "workflow_run_attempt": run_attempt,
        "commit": commit,
        "artifact": artifact,
    }


def _lock_entries(raw: bytes) -> list[tuple[Requirement, tuple[str, ...]]]:
    try:
        text = raw.decode("utf-8")
    except UnicodeError:
        raise WheelhouseError("dependency lock must be UTF-8") from None
    entries: list[str] = []
    current = ""
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        current = f"{current} {stripped}".strip()
        if current.endswith("\\"):
            current = current[:-1].rstrip()
            continue
        entries.append(current)
        current = ""
    if current or not entries:
        raise WheelhouseError("dependency lock is empty or truncated")

    parsed = []
    for entry in entries:
        hashes = tuple(sorted(set(_HASH.findall(entry))))
        requirement_text = re.sub(r"\s*--hash=sha256:[0-9a-f]{64}(?=\s|$)", "", entry).strip()
        try:
            requirement = Requirement(requirement_text)
        except Exception:
            raise WheelhouseError("dependency lock contains an unsafe requirement") from None
        specifiers = tuple(requirement.specifier)
        marker_text = str(requirement.marker) if requirement.marker is not None else ""
        if (
            len(specifiers) != 1
            or specifiers[0].operator != "=="
            or "*" in specifiers[0].version
            or requirement.url is not None
            or requirement.extras
            or not hashes
            or canonicalize_name(requirement.name) in EXPECTED
            or re.search(r"\b(?:python_full_version|implementation_version)\b", marker_text)
        ):
            raise WheelhouseError("dependency lock contains an unpinned, first-party, patch-sensitive, or unsafe entry")
        parsed.append((requirement, hashes))
    return parsed


def _marker_environment(target_key: str) -> dict[str, str]:
    target = TARGETS[target_key]
    version = target["python_version"]
    return {
        "implementation_name": "cpython",
        "implementation_version": f"{version}.0",
        "os_name": target["os_name"],
        "platform_machine": target["platform_machine"],
        "platform_release": "",
        "platform_system": target["platform_system"],
        "platform_version": "",
        "python_full_version": f"{version}.0",
        "platform_python_implementation": "CPython",
        "python_version": version,
        "sys_platform": target["sys_platform"],
        "extra": "",
    }


def target_lock(raw: bytes, target_key: str) -> dict[str, dict]:
    if target_key not in TARGETS:
        raise WheelhouseError("unsupported Candidate target")
    selected: dict[str, dict] = {}
    environment = _marker_environment(target_key)
    for requirement, hashes in _lock_entries(raw):
        if requirement.marker is not None and not requirement.marker.evaluate(environment=environment):
            continue
        name = canonicalize_name(requirement.name)
        version = tuple(requirement.specifier)[0].version
        if name in selected:
            raise WheelhouseError("target dependency lock contains a duplicate identity")
        selected[name] = {"version": version, "hashes": hashes}
    if not selected:
        raise WheelhouseError("target dependency lock is empty")
    return selected


def render_target_lock(selected: dict[str, dict]) -> bytes:
    rows = []
    for name in sorted(selected):
        hashes = " \\\n".join(f"    --hash=sha256:{digest}" for digest in selected[name]["hashes"])
        rows.append(f"{name}=={selected[name]['version']} \\\n{hashes}\n")
    return "".join(rows).encode("ascii")


def inspect_wheel(path: Path) -> tuple[dict, bytes]:
    raw = read_regular(path, _MAX_WHEEL_BYTES)
    try:
        filename_name, filename_version, _build, filename_tags = parse_wheel_filename(path.name)
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            metadata_names = [name for name in archive.namelist() if name.endswith(".dist-info/METADATA")]
            wheel_names = [name for name in archive.namelist() if name.endswith(".dist-info/WHEEL")]
            if len(metadata_names) != 1 or len(wheel_names) != 1:
                raise WheelhouseError("wheel metadata layout is invalid")
            if archive.getinfo(metadata_names[0]).file_size > 256 * 1024 or archive.getinfo(wheel_names[0]).file_size > 64 * 1024:
                raise WheelhouseError("wheel metadata is too large")
            metadata = BytesParser().parsebytes(archive.read(metadata_names[0]))
            wheel_metadata = BytesParser().parsebytes(archive.read(wheel_names[0]))
    except (OSError, ValueError, zipfile.BadZipFile, KeyError):
        raise WheelhouseError("wheel is invalid") from None

    metadata_name = metadata.get("Name")
    metadata_version = metadata.get("Version")
    declared_tags = wheel_metadata.get_all("Tag", [])
    try:
        wheel_tags = frozenset(tag for value in declared_tags for tag in parse_tag(value))
        same_version = Version(str(metadata_version)) == filename_version
    except Exception:
        raise WheelhouseError("wheel identity or tags are invalid") from None
    name = canonicalize_name(str(metadata_name))
    if name != canonicalize_name(filename_name) or not same_version or wheel_tags != filename_tags:
        raise WheelhouseError("wheel filename, metadata, and tags disagree")
    return ({
        "package": name,
        "version": str(filename_version),
        "filename": path.name,
        "size": len(raw),
        "tags": sorted(str(tag) for tag in filename_tags),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }, raw)


def _target_tags(target_key: str) -> frozenset[str]:
    target = TARGETS[target_key]
    python_version = tuple(int(value) for value in target["python_version"].split("."))
    if target["sys_platform"] == "darwin":
        deployment_version = tuple(int(value) for value in target["deployment_version"].split("."))
        platforms = tuple(mac_platforms(version=deployment_version, arch="arm64"))
    else:
        platforms = ("win_amd64",)
    tags = set(cpython_tags(python_version=python_version, platforms=platforms))
    tags.update(compatible_tags(python_version=python_version, interpreter=f"cp{python_version[0]}{python_version[1]}", platforms=platforms))
    return frozenset(str(tag) for tag in tags)


def _tag_compatible(tag_text: str, target_key: str) -> bool:
    return tag_text in _target_tags(target_key)


def _validate_inventory(
    directory: Path,
    target_key: str,
    dependency_lock: bytes,
    first_party: dict[str, dict],
) -> list[dict]:
    expected_third_party = target_lock(dependency_lock, target_key)
    records: dict[str, dict] = {}
    total = 0
    paths = sorted(directory.glob("*.whl"), key=lambda path: path.name)
    if not paths or len(paths) > _MAX_WHEELS:
        raise WheelhouseError("wheelhouse file count is invalid")
    for path in paths:
        record, _raw = inspect_wheel(path)
        total += record["size"]
        name = record["package"]
        if name in records:
            raise WheelhouseError("wheelhouse contains a duplicate package identity")
        if not any(_tag_compatible(tag, target_key) for tag in record["tags"]):
            raise WheelhouseError("wheelhouse contains a target-incompatible wheel")
        if name in EXPECTED:
            expected = first_party.get(name)
            if expected is None or any(record[key] != expected[key] for key in ("version", "filename", "size", "sha256")):
                raise WheelhouseError("wheelhouse contains a substituted first-party wheel")
            record["kind"] = "first-party"
        else:
            locked = expected_third_party.get(name)
            if locked is None or Version(record["version"]) != Version(locked["version"]) or record["sha256"] not in locked["hashes"]:
                raise WheelhouseError("wheelhouse contains an extra or substituted third-party wheel")
            record["kind"] = "third-party"
        records[name] = record
    if total > _MAX_WHEELHOUSE_BYTES:
        raise WheelhouseError("wheelhouse exceeds the total byte limit")
    required_first_party = {
        name for name, row in first_party.items() if TARGETS[target_key]["sys_platform"] in row["platforms"]
    }
    if set(records) != required_first_party | set(expected_third_party):
        raise WheelhouseError("wheelhouse dependency closure is incomplete")
    return [records[name] for name in sorted(records)]


def _first_party_rows(wheel_dir: Path) -> list[dict]:
    records = {}
    paths = sorted(wheel_dir.glob("*.whl"), key=lambda path: path.name)
    for path in paths:
        record, _raw = inspect_wheel(path)
        name = record["package"]
        if name not in EXPECTED or name in records or Version(record["version"]) != Version(EXPECTED[name]):
            raise WheelhouseError("first-party wheel set contains an unknown, duplicate, or mismatched identity")
        record.pop("tags")
        record["platforms"] = list(PLATFORMS[name])
        records[name] = record
    if set(records) != set(EXPECTED) or len(paths) != len(EXPECTED):
        raise WheelhouseError("first-party wheel set is incomplete")
    return [records[name] for name in EXPECTED]


def _set_digest(rows: list[dict]) -> str:
    return hashlib.sha256(canonical_json(rows)).hexdigest()


def render_candidate_requirements(wheel_dir: Path) -> bytes:
    rows = _first_party_rows(wheel_dir.resolve(strict=True))
    lines = []
    for row in rows:
        marker = " ; sys_platform == 'win32'" if row["platforms"] == ["win32"] else ""
        lines.append(f"{(wheel_dir / row['filename']).as_posix()}{marker}\n")
    return "".join(lines).encode("utf-8")


def write_candidate_requirements(wheel_dir: Path, output: Path) -> None:
    output = output.resolve()
    if output.exists():
        raise WheelhouseError("Candidate requirements output already exists")
    output.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(output.parent, output.name, render_candidate_requirements(wheel_dir))


def _replace_directory(staging: Path, output: Path) -> None:
    if output.exists():
        raise WheelhouseError("output directory already exists")
    os.replace(staging, output)


def prepare_base(
    wheel_dir: Path,
    dependency_lock_path: Path,
    output: Path,
    commit: str,
    run_id: str,
    run_attempt: str,
) -> dict:
    rows = _first_party_rows(wheel_dir.resolve(strict=True))
    lock_raw = read_regular(dependency_lock_path.resolve(strict=True), _MAX_LOCK_BYTES)
    for target_key in TARGETS:
        target_lock(lock_raw, target_key)
    artifact = f"autogenesis-candidate-base-{run_id}-{run_attempt}-{commit}"
    document = {
        "schema_version": 1,
        "kind": "candidate-base",
        "provenance": provenance(commit, run_id, run_attempt, artifact),
        "dependency_lock": {"filename": LOCK_NAME, "size": len(lock_raw), "sha256": hashlib.sha256(lock_raw).hexdigest()},
        "first_party_wheel_set_sha256": _set_digest(rows),
        "wheels": rows,
    }
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".candidate-base-", dir=output.parent))
    try:
        (staging / "wheels").mkdir()
        for row in rows:
            shutil.copyfile(wheel_dir / row["filename"], staging / "wheels" / row["filename"])
        atomic_write(staging, LOCK_NAME, lock_raw)
        atomic_write(staging, BASE_MANIFEST, canonical_json(document))
        _replace_directory(staging, output)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return document


def verify_base(base_dir: Path, commit: str, run_id: str, run_attempt: str) -> tuple[dict, bytes]:
    base_dir = base_dir.resolve(strict=True)
    document = _read_json(base_dir / BASE_MANIFEST)
    rows = _first_party_rows(base_dir / "wheels")
    lock_raw = read_regular(base_dir / LOCK_NAME, _MAX_LOCK_BYTES)
    expected = {
        "schema_version": 1,
        "kind": "candidate-base",
        "provenance": provenance(
            commit, run_id, run_attempt, f"autogenesis-candidate-base-{run_id}-{run_attempt}-{commit}"
        ),
        "dependency_lock": {"filename": LOCK_NAME, "size": len(lock_raw), "sha256": hashlib.sha256(lock_raw).hexdigest()},
        "first_party_wheel_set_sha256": _set_digest(rows),
        "wheels": rows,
    }
    wheel_names = {row["filename"] for row in rows}
    if {path.name for path in (base_dir / "wheels").iterdir()} != wheel_names:
        raise WheelhouseError("Candidate base wheel inventory is invalid")
    allowed = {BASE_MANIFEST, LOCK_NAME, "wheels"}
    if document != expected or {path.name for path in base_dir.iterdir()} != allowed:
        raise WheelhouseError("Candidate base provenance or inventory is invalid")
    return expected, lock_raw


def _minimal_pip_environment(private_home: Path) -> dict[str, str]:
    environment: dict[str, str] = {}
    for name in ("SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "TEMP", "TMP"):
        if name in os.environ:
            environment[name] = os.environ[name]
    environment.update({
        "HOME": str(private_home),
        "USERPROFILE": str(private_home),
        "NETRC": "nul" if os.name == "nt" else os.devnull,
        "PIP_CONFIG_FILE": "nul" if os.name == "nt" else os.devnull,
        "PIP_DISABLE_PIP_VERSION_CHECK": "1",
        "PIP_KEYRING_PROVIDER": "disabled",
        "PIP_NO_INPUT": "1",
        "PYTHONNOUSERSITE": "1",
    })
    return environment


def _assert_target_host(target_key: str) -> None:
    target = TARGETS[target_key]
    machine = platform.machine().lower()
    architecture = "arm64" if machine in {"arm64", "aarch64"} else "amd64" if machine in {"amd64", "x86_64"} else machine
    observed_version = f"{sys.version_info.major}.{sys.version_info.minor}"
    deployment_ok = True
    if target["sys_platform"] == "darwin":
        try:
            deployment_ok = Version(platform.mac_ver()[0]) >= Version(target["deployment_version"])
        except Exception:
            deployment_ok = False
    if (
        sys.implementation.name != "cpython"
        or observed_version != target["python_version"]
        or sys.platform != target["sys_platform"]
        or architecture != target["architecture"]
        or not deployment_ok
    ):
        raise WheelhouseError("acquisition host does not match the exact Candidate target")


def wheelhouse_document(
    directory: Path,
    base: dict,
    dependency_lock: bytes,
    target_key: str,
    commit: str,
    run_id: str,
    run_attempt: str,
) -> dict:
    if target_key not in TARGETS:
        raise WheelhouseError("unsupported Candidate target")
    first_party = {row["package"]: row for row in base["wheels"]}
    inventory = _validate_inventory(directory, target_key, dependency_lock, first_party)
    artifact = f"autogenesis-candidate-wheelhouse-{target_key}-{run_id}-{run_attempt}-{commit}"
    return {
        "schema_version": 1,
        "kind": "candidate-target-wheelhouse",
        "provenance": provenance(commit, run_id, run_attempt, artifact),
        "target": {"key": target_key, **TARGETS[target_key]},
        "source": {"host": SOURCE["host"], "class": SOURCE["class"]},
        "dependency_lock_sha256": base["dependency_lock"]["sha256"],
        "first_party_wheel_set_sha256": base["first_party_wheel_set_sha256"],
        "files": inventory,
    }


def acquire_wheelhouse(
    base_dir: Path,
    target_key: str,
    output: Path,
    commit: str,
    run_id: str,
    run_attempt: str,
) -> dict:
    if target_key not in TARGETS:
        raise WheelhouseError("unsupported Candidate target")
    _assert_target_host(target_key)
    base, lock_raw = verify_base(base_dir, commit, run_id, run_attempt)
    selected = target_lock(lock_raw, target_key)
    artifact = f"autogenesis-candidate-wheelhouse-{target_key}-{run_id}-{run_attempt}-{commit}"
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    transaction = Path(tempfile.mkdtemp(prefix=f".{target_key}-", dir=output.parent))
    staging = transaction / "wheelhouse"
    private_home = transaction / "home"
    staging.mkdir()
    private_home.mkdir(mode=0o700)
    try:
        target_lock_path = staging / ".target.lock"
        atomic_write(staging, target_lock_path.name, render_target_lock(selected))
        command = [
            sys.executable, "-I", "-m", "pip", "download", "--isolated", "--disable-pip-version-check",
            "--no-cache-dir", "--only-binary=:all:", "--require-hashes", "--no-deps",
            "--index-url", SOURCE["index"], "--dest", str(staging), "--requirement", str(target_lock_path),
        ]
        result = subprocess.run(
            command,
            env=_minimal_pip_environment(private_home),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=900,
            check=False,
        )
        target_lock_path.unlink(missing_ok=True)
        if result.returncode != 0:
            raise WheelhouseError("fixed-source wheel-only acquisition failed")
        first_party = {row["package"]: row for row in base["wheels"]}
        for row in base["wheels"]:
            if TARGETS[target_key]["sys_platform"] in row["platforms"]:
                destination = staging / row["filename"]
                if destination.exists():
                    raise WheelhouseError("first-party wheel filename collides with acquired content")
                shutil.copyfile(base_dir / "wheels" / row["filename"], destination)
        document = wheelhouse_document(
            staging, base, lock_raw, target_key, commit, run_id, run_attempt
        )
        atomic_write(staging, WHEELHOUSE_MANIFEST, canonical_json(document))
        _replace_directory(staging, output)
    finally:
        shutil.rmtree(transaction, ignore_errors=True)
    return document


def verify_wheelhouse(
    directory: Path,
    base: dict,
    dependency_lock: bytes,
    target_key: str,
    commit: str,
    run_id: str,
    run_attempt: str,
) -> tuple[dict, bytes]:
    directory = directory.resolve(strict=True)
    document = _read_json(directory / WHEELHOUSE_MANIFEST)
    expected = wheelhouse_document(
        directory, base, dependency_lock, target_key, commit, run_id, run_attempt
    )
    allowed = {WHEELHOUSE_MANIFEST} | {row["filename"] for row in expected["files"]}
    if document != expected or {path.name for path in directory.iterdir()} != allowed:
        raise WheelhouseError("target wheelhouse provenance or inventory is invalid")
    return expected, canonical_json(expected)


def verify_checksum_closure(candidate_dir: Path) -> dict[str, str]:
    candidate_dir = candidate_dir.resolve(strict=True)
    raw = read_regular(candidate_dir / "SHA256SUMS", _MAX_MANIFEST_BYTES)
    try:
        lines = raw.decode("ascii").splitlines()
    except UnicodeError:
        raise WheelhouseError("Candidate checksum closure is invalid") from None
    checksums: dict[str, str] = {}
    for line in lines:
        match = re.fullmatch(r"([0-9a-f]{64})  ([A-Za-z0-9._/-]+)", line)
        if match is None:
            raise WheelhouseError("Candidate checksum closure is invalid")
        digest, relative = match.groups()
        path = Path(relative)
        if path.is_absolute() or ".." in path.parts or relative == "SHA256SUMS" or relative in checksums:
            raise WheelhouseError("Candidate checksum closure is invalid")
        checksums[relative] = digest
    actual = {
        path.relative_to(candidate_dir).as_posix()
        for path in candidate_dir.rglob("*")
        if path.is_file() and path.name != "SHA256SUMS"
    }
    if set(checksums) != actual:
        raise WheelhouseError("Candidate checksum closure is incomplete")
    for relative, digest in checksums.items():
        if hashlib.sha256(read_regular(candidate_dir / relative, _MAX_WHEEL_BYTES)).hexdigest() != digest:
            raise WheelhouseError("Candidate checksum closure contains a mismatch")
    return checksums


def _offline_pip(arguments: list[str]) -> int:
    def denied(*_args, **_kwargs):
        raise RuntimeError("network access is denied during Candidate installation")

    class DeniedSocket(socket.socket):
        def connect(self, *_args, **_kwargs):
            denied()

        def connect_ex(self, *_args, **_kwargs):
            denied()

    socket.getaddrinfo = denied
    socket.create_connection = denied
    socket.socket = DeniedSocket
    sys.argv = ["pip", *arguments]
    try:
        runpy.run_module("pip", run_name="__main__")
    except SystemExit as error:
        return int(error.code or 0)
    return 0


def verify_candidate_target(candidate_dir: Path, manifest: dict, target_key: str) -> list[dict]:
    if manifest.get("schema_version") != 3 or manifest.get("channel") != "candidate":
        raise WheelhouseError("Candidate manifest interface is unsupported")
    wheelhouses = manifest.get("wheelhouses")
    matches = [
        row for row in wheelhouses
        if isinstance(row, dict) and row.get("target", {}).get("key") == target_key
    ] if isinstance(wheelhouses, list) else []
    if len(matches) != 1:
        raise WheelhouseError("Candidate target selection is unsupported or ambiguous")
    selected = matches[0]
    prefix = f"wheelhouse/{target_key}"
    expected_manifest_path = f"{prefix}/{WHEELHOUSE_MANIFEST}"
    if selected.get("manifest", {}).get("path") != expected_manifest_path:
        raise WheelhouseError("Candidate target manifest path is invalid")
    manifest_raw = read_regular(candidate_dir / expected_manifest_path, _MAX_MANIFEST_BYTES)
    if (
        selected["manifest"].get("size") != len(manifest_raw)
        or selected["manifest"].get("sha256") != hashlib.sha256(manifest_raw).hexdigest()
    ):
        raise WheelhouseError("Candidate target manifest identity is invalid")
    base_rows = []
    for row in manifest.get("wheels", []):
        if not isinstance(row, dict):
            raise WheelhouseError("Candidate first-party inventory is invalid")
        base_rows.append({key: row[key] for key in ("package", "version", "filename", "size", "sha256", "platforms")})
    lock_raw = read_regular(candidate_dir / LOCK_NAME, _MAX_LOCK_BYTES)
    base = {
        "wheels": base_rows,
        "dependency_lock": {"sha256": hashlib.sha256(lock_raw).hexdigest()},
        "first_party_wheel_set_sha256": _set_digest(base_rows),
    }
    provenance_row = manifest.get("provenance", {})
    expected, _canonical = verify_wheelhouse(
        candidate_dir / "wheelhouse" / target_key,
        base,
        lock_raw,
        target_key,
        manifest.get("commit", ""),
        provenance_row.get("workflow_run_id", ""),
        provenance_row.get("workflow_run_attempt", ""),
    )
    expected_files = [
        {**row, "path": f"{prefix}/{row['filename']}", "url": f"./{prefix}/{row['filename']}"}
        for row in expected["files"]
    ]
    expected_selected = {
        "target": expected["target"],
        "source": expected["source"],
        "dependency_lock_sha256": expected["dependency_lock_sha256"],
        "first_party_wheel_set_sha256": expected["first_party_wheel_set_sha256"],
        "manifest": {
            "path": expected_manifest_path,
            "url": f"./{expected_manifest_path}",
            "size": len(manifest_raw),
            "sha256": hashlib.sha256(manifest_raw).hexdigest(),
        },
        "files": expected_files,
    }
    if selected != expected_selected:
        raise WheelhouseError("Candidate target inventory is inconsistent")
    return expected["files"]


def offline_install(candidate_dir: Path, target_key: str, environment_dir: Path) -> None:
    if target_key not in TARGETS:
        raise WheelhouseError("unsupported Candidate target")
    _assert_target_host(target_key)
    verify_checksum_closure(candidate_dir)
    manifest = _read_json(candidate_dir / "candidate-manifest.json")
    installed_rows = verify_candidate_target(candidate_dir, manifest, target_key)
    wheelhouse = candidate_dir / "wheelhouse" / target_key
    environment_dir = environment_dir.resolve()
    if environment_dir.exists():
        raise WheelhouseError("offline install environment must be absent")
    venv.EnvBuilder(with_pip=True).create(environment_dir)
    private_home = environment_dir / ".installer-home"
    private_home.mkdir(mode=0o700)
    environment = _minimal_pip_environment(private_home)
    python = environment_dir / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    arguments = [
        "install", "--isolated", "--disable-pip-version-check", "--no-index", "--no-cache-dir",
        "--only-binary=:all:", "--find-links", str(wheelhouse), "--require-hashes", "--no-deps",
        "--force-reinstall", "--requirement", str(candidate_dir / "candidate-install.lock"),
    ]
    command = [str(python), str(Path(__file__).resolve()), "_offline-pip", *arguments]
    result = subprocess.run(
        command, env=environment, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL, check=False, timeout=900,
    )
    if result.returncode != 0:
        shutil.rmtree(private_home, ignore_errors=True)
        raise WheelhouseError("network-denied offline Candidate installation failed")
    check = subprocess.run(
        [str(python), "-I", "-m", "pip", "check"], env=environment,
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        check=False, timeout=120,
    )
    if check.returncode != 0:
        shutil.rmtree(private_home, ignore_errors=True)
        raise WheelhouseError("installed Candidate dependency metadata is inconsistent")
    evidence_path = environment_dir / ".candidate-install-evidence.json"
    evidence_script = """import hashlib, importlib.metadata, json, pathlib, sys\nfrom autogenesis_agent_contract import load_contract\ncontract = load_contract()\nevidence = {'inventory': sorted((item.metadata['Name'], item.version) for item in importlib.metadata.distributions()), 'identity': contract.identity.to_dict(), 'skill_sha256': hashlib.sha256(contract.read_skill('autogenesis')).hexdigest()}\npathlib.Path(sys.argv[1]).write_text(json.dumps(evidence, sort_keys=True), encoding='utf-8')\n"""
    evidence = subprocess.run(
        [str(python), "-I", "-c", evidence_script, str(evidence_path)], env=environment,
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        check=False, timeout=120,
    )
    try:
        observed = json.loads(read_regular(evidence_path, _MAX_MANIFEST_BYTES)) if evidence.returncode == 0 else None
    except (OSError, UnicodeError, json.JSONDecodeError):
        observed = None
    evidence_path.unlink(missing_ok=True)
    expected_inventory = {
        canonicalize_name(row["package"]): str(Version(row["version"])) for row in installed_rows
    }
    observed_inventory = {
        canonicalize_name(name): str(Version(version))
        for name, version in observed.get("inventory", [])
        if canonicalize_name(name) not in {"pip", "setuptools"}
    } if isinstance(observed, dict) else {}
    observed_identity = observed.get("identity") if isinstance(observed, dict) else None
    observed_skill = observed.get("skill_sha256") if isinstance(observed, dict) else None
    expected_identity = {
        "contract_version": manifest["contract"]["version"],
        "manifest_sha256": manifest["contract"]["manifest_sha256"],
        "schema_version": 2,
    }
    expected_skill = hashlib.sha256(read_regular(candidate_dir / "autogenesis-SKILL.md", _MAX_MANIFEST_BYTES)).hexdigest()
    if (
        observed_inventory != expected_inventory
        or observed_identity != expected_identity
        or observed_skill != expected_skill
    ):
        shutil.rmtree(private_home, ignore_errors=True)
        raise WheelhouseError("installed Candidate inventory, Contract identity, or Skill bytes are inconsistent")
    shutil.rmtree(private_home, ignore_errors=True)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in ("base", "acquire"):
        command = subparsers.add_parser(name)
        command.add_argument("--commit", required=True)
        command.add_argument("--workflow-run-id", required=True)
        command.add_argument("--workflow-run-attempt", required=True)
        command.add_argument("--output-dir", required=True, type=Path)
    requirements = subparsers.add_parser("requirements")
    requirements.add_argument("--wheel-dir", required=True, type=Path)
    requirements.add_argument("--output-file", required=True, type=Path)
    base = subparsers.choices["base"]
    base.add_argument("--wheel-dir", required=True, type=Path)
    base.add_argument("--dependency-lock", required=True, type=Path)
    acquire = subparsers.choices["acquire"]
    acquire.add_argument("--base-dir", required=True, type=Path)
    acquire.add_argument("--target", required=True, choices=tuple(TARGETS))
    install = subparsers.add_parser("offline-install")
    install.add_argument("--candidate-dir", required=True, type=Path)
    install.add_argument("--target", required=True, choices=tuple(TARGETS))
    install.add_argument("--environment-dir", required=True, type=Path)
    hidden = subparsers.add_parser("_offline-pip")
    hidden.add_argument("arguments", nargs=argparse.REMAINDER)
    return parser


def main() -> None:
    args = _parser().parse_args()
    try:
        if args.command == "requirements":
            write_candidate_requirements(args.wheel_dir, args.output_file)
        elif args.command == "base":
            prepare_base(
                args.wheel_dir, args.dependency_lock, args.output_dir,
                args.commit, args.workflow_run_id, args.workflow_run_attempt,
            )
        elif args.command == "acquire":
            acquire_wheelhouse(
                args.base_dir, args.target, args.output_dir,
                args.commit, args.workflow_run_id, args.workflow_run_attempt,
            )
        elif args.command == "offline-install":
            offline_install(args.candidate_dir, args.target, args.environment_dir)
        else:
            raise SystemExit(_offline_pip(args.arguments))
    except (OSError, WheelhouseError, subprocess.TimeoutExpired) as error:
        raise SystemExit(f"Candidate wheelhouse error: {error}") from None


if __name__ == "__main__":
    main()
