import json
import sys
from pathlib import Path

import pytest
from mcp.server.fastmcp.exceptions import ToolError
from autogenesis_agent_contract import ContractError, RuntimeContractRequirement, load_contract

from autogenesis_windows_mcp import server as runtime

pytestmark = [pytest.mark.windows, pytest.mark.skipif(sys.platform != "win32", reason="Real Windows driver imports required")]


@pytest.mark.anyio
async def test_versioned_tool_names_and_secret_ref_schemas(app_config):
    expected = json.loads((Path(__file__).parent / "fixtures/legacy_tool_schemas.json").read_text(encoding="utf-8"))["tools"]
    server = runtime.create_server(app_config)
    actual = {tool.name: tool.inputSchema for tool in await server.list_tools()}
    assert len(actual) == 22 and set(actual) == set(expected)
    changed = {"enter_text", "preview_code_changes", "confirm_code_changes"}
    assert {name: schema for name, schema in actual.items() if name not in changed} == {
        name: schema for name, schema in expected.items() if name not in changed
    }
    assert actual["preview_code_changes"]["properties"]["secret_bindings"]["default"] is None
    variants = actual["enter_text"]["properties"]["content"]["anyOf"]
    assert {variant.get("type", "ref") for variant in variants} == {"string", "ref"}
    confirm = actual["confirm_code_changes"]["properties"]
    assert confirm["preview_id"]["default"] == ""
    assert confirm["digest"]["default"] == ""
    assert confirm["approved"]["default"] is False
    assert not any("config" in name for name in actual)

@pytest.mark.anyio
async def test_generation_destination_cannot_escape_business_project(app_config, tmp_path):
    server = runtime.create_server(app_config, business_root=tmp_path)
    outside = tmp_path.parent / f"{tmp_path.name}-outside" / "steps.py"
    with pytest.raises(ToolError, match="AUTOGENESIS_GENERATION_DESTINATION_INVALID"):
        await server.call_tool("before_gen_code", {"step_file": str(outside)})
    assert not outside.parent.exists()



@pytest.mark.anyio
async def test_canonical_instructions_prompts_and_identity_use_merged_adapter(app_config):
    server = runtime.create_server(app_config)
    contract = load_contract()
    assert server.instructions == contract.instructions
    assert runtime.RUNTIME_CONTRACT == RuntimeContractRequirement("2.0.0", "8f9d138c629b8c2db753c4459bb589b4652158233fb9e9bed8b6e5f48569c133")
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


@pytest.mark.parametrize("version,digest", [("3.0.0", "8f9d138c629b8c2db753c4459bb589b4652158233fb9e9bed8b6e5f48569c133"), ("2.0.0", "0" * 64)])
def test_contract_drift_fails_closed_before_driver_import(monkeypatch, app_config, version, digest):
    monkeypatch.setattr(runtime, "RUNTIME_CONTRACT", RuntimeContractRequirement(version, digest))
    with pytest.raises(ContractError):
        runtime.create_server(app_config)
