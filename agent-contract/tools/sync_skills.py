"""Copy verified canonical Skill bytes to the two owned projections."""

import argparse
from pathlib import Path

from _files import atomic_write
from freeze_assets import PACKAGE, load_asset_io, release_bytes

SKILLS = ("autogenesis-setup", "autogenesis-run")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Fail on drift without writing")
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[2]
    package = repo / PACKAGE
    try:
        asset_io = load_asset_io(repo)
        read = asset_io["read_asset"]
        # Inspect/bound the installed manifest before computing a release. A
        # FIFO, special file, or oversized input must never reach an unbounded read.
        stored_manifest = read(package / "assets", "manifest.json", asset_io["MAX_MANIFEST_BYTES"])
        stored_pin = read(package, "_release.py", asset_io["MAX_MANIFEST_BYTES"])
        manifest, pin = release_bytes(repo)
        if stored_manifest != manifest or stored_pin != pin:
            raise ValueError("release drift")
        outputs = {
            f".github/skills/{name}/SKILL.md": read(package / "assets", f"skills/{name}/SKILL.md")
            for name in SKILLS
        }
        drift = []
        for path, raw in outputs.items():
            try:
                (repo / path).lstat()
            except FileNotFoundError:
                drift.append(path)
            else:
                if read(repo, path) != raw:
                    drift.append(path)
    except (OSError, ValueError):
        raise SystemExit("Contract integrity error: refusing unsafe or unverified Skill inputs.") from None
    if args.check and drift:
        raise SystemExit("Skill projection drift: run agent-contract/tools/sync_skills.py.")
    if not args.check:
        for path in drift:
            atomic_write(repo, path, outputs[path])
    print("Two canonical Skill projections are synchronized.")


if __name__ == "__main__":
    main()
