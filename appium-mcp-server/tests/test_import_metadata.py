"""Derive direct dependency evidence from installed Python code, not source paths."""

import ast
import importlib
from importlib import metadata
import json
import os
from pathlib import Path
import re
import sys

IMPORT_DISTRIBUTIONS = {
    "anyio": "anyio", "appium": "appium-python-client",
    "autogenesis_agent_contract": "autogenesis-agent-contract", "dotenv": "python-dotenv",
    "langchain_anthropic": "langchain-anthropic", "langchain_core": "langchain-core",
    "langchain_google_genai": "langchain-google-genai", "langchain_openai": "langchain-openai",
    "mcp": "mcp", "PIL": "pillow", "pydantic": "pydantic", "requests": "requests",
    "selenium": "selenium", "watchdog": "watchdog",
}


def imported_roots(source):
    roots = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".", 1)[0])
    return roots


def test_installed_ast_imports_match_direct_metadata_and_replay_requirement():
    distribution = metadata.distribution("autogenesis-appium-mcp")
    imports = set()
    modules = []
    for entry in distribution.files:
        if entry.parts[0] == "autogenesis_appium_mcp" and entry.suffix == ".py":
            installed = Path(distribution.locate_file(entry)).resolve()
            assert installed.is_relative_to(Path(sys.prefix).resolve())
            imports.update(imported_roots(installed.read_text(encoding="utf-8")))
            module = ".".join(entry.with_suffix("").parts)
            modules.append(module.removesuffix(".__init__"))
    external = imports - sys.stdlib_module_names - {"autogenesis_appium_mcp", "__future__"}
    assert external == set(IMPORT_DISTRIBUTIONS)
    declared = set()
    for requirement in distribution.requires:
        if not re.search(r"\bextra\s*==", requirement):
            name = re.match(r"[A-Za-z0-9][A-Za-z0-9_.-]*", requirement).group()
            declared.add(re.sub(r"[-_.]+", "-", name.lower()))
    assert declared == set(IMPORT_DISTRIBUTIONS.values()) | {"behave"}
    for module in sorted(set(modules)):
        importlib.import_module(module)
    from autogenesis_appium_mcp.utils.gen_code import HEADER_AUTO_GEN
    assert "behave" in imported_roots(HEADER_AUTO_GEN)
    assert metadata.version("behave") == "1.2.6"
    destination = os.environ.get("AUTOGENESIS_APPIUM_EVIDENCE_DIR")
    if destination:
        root = Path(destination).resolve(strict=True)
        temporary = root / "imports-and-metadata.json.tmp"
        temporary.write_text(json.dumps({
            "installed_package_ast_imports": sorted(external),
            "import_distributions": IMPORT_DISTRIBUTIONS,
            "direct_dependencies": sorted(declared), "replay_requirement": "behave==1.2.6",
            "all_packaged_modules_imported": True,
        }, indent=2) + "\n", encoding="utf-8")
        temporary.replace(root / "imports-and-metadata.json")
