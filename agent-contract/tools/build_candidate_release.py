"""Build one exact-wheel Candidate channel for pre-release AutoGenesis UAT."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path

from _files import atomic_write
from candidate_wheelhouse import (
    EXPECTED,
    LOCK_NAME,
    PLATFORMS,
    TARGETS,
    WHEELHOUSE_MANIFEST,
    WheelhouseError,
    canonical_json,
    read_regular,
    verify_base,
    verify_wheelhouse,
)
from freeze_assets import PACKAGE, load_asset_io, release_bytes
from install_prompt import REPOSITORY, candidate_asset_location, hardened_install_contract

SKILL = "skills/autogenesis/SKILL.md"
_MAX_LOCK_BYTES = 4 * 1024 * 1024
_MAX_WHEEL_BYTES = 128 * 1024 * 1024


def _copy_verified(root: Path, relative: str, source: Path, maximum: int) -> tuple[str, int]:
    raw = read_regular(source, maximum)
    atomic_write(root, relative, raw)
    return hashlib.sha256(raw).hexdigest(), len(raw)


def _checksum_row(checksum_rows: list[tuple[str, str]], root: Path, relative: str) -> None:
    raw = read_regular(root / relative, _MAX_WHEEL_BYTES)
    checksum_rows.append((hashlib.sha256(raw).hexdigest(), relative))



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
    parser.add_argument("--base-dir", required=True, type=Path)
    parser.add_argument("--darwin-wheelhouse", required=True, type=Path)
    parser.add_argument("--windows-wheelhouse", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--workflow-run-id", required=True)
    parser.add_argument("--workflow-run-attempt", required=True)
    args = parser.parse_args()
    if re.fullmatch(r"[0-9a-f]{40}", args.commit) is None:
        raise SystemExit("Candidate commit must be an exact lowercase Git commit.")
    try:
        base_url = candidate_asset_location(args.base_url)
    except ValueError:
        raise SystemExit("Candidate asset location is unsafe.") from None

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

    try:
        base_dir = args.base_dir.resolve(strict=True)
        base_manifest, lock_raw = verify_base(
            base_dir, args.commit, args.workflow_run_id, args.workflow_run_attempt
        )
        wheelhouse_inputs = {
            "darwin-arm64-py311": args.darwin_wheelhouse,
            "win32-amd64-py312": args.windows_wheelhouse,
        }
        verified_wheelhouses = {
            target: verify_wheelhouse(
                path, base_manifest, lock_raw, target,
                args.commit, args.workflow_run_id, args.workflow_run_attempt,
            )
            for target, path in wheelhouse_inputs.items()
        }
    except (OSError, WheelhouseError) as error:
        raise SystemExit(f"Candidate integrity error: {error}") from None

    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise SystemExit("Candidate output directory must be empty.")
    checksum_rows: list[tuple[str, str]] = []
    wheels = []
    for row in base_manifest["wheels"]:
        relative = row["filename"]
        _copy_verified(output, relative, base_dir / "wheels" / relative, _MAX_WHEEL_BYTES)
        wheel = {**row, "url": f"{base_url}/{relative}"}
        wheels.append(wheel)
        checksum_rows.append((row["sha256"], relative))

    install_lock_name = "candidate-install.lock"
    first_party_rows = []
    for wheel in wheels:
        marker = " ; sys_platform == 'win32'" if wheel["platforms"] == ["win32"] else ""
        first_party_rows.append(
            f"{wheel['package']}=={wheel['version']}{marker} \\\n"
            f"    --hash=sha256:{wheel['sha256']}\n"
        )
    install_lock = "".join(first_party_rows).encode("ascii") + lock_raw
    install_lock_digest = hashlib.sha256(install_lock).hexdigest()
    atomic_write(output, install_lock_name, install_lock)
    checksum_rows.append((install_lock_digest, install_lock_name))
    lock_digest = hashlib.sha256(lock_raw).hexdigest()
    atomic_write(output, LOCK_NAME, lock_raw)
    checksum_rows.append((lock_digest, LOCK_NAME))

    wheelhouses = []
    for target in TARGETS:
        document, manifest_raw = verified_wheelhouses[target]
        source = wheelhouse_inputs[target].resolve(strict=True)
        prefix = f"wheelhouse/{target}"
        manifest_relative = f"{prefix}/{WHEELHOUSE_MANIFEST}"
        atomic_write(output, manifest_relative, manifest_raw)
        checksum_rows.append((hashlib.sha256(manifest_raw).hexdigest(), manifest_relative))
        files = []
        for row in document["files"]:
            relative = f"{prefix}/{row['filename']}"
            _copy_verified(output, relative, source / row["filename"], _MAX_WHEEL_BYTES)
            checksum_rows.append((row["sha256"], relative))
            files.append({**row, "path": relative, "url": f"{base_url}/{relative}"})
        wheelhouses.append({
            "target": document["target"],
            "source": document["source"],
            "dependency_lock_sha256": document["dependency_lock_sha256"],
            "first_party_wheel_set_sha256": document["first_party_wheel_set_sha256"],
            "manifest": {
                "path": manifest_relative,
                "url": f"{base_url}/{manifest_relative}",
                "size": len(manifest_raw),
                "sha256": hashlib.sha256(manifest_raw).hexdigest(),
            },
            "files": files,
        })

    skill = asset_io["read_asset"](package / "assets", SKILL)
    skill_name = "autogenesis-SKILL.md"
    skill_digest = hashlib.sha256(skill).hexdigest()
    atomic_write(output, skill_name, skill)
    checksum_rows.append((skill_digest, skill_name))
    identity = json.loads(expected_manifest)
    candidate = {
        "schema_version": 3,
        "channel": "candidate",
        "provenance": {
            "repository": REPOSITORY,
            "workflow_run_id": args.workflow_run_id,
            "workflow_run_attempt": args.workflow_run_attempt,
            "artifact": f"autogenesis-candidate-{args.workflow_run_id}-{args.workflow_run_attempt}-{args.commit}",
        },
        "commit": args.commit,
        "contract": {
            "version": identity["contract_version"],
            "manifest_sha256": hashlib.sha256(expected_manifest).hexdigest(),
        },
        "first_party_index_fallback": False,
        "third_party_policy": "bundled-exact-target-wheelhouses-no-index",
        "dependency_locks": {
            "universal": {
                "filename": LOCK_NAME,
                "url": f"{base_url}/{LOCK_NAME}",
                "size": len(lock_raw),
                "sha256": lock_digest,
            },
            "offline_install": {
                "filename": install_lock_name,
                "url": f"{base_url}/{install_lock_name}",
                "size": len(install_lock),
                "sha256": install_lock_digest,
            },
        },
        "skill": {
            "name": "autogenesis",
            "filename": skill_name,
            "url": f"{base_url}/{skill_name}",
            "sha256": skill_digest,
        },
        "wheels": wheels,
        "wheelhouses": wheelhouses,
    }
    candidate_raw = canonical_json(candidate)
    manifest_name = "candidate-manifest.json"
    atomic_write(output, manifest_name, candidate_raw)
    manifest_digest = hashlib.sha256(candidate_raw).hexdigest()
    checksum_rows.append((manifest_digest, manifest_name))

    artifact_name = candidate["provenance"]["artifact"]
    contract = hardened_install_contract(
        channel="Candidate",
        external_anchor=(
            f"In canonical repository `{REPOSITORY}`, require exact Actions run `{args.workflow_run_id}`, "
            f"positive run attempt `{args.workflow_run_attempt}`, head commit `{args.commit}`, and attempt-qualified "
            f"artifact name `{artifact_name}`. Before interpreting bundle instructions, resolve exactly one unexpired "
            "immutable GitHub Actions artifact with a positive observed artifact ID and independently supplied positive "
            "GitHub artifact service digest matching all those fields; download by that artifact ID and verify the "
            "downloaded archive against that service digest before extraction. Reject a local directory, zero/multiple/"
            "expired artifact matches, another run/attempt/commit/name, a missing or mismatched service digest, or "
            "superseded run 42843125727."
        ),
        acquire=(
            "Use only the two manifest-bound target wheelhouses, universal lock, complete offline-install lock, "
            "first-party wheels, and Skill bytes already present in the exact Actions artifact. Prove the native "
            "host from trusted local facts, then select exactly one compatible target: native macOS 15 or newer on "
            "arm64 with CPython 3.11 selects `darwin-arm64-py311`; native Windows x64 with CPython 3.12 selects "
            "`win32-amd64-py312`. Reject older macOS, Linux, WSL, another Python implementation/version/architecture, "
            "zero matches, or multiple matches. "
            "Verify the selected target manifest and every listed wheel against the Candidate manifest and complete "
            "checksums before installation. Do not query or use a package index, mirror, proxy, credential, package "
            "configuration, cache, source tree, VCS checkout, sdist, editable input, or installed distribution."
        ),
        install=(
            "Using the disposable environment's absolute Python, install the complete offline-install lock from the "
            "exact verified target wheelhouse in one transaction with `--no-index --no-cache-dir --only-binary=:all: "
            "--find-links <verified-target-wheelhouse> --require-hashes --no-deps --force-reinstall`. Never accept an "
            "installed distribution as satisfying the lock and never resolve or replace any Candidate package. Then "
            "run `<absolute-disposable-environment-entrypoint>/autogenesis install --scope <user-or-project> "
            "--project-root <absolute-business-project>` as the sole owner of the Skill write; it must reject every "
            "other canonical or legacy discovery copy."
        ),
        cleanup="Candidate-only extracted, selected-scope, MCP, and cache state created by this prompt",
        package_source_required=False,
    )
    prompt = f"""Install this exact AutoGenesis Candidate for pre-release UAT, then stop before a business task.

Candidate manifest: {base_url}/{manifest_name}
Expected manifest SHA-256: {manifest_digest}
Complete checksums: {base_url}/SHA256SUMS
Candidate commit: {args.commit}
GitHub Actions repository: {REPOSITORY}
GitHub Actions workflow run: {args.workflow_run_id}
GitHub Actions workflow run attempt: {args.workflow_run_attempt}
GitHub Actions artifact ID and service digest: resolve both externally and verify the archive digest before extraction
GitHub Actions artifact: {artifact_name}

{contract}""".encode("utf-8")
    prompt_name = "candidate-install-prompt.txt"
    atomic_write(output, prompt_name, prompt)
    checksum_rows.append((hashlib.sha256(prompt).hexdigest(), prompt_name))

    checksums = "".join(
        f"{digest}  {name}\n" for digest, name in sorted(checksum_rows, key=lambda row: row[1])
    ).encode("ascii")
    atomic_write(output, "SHA256SUMS", checksums)
    wheel_count = sum(len(wheelhouse["files"]) for wheelhouse in wheelhouses)
    print(f"Built Candidate channel for {args.commit} with two exact target wheelhouses and {wheel_count} files.")


if __name__ == "__main__":
    main()
