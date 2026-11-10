"""Build immutable Skill release assets and the copy-paste Agent Install Prompt."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

from _files import atomic_write
from freeze_assets import PACKAGE, load_asset_io, release_bytes
from install_prompt import RELEASE_TAG, hardened_install_contract, public_asset_locations

SKILLS = ("autogenesis",)
EXPECTED = {
    "autogenesis-agent-contract": "2.1.0",
    "autogenesis-appium-mcp": "0.5.0",
    "autogenesis-windows-mcp": "0.5.0",
    "autogenesis-cli": "0.2.0",
}
_MAX_LOCK_BYTES = 4 * 1024 * 1024
_HASH = re.compile(r"--hash=sha256:[0-9a-f]{64}(?:\s|$)")


def _validate_lock(raw: bytes) -> None:
    try:
        text = raw.decode("utf-8")
    except UnicodeError:
        raise SystemExit("Release dependency lock must be UTF-8.") from None
    entries, current = [], ""
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
        raise SystemExit("Release dependency lock is empty or truncated.")
    for entry in entries:
        requirement = entry.split(";", 1)[0]
        if (
            "==" not in requirement or not _HASH.search(entry)
            or requirement.startswith("-") or " @ " in requirement
            or "/" in requirement or "\\" in requirement or "${" in entry
        ):
            raise SystemExit("Release dependency lock contains an unsafe entry.")




def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--release-manifest", type=Path, required=True)
    parser.add_argument("--release-manifest-url", required=True)
    parser.add_argument("--dependency-lock", type=Path, required=True)
    args = parser.parse_args()
    try:
        base, release_manifest_url = public_asset_locations(args.base_url, args.release_manifest_url)
    except ValueError:
        raise SystemExit("Release asset location is unsafe.") from None
    repo = Path(__file__).resolve().parents[2]
    package = repo / PACKAGE
    asset_io = load_asset_io(repo)
    expected_manifest, expected_pin = release_bytes(repo)
    manifest = asset_io["read_asset"](package / "assets", "manifest.json", asset_io["MAX_MANIFEST_BYTES"])
    pin = asset_io["read_asset"](package, "_release.py", asset_io["MAX_MANIFEST_BYTES"])
    if (manifest, pin) != (expected_manifest, expected_pin):
        raise SystemExit("Release drift: refusing to publish unverified Skills.")
    identity = json.loads(manifest)
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise SystemExit("Release output directory must be empty.")
    rows = []
    for name in SKILLS:
        relative = f"skills/{name}/SKILL.md"
        raw = asset_io["read_asset"](package / "assets", relative)
        digest = hashlib.sha256(raw).hexdigest()
        if identity["assets"].get(relative) != digest:
            raise SystemExit("Skill digest differs from the frozen Contract manifest.")
        filename = f"{name}-SKILL.md"
        atomic_write(output, filename, raw)
        rows.append((digest, filename))
    release_manifest = args.release_manifest
    try:
        release_raw = asset_io["read_asset"](
            release_manifest.parent,
            release_manifest.name,
            asset_io["MAX_MANIFEST_BYTES"],
        )
    except (OSError, ValueError):
        raise SystemExit("Release manifest could not be read securely.") from None
    if not release_raw:
        raise SystemExit("Release manifest size is invalid.")
    try:
        release_document = json.loads(release_raw)
    except (UnicodeError, ValueError):
        raise SystemExit("Release manifest is invalid JSON.") from None
    if not isinstance(release_document, dict) or not release_document.get("wheels"):
        raise SystemExit("Release manifest has no reviewed wheels.")
    provenance = release_document.get("provenance")
    release_commit = provenance.get("commit") if isinstance(provenance, dict) else None
    if not isinstance(release_commit, str) or re.fullmatch(r"[0-9a-f]{40}", release_commit) is None:
        raise SystemExit("Release manifest has no exact reviewed commit provenance.")
    wheel_records = {}
    for record in release_document["wheels"]:
        if not isinstance(record, dict):
            raise SystemExit("Release manifest wheel entry is invalid.")
        package_name = str(record.get("package", "")).lower().replace("_", "-")
        if (
            package_name not in EXPECTED
            or record.get("version") != EXPECTED[package_name]
            or not isinstance(record.get("sha256"), str)
            or re.fullmatch(r"[0-9a-f]{64}", record["sha256"]) is None
            or package_name in wheel_records
        ):
            raise SystemExit("Release manifest wheel set is invalid.")
        wheel_records[package_name] = record
    if set(wheel_records) != set(EXPECTED):
        raise SystemExit("Release manifest wheel set is incomplete.")
    try:
        dependency_raw = asset_io["read_asset"](
            args.dependency_lock.parent, args.dependency_lock.name, _MAX_LOCK_BYTES,
        )
    except (OSError, ValueError):
        raise SystemExit("Release dependency lock could not be read securely.") from None
    _validate_lock(dependency_raw)
    first_party_rows = []
    for package_name, version in EXPECTED.items():
        marker = " ; sys_platform == 'win32'" if package_name == "autogenesis-windows-mcp" else ""
        first_party_rows.append(
            f"{package_name}=={version}{marker} \\\n"
            f"    --hash=sha256:{wheel_records[package_name]['sha256']}\n"
        )
    release_lock = "".join(first_party_rows).encode("ascii") + dependency_raw
    _validate_lock(release_lock)
    lock_name = "autogenesis-release.lock"
    lock_digest = hashlib.sha256(release_lock).hexdigest()
    atomic_write(output, lock_name, release_lock)
    rows.append((lock_digest, lock_name))
    release_digest = hashlib.sha256(release_raw).hexdigest()
    atomic_write(output, "release-manifest.json", release_raw)
    rows.append((release_digest, "release-manifest.json"))
    skill_digest, skill_filename = rows[0]
    contract = hardened_install_contract(
        channel="public Release",
        external_anchor=(
            "Require the published immutable GitHub Release in `FSQ-lab/AutoGenesis`, tag "
            f"`{RELEASE_TAG}`, exact tag commit `{release_commit}`, and one observed positive Release ID. "
            "Bind the immutable Release's exact asset IDs, names, and sizes before download; reject a draft, "
            "mutable release, tag/commit mismatch, different Release ID, or copied asset directory."
        ),
        acquire=(
            "Download the Release manifest, Release lock, Skill, and checksum set only through the exact "
            "immutable Release asset IDs. Require the manifest to bind the CLI and host Runtime wheel identities "
            "and the lock's first-party hashes to equal the manifest. Through the approved source, stage every "
            "locked package under strict hash mode in a new public-install-only staging directory, verify the "
            "complete lock, and then disable indexes."
        ),
        install=(
            "Using the disposable environment's absolute Python, install that same complete lock from the staging "
            "directory in one offline transaction with strict hashes, dependency resolution disabled, and every "
            "locked package force-reinstalled. Never accept an already-installed distribution as satisfying the "
            "lock. Then run `<absolute-disposable-environment-entrypoint>/autogenesis install --scope "
            "<user-or-project> --project-root <absolute-business-project>` as the sole owner of the Skill write; "
            "it must reject every other canonical or legacy discovery copy."
        ),
        cleanup="public-install-only downloaded, extracted, staged, selected-scope, MCP, and cache state created by this prompt",
    )
    prompt = f"""Install the official AutoGenesis Skill and CLI, then stop before running a business task.

Immutable Release: https://github.com/FSQ-lab/AutoGenesis/releases/tag/{RELEASE_TAG}
Expected Release tag commit: {release_commit}
Immutable Skill source: {base}/{skill_filename}
Expected Skill SHA-256: {skill_digest}
Skill name: autogenesis
Release manifest: {release_manifest_url}
Expected release manifest SHA-256: {release_digest}
Release lock: {base}/{lock_name}
Expected Release lock SHA-256: {lock_digest}
Complete checksums: {base}/SHA256SUMS

{contract}""".encode("utf-8")
    prompt_name = "agent-install-prompt.txt"
    atomic_write(output, prompt_name, prompt)
    rows.append((hashlib.sha256(prompt).hexdigest(), prompt_name))

    checksums = "".join(f"{digest}  {filename}\n" for digest, filename in rows).encode("ascii")
    atomic_write(output, "SHA256SUMS", checksums)
    print(f"Built Skill release assets for Contract {identity['contract_version']}.")


if __name__ == "__main__":
    main()
