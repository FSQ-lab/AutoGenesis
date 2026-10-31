import configparser
import hashlib
from importlib import metadata, resources
import inspect
import json
import os
from pathlib import Path
import zipfile

import pytest
from autogenesis_agent_contract import ContractError, RuntimeContractRequirement, load_contract

from autogenesis_appium_mcp import server

VERSION = "2.2.0"
DIGEST = "75cf1b6d6afa13b8f0de7d87be79642fa58ab0a582da985ba3c2a1acbc35b554"
PROMPTS = {"execute_scenario", "generate_scenario_test", "execute_natural_language_task"}
URI = "autogenesis://agent-contract/identity"


def test_installed_console_and_exact_contract_requirement():
    distribution = metadata.distribution("autogenesis-appium-mcp")
    assert distribution.version == "0.6.0"
    entrypoints = [item for item in distribution.entry_points if item.group == "console_scripts"]
    assert [(item.name, item.value) for item in entrypoints] == [
        ("autogenesis-appium-mcp", "autogenesis_appium_mcp.server:main"),
    ]
    assert entrypoints[0].load() is server.main
    assert not inspect.iscoroutinefunction(server.main)
    dependencies = [item.lower().replace(" ", "") for item in distribution.requires]
    assert "autogenesis-agent-contract==2.2.0" in dependencies
    assert not any(item.startswith("browserstack-sdk") for item in dependencies)
    assert server.REQUIREMENT == RuntimeContractRequirement(VERSION, DIGEST)
    manifest = resources.files("autogenesis_agent_contract").joinpath("assets/manifest.json").read_bytes()
    assert hashlib.sha256(manifest).hexdigest() == DIGEST
    assert load_contract().identity.manifest_sha256 == DIGEST


def test_wheel_is_self_contained_and_installed_outside_checkout():
    wheel = Path(os.environ["APPIUM_WHEEL_PATH"])
    with zipfile.ZipFile(wheel) as archive:
        names = set(archive.namelist())
        prefix = "autogenesis_appium_mcp/"
        required = {
            "__init__.py", "server.py", "stdio.py", "driver_session.py", "conf/appium_conf.template.json",
            "tools/__init__.py", "tools/appium_driver_tool.py", "tools/android_driver_tool.py",
            "tools/ios_driver_tool.py", "tools/mac_driver_tool.py", "tools/config_tool.py",
            "tools/gen_code_tool.py", "tools/verify_tools.py", "utils/config_manager.py",
            "utils/logger.py", "utils/page_source.py", "utils/gen_code.py", "utils/response_format.py",
            "utils/element_util.py", "llm/chat.py", "llm/prompt.py",
        }
        assert {prefix + item for item in required} <= names
        assert not any(name.startswith(("tools/", "utils/", "llm/", "logs/", "tests/")) for name in names)
        assert not any(name.endswith(("appium_conf.json", ".env", ".pyc")) for name in names)
        config = json.loads(archive.read(prefix + "conf/appium_conf.template.json"))
        expected_template = Path(__file__).parent / "fixtures/source_template.json"
        if not expected_template.exists():
            expected_template = Path(__file__).parents[1] / "conf/appium_conf.template.json"
        assert archive.read(prefix + "conf/appium_conf.template.json") == expected_template.read_bytes()
        assert set(config["APPIUM_DRIVER_CONFIGS"]) == {"ios", "android", "mac"}
        entry = next(name for name in names if name.endswith(".dist-info/entry_points.txt"))
        parser = configparser.ConfigParser()
        parser.read_string(archive.read(entry).decode())
        assert parser["console_scripts"]["autogenesis-appium-mcp"] == "autogenesis_appium_mcp.server:main"
    import sys
    location = Path(server.__file__).resolve()
    assert location.is_relative_to(Path(sys.prefix).resolve())
    forbidden = Path(os.environ["APPIUM_SOURCE_ROOT"]).resolve()
    assert not location.is_relative_to(forbidden)
    assert not any(Path(item).resolve().is_relative_to(forbidden) for item in sys.path if item)


@pytest.mark.anyio
async def test_canonical_instructions_prompt_arguments_and_identity(config_path):
    runtime = server.Runtime("mac", config_path)
    try:
        contract = load_contract()
        assert runtime.server.instructions == contract.instructions
        discovered = await runtime.server.list_prompts()
        assert {p.name: [(a.name, a.required) for a in p.arguments] for p in discovered} == {
            "execute_scenario": [("scenario_text", True), ("feature_file_path", False)],
            "generate_scenario_test": [("scenario_text", True), ("feature_file_path", True)],
            "execute_natural_language_task": [("task_text", True)],
        }
        cases = {
            "execute_scenario": {"scenario_text": "Given an app"},
            "generate_scenario_test": {"scenario_text": "Given an app", "feature_file_path": "features/app.feature"},
            "execute_natural_language_task": {"task_text": "Inspect the app title"},
        }
        for name, arguments in cases.items():
            result = await runtime.server.get_prompt(name, arguments)
            assert result.messages[0].content.text == contract.render(name, arguments)
        assert [str(resource.uri) for resource in await runtime.server.list_resources()] == [URI]
        identity = json.loads(list(await runtime.server.read_resource(URI))[0].content)
        assert identity["contract_version"] == VERSION
        assert identity["manifest_sha256"] == DIGEST
    finally:
        runtime.close()


@pytest.mark.parametrize("requirement", [RuntimeContractRequirement("3.0.0", DIGEST), RuntimeContractRequirement(VERSION, "0" * 64)])
def test_contract_drift_fails_closed_before_server_publication(requirement, config_path, monkeypatch):
    monkeypatch.setattr(server, "REQUIREMENT", requirement)
    with pytest.raises(ContractError):
        server.Runtime("ios", config_path)
