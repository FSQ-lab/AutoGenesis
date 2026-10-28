"""Deterministically materialize manifest and pin for an intentional release.

Run with --write only while authoring a new, unreleased contract version.
The default is a read-only release consistency check.
"""

import argparse
import hashlib
import json
import runpy
from pathlib import Path

from _files import atomic_write

PACKAGE = "agent-contract/src/autogenesis_agent_contract"


def load_asset_io(repo: Path) -> dict:
    return runpy.run_path(str(repo / PACKAGE / "_asset_io.py"))


def release_bytes(repo: Path) -> tuple[bytes, bytes]:
    package = repo / PACKAGE
    layout = runpy.run_path(str(package / "_layout.py"))
    asset_io = load_asset_io(repo)
    assets = package / "assets"
    inventory = {p.relative_to(assets).as_posix() for p in assets.rglob("*") if p.is_file()}
    if inventory - {"manifest.json"} != set(layout["ASSET_PATHS"]):
        raise ValueError("Official asset inventory differs from the release layout")
    hashes = {}
    for name in sorted(layout["ASSET_PATHS"]):
        source = assets / name
        if source.is_symlink() or any(parent.is_symlink() for parent in source.parents if parent != repo):
            raise ValueError("Official release assets must not be symlinks")
        raw = asset_io["read_asset"](assets, name)
        raw.decode("utf-8")
        if b"\r" in raw or raw.startswith(b"\xef\xbb\xbf") or not raw.endswith(b"\n"):
            raise ValueError("Official release assets must be exact UTF-8/LF with a final LF")
        hashes[name] = hashlib.sha256(raw).hexdigest()
    manifest = (json.dumps({
        "schema_version": layout["SCHEMA_VERSION"],
        "contract_version": layout["CONTRACT_VERSION"],
        "assets": hashes,
    }, indent=2, sort_keys=True) + "\n").encode("utf-8")
    digest = hashlib.sha256(manifest).hexdigest()
    pin = (
        '"""Generated release pin; update only for an intentional contract release."""\n\n'
        f'MANIFEST_SHA256 = "{digest}"\n'
    ).encode("utf-8")
    return manifest, pin


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[2]
    manifest, pin = release_bytes(repo)
    outputs = {f"{PACKAGE}/assets/manifest.json": manifest, f"{PACKAGE}/_release.py": pin}
    if args.write:
        for path, content in outputs.items():
            atomic_write(repo, path, content)
        print("Materialized manifest and release pin.")
    else:
        try:
            asset_io = load_asset_io(repo)
            stored = {
                path: asset_io["read_asset"](repo, path, asset_io["MAX_MANIFEST_BYTES"])
                for path in outputs
            }
        except (OSError, ValueError):
            raise SystemExit("Release integrity error: stored outputs must be bounded regular files.") from None
        if any(stored[path] != content for path, content in outputs.items()):
            raise SystemExit("Release drift: asset bytes, manifest, and release pin must agree.")
        print("Release assets, manifest, and pin agree.")


if __name__ == "__main__":
    main()
