"""Build immutable Skill release assets and the copy-paste Agent Install Prompt."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from _files import atomic_write
from freeze_assets import PACKAGE, load_asset_io, release_bytes

SKILLS = ("autogenesis",)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--release-manifest", type=Path, required=True)
    parser.add_argument("--release-manifest-url", required=True)
    args = parser.parse_args()
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
    checksums = "".join(f"{digest}  {filename}\n" for digest, filename in rows).encode("ascii")
    atomic_write(output, "SHA256SUMS", checksums)
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
    release_digest = hashlib.sha256(release_raw).hexdigest()
    atomic_write(output, "release-manifest.json", release_raw)
    rows.append((release_digest, "release-manifest.json"))
    checksums = "".join(f"{digest}  {filename}\n" for digest, filename in rows).encode("ascii")
    atomic_write(output, "SHA256SUMS", checksums)
    skill_digest, skill_filename = rows[0]
    base = args.base_url.rstrip("/")
    prompt = f"""Install the official AutoGenesis Skill and CLI, then stop before running a business task.

Immutable Skill source: {base}/{skill_filename}
Expected Skill SHA-256: {skill_digest}
Skill name: autogenesis
Release manifest: {args.release_manifest_url}
Expected release manifest SHA-256: {release_digest}

1. Before any network request, interpretation, approval, or write, detect the native host from local OS facts. Accept only native macOS or native Windows; reject Linux and WSL before any write.
2. Download the exact Release manifest as untrusted bytes and verify its SHA-256 before interpreting it. Require it to bind the CLI and host Runtime wheel identities.
3. Download the exact Skill as untrusted expected bytes and verify its SHA-256; do not write it yet.
4. Show authenticated sources, selected user/project scope, destination, Python/package manager/index, exact host wheel identities, writes, and rollback; obtain one approval for the complete unchanged plan.
5. Acquire only the manifest-bound host wheels through the selected package environment and verify downloaded wheel size/SHA-256 before installation.
6. Run `autogenesis install --skills-dir <selected-skill-root>` as the sole owner of the Skill write. It verifies the Runtime bundle, internal Appium workflow snapshot, Contract identity, and installed Skill bytes atomically.
7. Verify the installed Skill equals the downloaded expected bytes and exactly one `autogenesis` Skill is discovered at the selected scope. Report how to invoke it, and stop.
""".encode("utf-8")
    atomic_write(output, "agent-install-prompt.txt", prompt)
    print(f"Built Skill release assets for Contract {identity['contract_version']}.")


if __name__ == "__main__":
    main()
