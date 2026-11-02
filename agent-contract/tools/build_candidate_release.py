"""Build one exact-wheel Candidate channel for pre-release AutoGenesis UAT."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import stat
import subprocess
import zipfile
from email.parser import BytesParser
from pathlib import Path

from _files import atomic_write
from freeze_assets import PACKAGE, load_asset_io, release_bytes

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
_MAX_LOCK_BYTES = 4 * 1024 * 1024
_HASH = re.compile(r"--hash=sha256:[0-9a-f]{64}(?:\s|$)")
SKILL = "skills/autogenesis/SKILL.md"
_MAX_WHEEL_BYTES = 64 * 1024 * 1024
_MAX_METADATA_BYTES = 256 * 1024


def _read_regular(path: Path, maximum: int) -> bytes:
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    try:
        expected = os.lstat(path)
        if not stat.S_ISREG(expected.st_mode) or expected.st_size <= 0 or expected.st_size > maximum:
            raise ValueError("candidate input must be a bounded regular non-symlink file")
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_BINARY", 0) | nofollow)
        try:
            opened = os.fstat(descriptor)
            if (opened.st_dev, opened.st_ino, opened.st_size) != (expected.st_dev, expected.st_ino, expected.st_size):
                raise ValueError("candidate input changed before read")
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
        raise ValueError("candidate input could not be read securely") from None
    if len(raw) != expected.st_size or len(raw) > maximum or (final.st_dev, final.st_ino, final.st_size) != (expected.st_dev, expected.st_ino, expected.st_size):
        raise ValueError("candidate input changed during read")
    return bytes(raw)


def _wheel_identity(raw: bytes) -> tuple[str, str]:
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            names = [name for name in archive.namelist() if name.endswith(".dist-info/METADATA")]
            if len(names) != 1 or archive.getinfo(names[0]).file_size > _MAX_METADATA_BYTES:
                raise ValueError("candidate wheel metadata is invalid")
            metadata = BytesParser().parsebytes(archive.read(names[0]))
    except (OSError, zipfile.BadZipFile, KeyError):
        raise ValueError("candidate wheel is invalid") from None
    name = metadata.get("Name")
    version = metadata.get("Version")
    if not isinstance(name, str) or not isinstance(version, str):
        raise ValueError("candidate wheel identity is missing")
    return name.lower().replace("_", "-"), version
def _dependency_lock(raw: bytes) -> None:
    try:
        text = raw.decode("utf-8")
    except UnicodeError:
        raise ValueError("dependency lock must be UTF-8") from None
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
        raise ValueError("dependency lock is empty or truncated")
    for entry in entries:
        requirement = entry.split(";", 1)[0]
        if (
            "==" not in requirement
            or not _HASH.search(entry)
            or requirement.startswith("-")
            or " @ " in requirement
            or "/" in requirement
            or "\\" in requirement
            or "${" in entry
        ):
            raise ValueError("dependency lock contains an unpinned or unsafe entry")




def _verify_commit(repo: Path, expected: str) -> None:
    try:
        head = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD"], check=True,
            capture_output=True, text=True,
        ).stdout.strip()
        tracked_clean = subprocess.run(
            ["git", "-C", str(repo), "diff-index", "--quiet", "HEAD", "--"],
            check=False,
        ).returncode == 0
        untracked = subprocess.run(
            [
                "git", "-C", str(repo), "status", "--porcelain=v1", "--untracked-files=all", "--",
                "agent-contract", "appium-mcp-server", "pywinauto-mcp-server", "autogenesis-cli",
            ],
            check=True, capture_output=True, text=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        raise SystemExit("Candidate source provenance could not be verified.") from None
    if head != expected or not tracked_clean or untracked:
        raise SystemExit("Candidate commit does not match a clean source checkout.")




def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheel-dir", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--dependency-lock", required=True, type=Path)
    args = parser.parse_args()
    if re.fullmatch(r"[0-9a-f]{40}", args.commit) is None:
        raise SystemExit("Candidate commit must be an exact lowercase Git commit.")

    repo = Path(__file__).resolve().parents[2]
    _verify_commit(repo, args.commit)
    package = repo / PACKAGE
    asset_io = load_asset_io(repo)
    expected_manifest, expected_pin = release_bytes(repo)
    if (
        asset_io["read_asset"](package / "assets", "manifest.json", asset_io["MAX_MANIFEST_BYTES"]),
        asset_io["read_asset"](package, "_release.py", asset_io["MAX_MANIFEST_BYTES"]),
    ) != (expected_manifest, expected_pin):
        raise SystemExit("Release drift: refusing to build a Candidate from unverified assets.")
    wheel_dir = args.wheel_dir.resolve(strict=True)

    found: dict[str, tuple[str, str, bytes]] = {}
    try:
        wheel_paths = tuple(wheel_dir.glob("*.whl"))
        for path in wheel_paths:
            raw = _read_regular(path, _MAX_WHEEL_BYTES)
            name, version = _wheel_identity(raw)
            if name not in EXPECTED:
                continue
            if version != EXPECTED[name] or name in found:
                raise ValueError("candidate wheel set has a version mismatch or duplicate")
            found[name] = (path.name, version, raw)
    except (OSError, ValueError) as error:
        raise SystemExit(f"Candidate integrity error: {error}") from None
    if set(found) != set(EXPECTED):
        raise SystemExit("Candidate wheel set is incomplete.")
    try:
        lock_raw = _read_regular(args.dependency_lock, _MAX_LOCK_BYTES)
        _dependency_lock(lock_raw)
    except ValueError as error:
        raise SystemExit(f"Candidate dependency lock error: {error}") from None

    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    base = args.base_url.rstrip("/")
    wheels = []
    checksum_rows = []
    for name in EXPECTED:
        filename, version, raw = found[name]
        digest = hashlib.sha256(raw).hexdigest()
        atomic_write(output, filename, raw)
        wheels.append({
            "package": name,
            "version": version,
            "filename": filename,
            "url": f"{base}/{filename}",
            "size": len(raw),
            "platforms": list(PLATFORMS[name]),
            "sha256": digest,
        })
        checksum_rows.append((digest, filename))
    install_lock_name = "candidate-install.lock"
    first_party_rows = []
    for wheel in wheels:
        marker = " ; sys_platform == 'win32'" if wheel["platforms"] == ["win32"] else ""
        first_party_rows.append(
            f"{wheel['package']}=={wheel['version']}{marker} \\\n"
            f"    --hash=sha256:{wheel['sha256']}\n"
        )
    first_party_lock = "".join(first_party_rows).encode("ascii")
    install_lock = first_party_lock + lock_raw
    _dependency_lock(install_lock)
    install_lock_digest = hashlib.sha256(install_lock).hexdigest()
    atomic_write(output, install_lock_name, install_lock)
    checksum_rows.append((install_lock_digest, install_lock_name))
    lock_name = "candidate-dependencies.lock"
    lock_digest = hashlib.sha256(lock_raw).hexdigest()
    atomic_write(output, lock_name, lock_raw)
    checksum_rows.append((lock_digest, lock_name))

    skill = asset_io["read_asset"](package / "assets", SKILL)
    skill_name = "autogenesis-SKILL.md"
    skill_digest = hashlib.sha256(skill).hexdigest()
    atomic_write(output, skill_name, skill)
    checksum_rows.append((skill_digest, skill_name))
    identity = json.loads(expected_manifest)
    candidate = {
        "schema_version": 1,
        "channel": "candidate",
        "commit": args.commit,
        "contract": {
            "version": identity["contract_version"],
            "manifest_sha256": hashlib.sha256(expected_manifest).hexdigest(),
        },
        "first_party_index_fallback": False,
        "third_party_policy": "user-selected-index-with-release-hash-lock",
        "dependency_locks": {
            "download": {
                "filename": lock_name,
                "url": f"{base}/{lock_name}",
                "size": len(lock_raw),
                "sha256": lock_digest,
            },
            "offline_install": {
                "filename": install_lock_name,
                "url": f"{base}/{install_lock_name}",
                "size": len(install_lock),
                "sha256": install_lock_digest,
            },
        },
        "skill": {
            "name": "autogenesis",
            "filename": skill_name,
            "url": f"{base}/{skill_name}",
            "sha256": skill_digest,
        },
        "wheels": wheels,
    }
    candidate_raw = (json.dumps(candidate, indent=2, sort_keys=True) + "\n").encode("utf-8")
    manifest_name = "candidate-manifest.json"
    atomic_write(output, manifest_name, candidate_raw)
    manifest_digest = hashlib.sha256(candidate_raw).hexdigest()
    checksum_rows.append((manifest_digest, manifest_name))
    checksums = "".join(f"{digest}  {name}\n" for digest, name in checksum_rows).encode("ascii")
    atomic_write(output, "SHA256SUMS", checksums)

    prompt = f"""Install this exact AutoGenesis Candidate for pre-release UAT, then stop before a business task.

Candidate manifest: {base}/{manifest_name}
Expected manifest SHA-256: {manifest_digest}
Candidate commit: {args.commit}
Reject Linux/WSL before any download or write. Download the manifest as untrusted bytes and verify its exact SHA-256 before interpreting it. Show the selected Python, package manager, third-party index, Skill scope/destination, exact host-applicable first-party wheel identities, both lock identities, writes, and rollback; obtain one approval. Download every host-applicable first-party wheel, both locks, and the Skill expected bytes only from manifest URLs and verify size/SHA-256; do not write the Skill yet. Use the selected index only to download third-party artifacts under the download lock's strict hash policy into a private staging directory. Verify every staged artifact, add the already verified first-party wheel bytes, disable indexes, and install the complete offline-install lock from that same staging directory in one package transaction with every locked package force-reinstalled and dependency resolution disabled. Never accept an installed distribution as satisfying the lock, and never resolve or replace a first-party Candidate package from an index. Then run `autogenesis install --scope <user-or-project> --project-root <absolute-business-project>` as the sole owner of the Skill write; it must reject every other canonical or legacy discovery copy. Verify the installed Skill equals the downloaded expected bytes, and verify the Contract manifest, internal Appium workflow inventory, package versions, selected scope, and discovery. Report the result and stop.
""".encode("utf-8")
    atomic_write(output, "candidate-install-prompt.txt", prompt)
    print(f"Built Candidate channel for {args.commit} with {len(wheels)} exact wheels.")


if __name__ == "__main__":
    main()
