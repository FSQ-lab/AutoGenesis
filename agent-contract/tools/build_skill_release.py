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

1. Identify the native host from available environment metadata. If a command is required, include it in the approval plan instead of running it yet. Stop on Linux, WSL, or any host other than native macOS or Windows.
2. If installation scope is unspecified, ask whether to install for the current project or user.
3. Show the source, digest, exact commands, network access, temporary destination, scope, final destination, and how every visible autogenesis-setup installation will be checked. Obtain explicit approval before process execution, network access, or filesystem writes. Stop and request fresh approval if any plan element changes.
4. After approval, enumerate every visible autogenesis-setup installation before writing. Preserve different existing content and stop on conflict, shadowing, ambiguity, or an installation whose bytes or location cannot be inspected.
5. Download the exact file and verify SHA-256 before interpreting or installing it. Stop if the digest differs.
6. Use this Coding Agent's native Skill installation mechanism. Install only autogenesis-setup; do not install Runtime packages, Appium, Drivers, SDKs, MCP configuration, or autogenesis-run yet.
7. Hash the exact installed file after writing. Stop if its digest or declared contract version differs from the approved source.
8. Reload Skill discovery. Prove that the discovered autogenesis-setup resolves to the approved destination, digest, and contract version, with no higher-precedence or ambiguous copy. If the Coding Agent cannot prove this identity, stop instead of reporting success.
9. Report the verified source, destination, digest, contract version, scope, and how to invoke the Skill, then stop.
""".encode("utf-8")
    atomic_write(output, "agent-install-prompt.txt", prompt)
    print(f"Built Skill release assets for Contract {identity['contract_version']}.")


if __name__ == "__main__":
    main()
