"""Metadata/import checks are the only checks selected on non-Windows CI."""

import importlib
import json
import os
import zipfile
from importlib.metadata import distribution
from importlib.resources import files
from pathlib import Path

import pytest
from packaging.requirements import Requirement


def test_distribution_entrypoint_and_exact_contract_dependency():
    dist = distribution("autogenesis-windows-mcp")
    assert dist.metadata["Name"] == "autogenesis-windows-mcp"
    requirements = [Requirement(item) for item in dist.requires]
    contract = [item for item in requirements if item.name == "autogenesis-agent-contract"]
    assert len(contract) == 1
    assert str(contract[0].specifier) == "==1.2.0"
    console = [item for item in dist.entry_points if item.group == "console_scripts"]
    assert [(item.name, item.value) for item in console] == [
        ("autogenesis-windows-mcp", "autogenesis_windows_mcp.cli:main"),
    ]
    import inspect
    assert not inspect.iscoroutinefunction(console[0].load())


def test_imports_and_configuration_assets_are_self_contained():
    for module in ("", ".cli", ".config", ".server", ".safe_output", ".llm.chat", ".utils.gen_code"):
        importlib.import_module("autogenesis_windows_mcp" + module)
    package = files("autogenesis_windows_mcp")
    schema = json.loads(package.joinpath("conf/config.schema.json").read_text(encoding="utf-8"))
    template = json.loads(package.joinpath("conf/pywinauto_conf.json").read_text(encoding="utf-8"))
    assert schema["properties"]["PYWINAUTO_CONFIG"]["required"] == ["apps_config"]
    assert list(template["PYWINAUTO_CONFIG"]["apps_config"]) == ["notepad"]


def test_built_wheel_contains_every_runtime_module_and_only_public_templates():
    wheel_dir = os.environ.get("AUTOGENESIS_WHEEL_DIR")
    if not wheel_dir:
        pytest.skip("Set AUTOGENESIS_WHEEL_DIR to inspect built artifacts.")
    wheels = list(Path(wheel_dir).glob("autogenesis_windows_mcp-0.3.0-*.whl"))
    assert len(wheels) == 1
    with zipfile.ZipFile(wheels[0]) as wheel:
        names = set(wheel.namelist())
        required = {
            "__init__.py", "__main__.py", "cli.py", "server.py", "config.py", "safe_output.py", "app_session.py",
            "tools/__init__.py", "tools/common_tool.py", "tools/mouse_tool.py", "tools/verify_tool.py", "tools/gen_code_tool.py",
            "utils/__init__.py", "utils/logger.py", "utils/response_format.py", "utils/element_util.py", "utils/gen_code.py",
            "llm/__init__.py", "llm/chat.py", "llm/prompt.py", "conf/config.schema.json", "conf/pywinauto_conf.json",
        }
        assert {"autogenesis_windows_mcp/" + name for name in required}.issubset(names)
        assert not any(name.startswith(("tests/", "logs/", "conf/", "agent-contract/")) or name.endswith((".env", "simple_server.py")) for name in names)
        configs = {name for name in names if name.endswith(".json")}
        assert configs == {"autogenesis_windows_mcp/conf/config.schema.json", "autogenesis_windows_mcp/conf/pywinauto_conf.json"}


def test_unused_dependency_removal_has_import_evidence():
    # These imports were absent from the old runtime, or unused provider/type
    # imports removed in this change. Behave remains for emitted replay code.
    import ast
    dist = distribution("autogenesis-windows-mcp")
    dependencies = {Requirement(item).name for item in dist.requires}
    removed = {"janus", "playwright", "langchain", "langchain-anthropic", "langchain-google-genai", "google-generativeai", "anthropic", "openai", "pyautogui", "applicationinsights"}
    assert dependencies.isdisjoint(removed)
    imports = set()
    for entry in dist.files:
        if str(entry).startswith("autogenesis_windows_mcp/") and str(entry).endswith(".py"):
            tree = ast.parse(dist.locate_file(entry).read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imports.update(item.name.split(".")[0] for item in node.names)
                elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                    imports.add(node.module.split(".")[0])
    assert imports.isdisjoint({"janus", "playwright", "langchain", "langchain_anthropic", "langchain_google_genai", "google", "anthropic", "openai", "pyautogui", "applicationinsights"})
    direct = {"mcp", "anyio", "jsonschema", "python-dotenv", "psutil", "pillow", "pywinauto", "pympler", "pydantic", "requests", "langchain-core", "langchain-openai"}
    assert direct.issubset(dependencies)
