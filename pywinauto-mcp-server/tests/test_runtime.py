import json
import sys
from pathlib import Path

import pytest
from autogenesis_agent_contract import ContractError, RuntimeContractRequirement, load_contract

from autogenesis_windows_mcp import server as runtime

pytestmark = [pytest.mark.windows, pytest.mark.skipif(sys.platform != "win32", reason="Real Windows driver imports required")]


@pytest.mark.anyio
async def test_exact_legacy_tool_names_and_complete_input_schemas(app_config):
    expected = json.loads((Path(__file__).parent / "fixtures/legacy_tool_schemas.json").read_text(encoding="utf-8"))["tools"]
    server = runtime.create_server(app_config)
    actual = {tool.name: tool.inputSchema for tool in await server.list_tools()}
    assert len(actual) == 22
    assert actual == expected
    # No new config readback tool can accidentally publish the selected profile.
    assert not any("config" in name for name in actual)


@pytest.mark.anyio
async def test_canonical_instructions_prompts_and_identity_use_merged_adapter(app_config):
    server = runtime.create_server(app_config)
    contract = load_contract()
    assert server.instructions == contract.instructions
    assert runtime.RUNTIME_CONTRACT == RuntimeContractRequirement("1.0.0", "302a8d779a3c30c26f8c5d801fcf06852f802eeaf18e677924a1d9a791b93412")
    assert {prompt.name: [(arg.name, arg.required) for arg in prompt.arguments] for prompt in await server.list_prompts()} == {
        "execute_scenario": [("scenario_text", True), ("feature_file_path", False)],
        "generate_scenario_test": [("scenario_text", True), ("feature_file_path", True)],
        "execute_natural_language_task": [("task_text", True)],
    }
    for name, arguments in {
        "execute_scenario": {"scenario_text": "Given an application"},
        "generate_scenario_test": {"scenario_text": "Given an application", "feature_file_path": "features/demo.feature"},
        "execute_natural_language_task": {"task_text": "Inspect the application"},
    }.items():
        result = await server.get_prompt(name, arguments)
        assert result.messages[0].content.text == contract.render(name, arguments)
    resources = await server.list_resources()
    assert [str(resource.uri) for resource in resources] == ["autogenesis://agent-contract/identity"]
    contents = list(await server.read_resource("autogenesis://agent-contract/identity"))
    identity = json.loads(contents[0].content)
    assert {key: identity[key] for key in contract.identity.to_dict()} == contract.identity.to_dict()


@pytest.mark.parametrize("version,digest", [("2.0.0", "302a8d779a3c30c26f8c5d801fcf06852f802eeaf18e677924a1d9a791b93412"), ("1.0.0", "0" * 64)])
def test_contract_drift_fails_closed_before_driver_import(monkeypatch, app_config, version, digest):
    monkeypatch.setattr(runtime, "RUNTIME_CONTRACT", RuntimeContractRequirement(version, digest))
    with pytest.raises(ContractError):
        runtime.create_server(app_config)
