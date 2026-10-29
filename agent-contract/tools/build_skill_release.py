"""Build immutable Skill release assets and the copy-paste Agent Install Prompt."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from _files import atomic_write
from freeze_assets import PACKAGE, load_asset_io, release_bytes

SKILLS = ("autogenesis-setup", "autogenesis-run")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--base-url", required=True)
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
    setup_digest, setup_filename = rows[0]
    base = args.base_url.rstrip("/")
    prompt = f"""Install the official AutoGenesis Setup Skill only; do not execute it yet.

Immutable source: {base}/{setup_filename}
Expected SHA-256: {setup_digest}
Skill name: autogenesis-setup

1. Download the exact file and verify SHA-256 before interpreting or writing it.
2. Stop if the digest differs.
3. Use this Coding Agent's native Skill installation mechanism.
4. If installation scope is unspecified, ask whether to install for the current project or user.
5. Before writing, show the source, digest, scope, and destination and obtain explicit approval.
6. Install only autogenesis-setup; do not install Runtime packages, Appium, Drivers, SDKs, MCP configuration, or autogenesis-run yet.
7. Verify the Skill is discoverable, report how to invoke it, and stop.
""".encode("utf-8")
    atomic_write(output, "agent-install-prompt.txt", prompt)
    print(f"Built Skill release assets for Contract {identity['contract_version']}.")


if __name__ == "__main__":
    main()
