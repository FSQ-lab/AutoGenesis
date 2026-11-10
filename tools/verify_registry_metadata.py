"""Validate official Registry metadata, generated descriptors, and local wheels."""

from __future__ import annotations

import argparse
from email.parser import BytesParser
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import time
import tomllib
import urllib.error
import urllib.request
import zipfile

from render_mcp_descriptor import DescriptorError, render_descriptor


SCHEMA_URL = "https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json"
SCHEMA_SHA256 = "3fba09590c99f61735d234822279f4223fab9e300c0a81e81c91ab62a4114de0"
REPOSITORY = "https://github.com/FSQ-lab/AutoGenesis"
REPOSITORY_ID = "1412652894"
SERVERS = {
    "appium": {
        "path": "appium-mcp-server/server.json",
        "project": "appium-mcp-server/pyproject.toml",
        "name": "io.github.FSQ-lab/autogenesis-appium",
        "package": "autogenesis-appium-mcp",
        "entrypoint": "autogenesis-appium-mcp = autogenesis_appium_mcp.server:main",
        "arguments": {"--platform", "--config", "--project-root"},
    },
    "windows": {
        "path": "pywinauto-mcp-server/server.json",
        "project": "pywinauto-mcp-server/pyproject.toml",
        "name": "io.github.FSQ-lab/autogenesis-windows",
        "package": "autogenesis-windows-mcp",
        "entrypoint": "autogenesis-windows-mcp = autogenesis_windows_mcp.cli:main",
        "arguments": {"--config", "--app", "--project-root"},
    },
}

CLI_PROJECT = "autogenesis-cli/pyproject.toml"
CLI_ENTRYPOINT = "autogenesis = autogenesis_cli.cli:main"
RELEASE_MANIFEST_SCHEMA = 1
RELEASE_PROVENANCE_KEYS = {
    "repository",
    "workflow_ref",
    "ref",
    "commit",
    "run_id",
    "run_attempt",
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
    from jsonschema import Draft7Validator, FormatChecker

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
    from jsonschema import Draft202012Validator, FormatChecker

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


def _verify_cli_wheel(repo: Path, wheel_dir: Path) -> None:
    project = tomllib.loads((repo / CLI_PROJECT).read_text(encoding="utf-8"))["project"]
    wheel_name = project["name"].replace("-", "_")
    wheels = sorted(wheel_dir.glob(f"{wheel_name}-{project['version']}-*.whl"))
    if len(wheels) != 1:
        raise VerificationError("Expected one local AutoGenesis CLI wheel")
    name, version, entrypoints, requirements, project_urls, _ = _wheel_metadata(wheels[0])
    if name != project["name"] or version != project["version"]:
        raise VerificationError("Built AutoGenesis CLI identity differs from its project")
    if CLI_ENTRYPOINT not in entrypoints:
        raise VerificationError("Built AutoGenesis CLI entrypoint is unavailable")
    normalized = requirements.replace(" ", "").lower()
    for requirement in (
        "autogenesis-agent-contract==2.1.0",
        "autogenesis-appium-mcp==0.5.0;sys_platform==\"darwin\"orsys_platform==\"win32\"",
        "autogenesis-windows-mcp==0.5.0;sys_platform==\"win32\"",
    ):
        if requirement not in normalized:
            raise VerificationError("AutoGenesis CLI host bundle dependencies drifted")
    if f"Repository, {REPOSITORY}" not in project_urls:
        raise VerificationError("AutoGenesis CLI wheel lacks repository ownership metadata")


def _release_projects(repo: Path, metadata: dict[str, dict]) -> list[tuple[str, str]]:
    contract = tomllib.loads((repo / "agent-contract/pyproject.toml").read_text(encoding="utf-8"))["project"]
    cli = tomllib.loads((repo / CLI_PROJECT).read_text(encoding="utf-8"))["project"]
    projects = [(contract["name"], contract["version"]), (cli["name"], cli["version"])]
    projects.extend(
        (document["packages"][0]["identifier"], document["packages"][0]["version"])
        for document in metadata.values()
    )
    return projects


def _normalized_package(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _release_wheel_records(repo: Path, wheel_dir: Path, metadata: dict[str, dict]) -> list[dict]:
    expected = {(_normalized_package(name), version) for name, version in _release_projects(repo, metadata)}
    records = []
    identities = set()
    for wheel in sorted(wheel_dir.glob("*.whl")):
        package, version, *_ = _wheel_metadata(wheel)
        identity = (_normalized_package(package), version)
        if identity not in expected:
            raise VerificationError("Release wheel directory contains an unexpected distribution")
        if identity in identities:
            raise VerificationError("Release wheel directory contains duplicate package versions")
        identities.add(identity)
        raw = wheel.read_bytes()
        records.append(
            {
                "filename": wheel.name,
                "sha256": hashlib.sha256(raw).hexdigest(),
                "size": len(raw),
                "package": package,
                "version": version,
            }
        )
    if identities != expected:
        raise VerificationError("Release wheel directory does not contain the complete release set")
    return records


def _github_provenance() -> dict[str, str]:
    environment = {
        "repository": "GITHUB_REPOSITORY",
        "workflow_ref": "GITHUB_WORKFLOW_REF",
        "ref": "GITHUB_REF",
        "commit": "GITHUB_SHA",
        "run_id": "GITHUB_RUN_ID",
        "run_attempt": "GITHUB_RUN_ATTEMPT",
    }
    provenance = {key: os.environ.get(variable, "") for key, variable in environment.items()}
    if any(not value for value in provenance.values()):
        raise VerificationError("GitHub workflow provenance is incomplete")
    if provenance["repository"] != "FSQ-lab/AutoGenesis":
        raise VerificationError("Release provenance repository is not canonical")
    if not re.fullmatch(r"[0-9a-f]{40}", provenance["commit"]):
        raise VerificationError("Release provenance commit is invalid")
    if not provenance["run_id"].isdigit() or not provenance["run_attempt"].isdigit():
        raise VerificationError("Release provenance run identity is invalid")
    return provenance


def _validate_release_manifest(document: dict) -> None:
    if set(document) != {"schema_version", "provenance", "wheels"}:
        raise VerificationError("Release manifest has unexpected fields")
    if document["schema_version"] != RELEASE_MANIFEST_SCHEMA:
        raise VerificationError("Release manifest schema is unsupported")
    provenance = document["provenance"]
    if not isinstance(provenance, dict) or set(provenance) != RELEASE_PROVENANCE_KEYS:
        raise VerificationError("Release manifest provenance is invalid")
    if any(not isinstance(value, str) or not value for value in provenance.values()):
        raise VerificationError("Release manifest provenance is incomplete")
    wheels = document["wheels"]
    if not isinstance(wheels, list) or not wheels:
        raise VerificationError("Release manifest wheel set is empty")
    filenames = set()
    identities = set()
    for wheel in wheels:
        if not isinstance(wheel, dict) or set(wheel) != {"filename", "sha256", "size", "package", "version"}:
            raise VerificationError("Release manifest wheel entry is invalid")
        filename = wheel["filename"]
        if (
            not isinstance(filename, str)
            or Path(filename).name != filename
            or not filename.endswith(".whl")
            or not isinstance(wheel["sha256"], str)
            or re.fullmatch(r"[0-9a-f]{64}", wheel["sha256"]) is None
            or not isinstance(wheel["size"], int)
            or isinstance(wheel["size"], bool)
            or wheel["size"] <= 0
            or not isinstance(wheel["package"], str)
            or not wheel["package"]
            or not isinstance(wheel["version"], str)
            or not wheel["version"]
        ):
            raise VerificationError("Release manifest wheel entry is invalid")
        identity = (_normalized_package(wheel["package"]), wheel["version"])
        if filename in filenames or identity in identities:
            raise VerificationError("Release manifest contains duplicate wheels")
        filenames.add(filename)
        identities.add(identity)


def _write_release_manifest(path: Path, records: list[dict], provenance: dict[str, str]) -> None:
    document = {"schema_version": RELEASE_MANIFEST_SCHEMA, "provenance": provenance, "wheels": records}
    _validate_release_manifest(document)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.tmp")
    temporary.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def _load_release_manifest(path: Path, expected_provenance: dict[str, str] | None = None) -> dict:
    document = _read_json(path)
    _validate_release_manifest(document)
    if expected_provenance is not None and document["provenance"] != expected_provenance:
        raise VerificationError("Release manifest provenance differs from the current workflow run")
    return document


def _verify_manifest_wheels(wheel_dir: Path, manifest: dict) -> None:
    expected = {wheel["filename"]: wheel for wheel in manifest["wheels"]}
    wheels = sorted(wheel_dir.glob("*.whl"))
    if not wheels:
        raise VerificationError("No release wheels were downloaded")
    for wheel in wheels:
        record = expected.get(wheel.name)
        if record is None:
            raise VerificationError("Downloaded wheel is absent from the release manifest")
        raw = wheel.read_bytes()
        if len(raw) != record["size"] or hashlib.sha256(raw).hexdigest() != record["sha256"]:
            raise VerificationError("Downloaded wheel bytes differ from the reviewed release manifest")


def _pypi_version(identifier: str, version: str, opener=urllib.request.urlopen) -> dict | None:
    url = f"https://pypi.org/pypi/{identifier}/{version}/json"
    try:
        raw = opener(url, timeout=30).read()
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return None
        raise VerificationError("PyPI release metadata could not be retrieved") from None
    except (OSError, urllib.error.URLError):
        raise VerificationError("PyPI release metadata could not be retrieved") from None
    try:
        response = json.loads(raw)
    except (UnicodeError, ValueError):
        raise VerificationError("PyPI returned invalid release metadata") from None
    if not isinstance(response, dict):
        raise VerificationError("PyPI returned invalid release metadata")
    return response


def _release_packages(manifest: dict) -> dict[tuple[str, str], list[dict]]:
    packages: dict[tuple[str, str], list[dict]] = {}
    for wheel in manifest["wheels"]:
        packages.setdefault((wheel["package"], wheel["version"]), []).append(wheel)
    return packages


def _verify_pypi_response(package: str, version: str, records: list[dict], response: dict) -> None:
    info = response.get("info")
    urls = response.get("urls")
    if (
        not isinstance(info, dict)
        or _normalized_package(str(info.get("name", ""))) != _normalized_package(package)
        or info.get("version") != version
        or not isinstance(urls, list)
    ):
        raise VerificationError("Published PyPI package identity differs from the release manifest")
    actual = {}
    for item in urls:
        if not isinstance(item, dict) or not isinstance(item.get("digests"), dict):
            raise VerificationError("Published PyPI file metadata is invalid")
        filename = item.get("filename")
        digest = item["digests"].get("sha256")
        size = item.get("size")
        if (
            not isinstance(filename, str)
            or filename in actual
            or item.get("packagetype") != "bdist_wheel"
            or not isinstance(digest, str)
            or re.fullmatch(r"[0-9a-f]{64}", digest) is None
            or not isinstance(size, int)
            or isinstance(size, bool)
        ):
            raise VerificationError("Published PyPI file metadata is invalid")
        actual[filename] = (digest, size)
    expected = {record["filename"]: (record["sha256"], record["size"]) for record in records}
    if actual.keys() != expected.keys():
        raise VerificationError(f"Published PyPI wheel filename set differs for {package}=={version}")
    if actual != expected:
        raise VerificationError(f"Published PyPI wheel bytes differ for {package}=={version}")


def _preflight_pypi_release(manifest: dict, opener=urllib.request.urlopen) -> None:
    for (package, version), records in _release_packages(manifest).items():
        response = _pypi_version(package, version, opener)
        if response is None:
            continue
        try:
            _verify_pypi_response(package, version, records, response)
        except VerificationError:
            raise VerificationError(
                f"PyPI release collision ({package}=={version}); existing bytes differ, bump the complete release version set"
            ) from None


def _verify_pypi_release(manifest: dict, opener=urllib.request.urlopen) -> None:
    for (package, version), records in _release_packages(manifest).items():
        response = _pypi_version(package, version, opener)
        if response is None:
            raise VerificationError(f"Published PyPI release is unavailable: {package}=={version}")
        _verify_pypi_response(package, version, records, response)


def _verify_pypi_release_with_retries(manifest: dict, attempts: int, delay_seconds: float) -> None:
    for attempt in range(1, attempts + 1):
        try:
            _verify_pypi_release(manifest)
            return
        except VerificationError:
            if attempt == attempts:
                raise
            time.sleep(delay_seconds)

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheel-dir", type=Path)
    parser.add_argument("--evidence-dir", type=Path)
    parser.add_argument("--write-release-manifest", type=Path)
    parser.add_argument("--release-manifest", type=Path)
    release_mode = parser.add_mutually_exclusive_group()
    release_mode.add_argument("--preflight-pypi-release", action="store_true")
    release_mode.add_argument("--verify-manifest-wheels", action="store_true")
    release_mode.add_argument("--verify-pypi-release", action="store_true")
    parser.add_argument("--pypi-attempts", type=int, default=1)
    parser.add_argument("--pypi-delay-seconds", type=float, default=0)
    args = parser.parse_args()
    selected_release_mode = args.preflight_pypi_release or args.verify_manifest_wheels or args.verify_pypi_release
    if selected_release_mode:
        if args.release_manifest is None:
            parser.error("release verification modes require --release-manifest")
        if args.pypi_attempts < 1 or args.pypi_delay_seconds < 0:
            parser.error("PyPI retry values must be non-negative and attempts must be positive")
        manifest = _load_release_manifest(args.release_manifest.resolve(strict=True), _github_provenance())
        if args.preflight_pypi_release:
            _preflight_pypi_release(manifest)
        elif args.verify_manifest_wheels:
            if args.wheel_dir is None:
                parser.error("--verify-manifest-wheels requires --wheel-dir")
            _verify_manifest_wheels(args.wheel_dir.resolve(strict=True), manifest)
        else:
            _verify_pypi_release_with_retries(manifest, args.pypi_attempts, args.pypi_delay_seconds)
        print("Release manifest and public package bytes agree.")
        return
    if args.release_manifest is not None:
        parser.error("--release-manifest requires a release verification mode")
    if args.pypi_attempts != 1 or args.pypi_delay_seconds != 0:
        parser.error("PyPI retry options require --verify-pypi-release")

    repo = Path(__file__).resolve().parents[1]
    metadata = _metadata(repo, _official_schema())
    descriptors = _verify_descriptors(repo, metadata)
    wheel_dir = args.wheel_dir.resolve(strict=True) if args.wheel_dir is not None else None
    if wheel_dir is not None:
        _verify_wheels(wheel_dir, metadata)
        _verify_cli_wheel(repo, wheel_dir)
    if args.write_release_manifest is not None:
        if wheel_dir is None:
            parser.error("--write-release-manifest requires --wheel-dir")
        _write_release_manifest(
            args.write_release_manifest.resolve(),
            _release_wheel_records(repo, wheel_dir, metadata),
            _github_provenance(),
        )
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
            "local_wheels_verified": wheel_dir is not None,
            "release_manifest_written": args.write_release_manifest is not None,
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
