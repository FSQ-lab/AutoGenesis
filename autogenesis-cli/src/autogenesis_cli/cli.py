"""Install canonical AutoGenesis Skills after package dependencies are resolved."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from importlib import metadata, resources
from pathlib import Path

from autogenesis_agent_contract import load_contract

SKILLS = ("autogenesis-setup", "autogenesis-run")
EXPECTED = {
    "autogenesis-agent-contract": "2.0.0",
    "autogenesis-appium-mcp": "0.4.0",
    "autogenesis-windows-mcp": "0.4.0",
}


class InstallError(RuntimeError):
    pass


def _host_packages() -> tuple[str, ...]:
    if sys.platform == "darwin":
        return ("autogenesis-agent-contract", "autogenesis-appium-mcp")
    if sys.platform == "win32":
        return (
            "autogenesis-agent-contract",
            "autogenesis-appium-mcp",
            "autogenesis-windows-mcp",
        )
    raise InstallError("AUTOGENESIS_PLATFORM_UNSUPPORTED: native macOS or Windows is required")


def _verify_packages(names: tuple[str, ...]) -> dict[str, str]:
    versions = {}
    for name in names:
        try:
            actual = metadata.version(name)
        except metadata.PackageNotFoundError:
            raise InstallError(f"AUTOGENESIS_PACKAGE_MISSING: {name}") from None
        if actual != EXPECTED[name]:
            raise InstallError(f"AUTOGENESIS_PACKAGE_MISMATCH: {name}")
        versions[name] = actual
    contract = load_contract()
    if contract.identity.contract_version != EXPECTED["autogenesis-agent-contract"]:
        raise InstallError("AUTOGENESIS_CONTRACT_MISMATCH")
    return versions


def _canonical_skill(name: str) -> bytes:
    raw = resources.files("autogenesis_agent_contract").joinpath(
        f"assets/skills/{name}/SKILL.md"
    ).read_bytes()
    if not raw.endswith(b"\n") or b"\r" in raw:
        raise InstallError("AUTOGENESIS_SKILL_INTEGRITY_ERROR")
    return raw


def _validate_ancestors(path: Path) -> None:
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        try:
            current.lstat()
        except FileNotFoundError:
            return
        if current.is_symlink() or not current.is_dir():
            raise InstallError("AUTOGENESIS_SKILL_DESTINATION_UNSAFE")


def _ensure_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    _validate_ancestors(path)


def _preflight(destination: Path, raw: bytes) -> str:
    _validate_ancestors(destination.parent)
    if not destination.exists():
        return "pending"
    if destination.is_symlink() or not destination.is_file():
        raise InstallError("AUTOGENESIS_SKILL_DESTINATION_UNSAFE")
    if destination.read_bytes() == raw:
        return "unchanged"
    raise InstallError("AUTOGENESIS_SKILL_CONFLICT: existing Skill differs")


def _atomic_install(destination: Path, raw: bytes) -> None:
    _ensure_directory(destination.parent)
    descriptor, temporary = tempfile.mkstemp(prefix=".autogenesis-skill-", dir=destination.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
    finally:
        Path(temporary).unlink(missing_ok=True)
    if hashlib.sha256(destination.read_bytes()).digest() != hashlib.sha256(raw).digest():
        raise InstallError("AUTOGENESIS_SKILL_INTEGRITY_ERROR")


def install(skills_dir: Path) -> dict:
    if not skills_dir.is_absolute():
        raise InstallError("AUTOGENESIS_SKILL_DESTINATION_NOT_ABSOLUTE")
    skills_dir = skills_dir.resolve(strict=False)
    packages = _verify_packages(_host_packages())
    plan = []
    for name in SKILLS:
        raw = _canonical_skill(name)
        destination = skills_dir / name / "SKILL.md"
        plan.append((name, destination, raw, _preflight(destination, raw)))
    created = []
    try:
        for _, destination, raw, status in plan:
            if status == "pending":
                _atomic_install(destination, raw)
                created.append(destination)
    except Exception:
        for destination in reversed(created):
            destination.unlink(missing_ok=True)
            try:
                destination.parent.rmdir()
            except OSError:
                pass
        raise
    installed = {
        name: {
            "status": "installed" if status == "pending" else status,
            "path": str(destination),
            "sha256": hashlib.sha256(raw).hexdigest(),
        }
        for name, destination, raw, status in plan
    }
    return {"status": "ready", "platform": sys.platform, "packages": packages, "skills": installed}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="autogenesis")
    subparsers = parser.add_subparsers(dest="command", required=True)
    command = subparsers.add_parser("install", help="install the host bundle's canonical Skills")
    command.add_argument(
        "--skills-dir",
        type=Path,
        default=Path.home() / ".agents" / "skills",
        help="absolute Skill root (default: ~/.agents/skills)",
    )
    command.add_argument("--json", action="store_true", help="emit machine-readable result")
    args = parser.parse_args(argv)
    try:
        result = install(args.skills_dir.expanduser())
    except (InstallError, OSError, ValueError) as error:
        message = str(error) if isinstance(error, InstallError) else "AUTOGENESIS_INSTALL_FAILED"
        if getattr(args, "json", False):
            print(json.dumps({"status": "error", "error": message}, sort_keys=True))
        else:
            print(message, file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(result, sort_keys=True))
    else:
        print("AutoGenesis machine installation is ready.")
        for name, detail in result["skills"].items():
            print(f"{name}: {detail['status']} ({detail['path']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
