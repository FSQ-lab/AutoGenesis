"""Validate official Registry metadata, generated descriptors, and local wheels."""

from __future__ import annotations

import argparse
from email.parser import BytesParser
import hashlib
import json
from pathlib import Path
import tempfile
import tomllib
import urllib.error
import urllib.request
import zipfile

from jsonschema import Draft7Validator, Draft202012Validator, FormatChecker

from render_mcp_descriptor import DescriptorError, render_descriptor


SCHEMA_URL = "https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json"
SCHEMA_SHA256 = "3fba09590c99f61735d234822279f4223fab9e300c0a81e81c91ab62a4114de0"
REPOSITORY = "https://github.com/FSQ-lab/AutoGenesis"
REPOSITORY_ID = "1412652894"
SERVERS = {
    "appium": {
        "path": "appium-mcp-server/server.json",
        "project": "appium-mcp-server/pyproject.toml",
        "name": "io.github.fsq-lab/autogenesis-appium",
        "package": "autogenesis-appium-mcp",
        "entrypoint": "autogenesis-appium-mcp = autogenesis_appium_mcp.server:main",
        "arguments": {"--platform", "--config", "--project-root"},
    },
    "windows": {
        "path": "pywinauto-mcp-server/server.json",
        "project": "pywinauto-mcp-server/pyproject.toml",
        "name": "io.github.fsq-lab/autogenesis-windows",
        "package": "autogenesis-windows-mcp",
        "entrypoint": "autogenesis-windows-mcp = autogenesis_windows_mcp.cli:main",
        "arguments": {"--config", "--app", "--project-root"},
    },
}


class VerificationError(ValueError):
    pass


def _read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        raise VerificationError(f"Invalid JSON: {path.relative_to(path.parents[1])}") from None
    if not isinstance(value, dict):
        raise VerificationError("Metadata roots must be JSON objects")
    return value


def _official_schema() -> dict:
    try:
        raw = urllib.request.urlopen(SCHEMA_URL, timeout=30).read()
    except (OSError, urllib.error.URLError):
        raise VerificationError("Official MCP Registry schema could not be downloaded") from None
    if hashlib.sha256(raw).hexdigest() != SCHEMA_SHA256:
        raise VerificationError("Official MCP Registry schema digest changed")
    return json.loads(raw)


def _metadata(repo: Path, schema: dict) -> dict[str, dict]:
    validated = {}
    for key, expected in SERVERS.items():
        document = _read_json(repo / expected["path"])
        errors = sorted(
            Draft7Validator(schema, format_checker=FormatChecker()).iter_errors(document),
            key=lambda error: tuple(str(item) for item in error.path),
        )
        if errors:
            raise VerificationError(f"{expected['path']}: {errors[0].message}")
        project_path = repo / expected["project"]
        project = tomllib.loads(project_path.read_text(encoding="utf-8"))["project"]
        readme = project.get("readme")
        if not isinstance(readme, str):
            raise VerificationError("Registry package must declare a PyPI README")
        try:
            description = (project_path.parent / readme).read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            raise VerificationError("Registry package README is unavailable") from None
        if f"mcp-name: {document['name']}" not in description:
            raise VerificationError("PyPI README does not prove MCP Registry package ownership")
        package = document["packages"][0]
        repository = document.get("repository", {})
        if document["$schema"] != SCHEMA_URL or document["name"] != expected["name"]:
            raise VerificationError("Registry schema URI or server name drifted")
        if document["version"] != project["version"] or package.get("version") != project["version"]:
            raise VerificationError("Server, package, and Python project versions must match")
        if package.get("identifier") != project["name"] or package["identifier"] != expected["package"]:
            raise VerificationError("Registry package identifier must match the Python distribution")
        if package.get("registryType") != "pypi" or package.get("registryBaseUrl") != "https://pypi.org":
            raise VerificationError("Official metadata must use the public PyPI registry")
        if package.get("runtimeHint") != "uvx" or package.get("transport") != {"type": "stdio"}:
            raise VerificationError("AutoGenesis Registry packages must launch through uvx over stdio")
        if document.get("remotes"):
            raise VerificationError("AutoGenesis Registry metadata must not expose a remote transport")
        if repository != {
            "url": REPOSITORY,
            "source": "github",
            "id": REPOSITORY_ID,
            "subfolder": expected["path"].rsplit("/", 1)[0],
        }:
            raise VerificationError("Repository provenance metadata drifted")
        if project.get("urls", {}).get("Repository") != REPOSITORY:
            raise VerificationError("Python package ownership metadata must link the repository")
        definitions = package.get("packageArguments", [])
        if {item.get("name") for item in definitions} != expected["arguments"]:
            raise VerificationError("Registry launch arguments drifted from the runtime interface")
        if any("value" in item for item in package.get("environmentVariables", [])):
            raise VerificationError("Registry environment metadata must never contain values")
        validated[key] = document
    return validated


def _verify_descriptors(repo: Path, metadata: dict[str, dict]) -> dict[str, dict]:
    launch_schema = _read_json(repo / "registry/generic-launch.schema.json")
    validator = Draft202012Validator(launch_schema, format_checker=FormatChecker())
    with tempfile.TemporaryDirectory(prefix="autogenesis-registry-") as temporary:
        root = Path(temporary).resolve()
        config = root / "config.json"
        config.write_text("{}\n", encoding="utf-8")
        descriptors = {
            "appium": render_descriptor(repo, "appium", root, config, platform="android"),
            "windows": render_descriptor(repo, "windows", root, config, app="notepad"),
        }
        for key, descriptor in descriptors.items():
            validator.validate(descriptor)
            package = metadata[key]["packages"][0]
            expected = f"{package['identifier']}=={package['version']}"
            if descriptor["args"][:3] != ["--from", expected, package["identifier"]]:
                raise VerificationError("Generic descriptor package identity drifted from server.json")
            if descriptor["args"].count("--project-root") != 1 or descriptor["args"].count("--config") != 1:
                raise VerificationError("Generic descriptor omitted its scoped project inputs")
        outside = root.parent / f"{root.name}-outside.json"
        outside.write_text("{}\n", encoding="utf-8")
        try:
            try:
                render_descriptor(repo, "appium", root, outside, platform="ios")
            except DescriptorError:
                pass
            else:
                raise VerificationError("Descriptor accepted a configuration outside the project")
            try:
                render_descriptor(repo, "appium", root, config, platform="browser")
            except DescriptorError:
                pass
            else:
                raise VerificationError("Descriptor accepted an undeclared platform")
            link = root / "linked-config.json"
            try:
                link.symlink_to(config)
            except OSError:
                link = None
            if link is not None:
                try:
                    render_descriptor(repo, "windows", root, link)
                except DescriptorError:
                    pass
                else:
                    raise VerificationError("Descriptor accepted a symlink configuration")
        finally:
            outside.unlink(missing_ok=True)
        return descriptors


def _wheel_metadata(wheel: Path) -> tuple[str, str, str, str, tuple[str, ...], str]:
    with zipfile.ZipFile(wheel) as archive:
        metadata_name = next(name for name in archive.namelist() if name.endswith(".dist-info/METADATA"))
        entry_name = next((name for name in archive.namelist() if name.endswith(".dist-info/entry_points.txt")), None)
        parsed = BytesParser().parsebytes(archive.read(metadata_name))
        return (
            parsed["Name"],
            parsed["Version"],
            "" if entry_name is None else archive.read(entry_name).decode("utf-8"),
            "\n".join(parsed.get_all("Requires-Dist", [])),
            tuple(parsed.get_all("Project-URL", [])),
            parsed.get_payload(),
        )


def _verify_wheels(wheel_dir: Path, metadata: dict[str, dict]) -> None:
    contract_project = tomllib.loads((Path(__file__).resolve().parents[1] / "agent-contract/pyproject.toml").read_text())["project"]
    contract_version = contract_project["version"]
    contract_wheels = sorted(wheel_dir.glob(f"autogenesis_agent_contract-{contract_version}-*.whl"))
    if len(contract_wheels) != 1:
        raise VerificationError("Expected one local Agent Contract wheel")
    contract_name, built_contract_version, _, _, contract_urls, _ = _wheel_metadata(contract_wheels[0])
    if contract_name != contract_project["name"] or built_contract_version != contract_version:
        raise VerificationError("Built Agent Contract identity differs from its Python project")
    if f"Repository, {REPOSITORY}" not in contract_urls:
        raise VerificationError("Agent Contract wheel does not contain Registry ownership metadata")
    for key, expected in SERVERS.items():
        package = metadata[key]["packages"][0]
        wheel_name = package["identifier"].replace("-", "_")
        wheels = sorted(wheel_dir.glob(f"{wheel_name}-{package['version']}-*.whl"))
        if len(wheels) != 1:
            raise VerificationError(f"Expected one local wheel for {package['identifier']}")
        name, version, entrypoints, requirements, project_urls, description = _wheel_metadata(wheels[0])
        if name != package["identifier"] or version != package["version"]:
            raise VerificationError("Built wheel identity differs from server.json")
        if expected["entrypoint"] not in entrypoints:
            raise VerificationError("Built wheel entrypoint differs from server.json")
        if f"autogenesis-agent-contract=={contract_version}" not in requirements.replace(" ", ""):
            raise VerificationError("Runtime wheel does not pin the current Agent Contract")
        if f"Repository, {REPOSITORY}" not in project_urls:
            raise VerificationError("Built wheel does not contain Registry ownership metadata")
        if f"mcp-name: {metadata[key]['name']}" not in description:
            raise VerificationError("Built wheel lacks its MCP Registry ownership token")


def _verify_pypi(repo: Path, metadata: dict[str, dict]) -> None:
    contract = tomllib.loads((repo / "agent-contract/pyproject.toml").read_text(encoding="utf-8"))["project"]
    packages = [(contract["name"], contract["version"])]
    packages.extend(
        (document["packages"][0]["identifier"], document["packages"][0]["version"])
        for document in metadata.values()
    )
    for identifier, version in packages:
        url = f"https://pypi.org/pypi/{identifier}/{version}/json"
        try:
            response = json.loads(urllib.request.urlopen(url, timeout=30).read())
        except (OSError, urllib.error.URLError, ValueError):
            raise VerificationError(f"Published PyPI package is unavailable: {identifier}=={version}") from None
        if response.get("info", {}).get("version") != version:
            raise VerificationError("Published PyPI package version differs from local metadata")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheel-dir", type=Path)
    parser.add_argument("--evidence-dir", type=Path)
    parser.add_argument("--check-pypi", action="store_true")
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    metadata = _metadata(repo, _official_schema())
    descriptors = _verify_descriptors(repo, metadata)
    if args.wheel_dir is not None:
        _verify_wheels(args.wheel_dir.resolve(strict=True), metadata)
    if args.check_pypi:
        _verify_pypi(repo, metadata)
    if args.evidence_dir is not None:
        evidence = args.evidence_dir.resolve()
        evidence.mkdir(parents=True, exist_ok=True)
        summary = {
            "schema": {"url": SCHEMA_URL, "sha256": SCHEMA_SHA256},
            "servers": {
                key: {
                    "name": document["name"],
                    "version": document["version"],
                    "transport": document["packages"][0]["transport"]["type"],
                }
                for key, document in metadata.items()
            },
            "descriptors": descriptors,
            "local_wheels_verified": args.wheel_dir is not None,
            "pypi_verified": args.check_pypi,
        }
        temporary = evidence / "registry-verification.json.tmp"
        temporary.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        temporary.replace(evidence / "registry-verification.json")
    print("Registry metadata, generic descriptors, and package identities agree.")


if __name__ == "__main__":
    try:
        main()
    except VerificationError as error:
        raise SystemExit(str(error)) from None
