"""Render a shell-free generic MCP launch descriptor from canonical server.json."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import os
from typing import Mapping


SERVER_PATHS = {
    "appium": "appium-mcp-server/server.json",
    "windows": "pywinauto-mcp-server/server.json",
}


class DescriptorError(ValueError):
    pass


def _load_server(repo: Path, server: str) -> dict:
    try:
        return json.loads((repo / SERVER_PATHS[server]).read_text(encoding="utf-8"))
    except (KeyError, OSError, UnicodeError, ValueError):
        raise DescriptorError("AutoGenesis server metadata is unavailable or invalid") from None


def _contained_file(project_root: str | Path, config: str | Path) -> tuple[Path, Path]:
    try:
        root = Path(project_root).resolve(strict=True)
        requested = Path(config)
        candidate = requested if requested.is_absolute() else root / requested
        lexical = Path(os.path.abspath(os.fspath(candidate)))
        relative = lexical.relative_to(root)
        current = root
        for part in relative.parts:
            current /= part
            if current.is_symlink():
                raise DescriptorError("Configuration symlinks are not accepted")
        source = candidate.resolve(strict=True)
        source.relative_to(root)
        if not root.is_dir() or not source.is_file():
            raise DescriptorError("Project root and configuration must already exist")
        return root, source
    except (OSError, RuntimeError, ValueError):
        raise DescriptorError("Configuration must remain inside the business project") from None


def render_descriptor(
    repo: Path,
    server: str,
    project_root: str | Path,
    config: str | Path,
    *,
    platform: str | None = None,
    app: str | None = None,
) -> dict[str, object]:
    metadata = _load_server(repo, server)
    root, source = _contained_file(project_root, config)
    packages = metadata.get("packages")
    if not isinstance(packages, list) or len(packages) != 1:
        raise DescriptorError("AutoGenesis metadata must declare exactly one package")
    package = packages[0]
    identifier = package.get("identifier")
    version = package.get("version")
    if not isinstance(identifier, str) or not isinstance(version, str):
        raise DescriptorError("AutoGenesis package identity is invalid")

    values: Mapping[str, str | None] = {
        "--platform": platform,
        "--config": str(source),
        "--app": app,
        "--project-root": str(root),
    }
    arguments = ["--from", f"{identifier}=={version}", identifier]
    for definition in package.get("packageArguments", []):
        name = definition.get("name")
        if name not in values:
            raise DescriptorError("AutoGenesis metadata contains an unsupported launch argument")
        value = values[name]
        if value is None:
            value = definition.get("default")
        if value is None:
            if definition.get("isRequired"):
                raise DescriptorError("A required launch argument has no value")
            continue
        choices = definition.get("choices")
        if choices is not None and value not in choices:
            raise DescriptorError("A launch argument is outside its declared choices")
        arguments.extend((name, value))

    return {
        "server": metadata["name"],
        "type": "stdio",
        "command": package.get("runtimeHint", "uvx"),
        "args": arguments,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server", choices=tuple(SERVER_PATHS), required=True)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--platform", choices=("ios", "android", "mac"))
    parser.add_argument("--app")
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    try:
        descriptor = render_descriptor(
            repo,
            args.server,
            args.project_root,
            args.config,
            platform=args.platform,
            app=args.app,
        )
    except DescriptorError as error:
        parser.error(str(error))
    print(json.dumps(descriptor, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
