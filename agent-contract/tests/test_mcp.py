import hashlib
import json
import os
import re
import sys
from importlib import resources
from pathlib import Path

import anyio
import pytest
from jsonschema import Draft202012Validator
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ResourceError
from mcp.shared.exceptions import McpError
from mcp.types import GetPromptRequestParams
from pydantic import ValidationError

from autogenesis_agent_contract import (
    CONTRACT_INTEGRITY_ERROR, CONTRACT_MISMATCH, ContractError, RuntimeContractRequirement,
    load_project_appendix, register_mcp,
)

URI = "autogenesis://agent-contract/identity"


def requirement(contract):
    return RuntimeContractRequirement(contract.identity.contract_version, contract.identity.manifest_sha256)


def task_data(text):
    return json.loads(re.search(r"<autogenesis-task-data>\n(.*?)\n</autogenesis-task-data>", text, re.S).group(1))


def evidence(filename, value):
    destination = os.environ.get("AUTOGENESIS_EVIDENCE_DIR")
    if destination:
        root = Path(destination).resolve(strict=True)
        temporary = root / (filename + ".tmp")
        temporary.write_text(json.dumps(value, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
        temporary.replace(root / filename)


@pytest.mark.anyio
@pytest.mark.parametrize("kind", ["version", "hash", "instructions", "missing_requirement"])
async def test_registration_fails_before_exposing_prompts_on_mismatch(contract, kind):
    server = FastMCP("mismatch", instructions=contract.instructions if kind != "instructions" else "Other policy")
    expected = requirement(contract)
    if kind == "version":
        expected = RuntimeContractRequirement("3.0.0", contract.identity.manifest_sha256)
    elif kind == "hash":
        expected = RuntimeContractRequirement("2.2.0", "0" * 64)
    elif kind == "missing_requirement":
        expected = None
    with pytest.raises(ContractError) as caught:
        register_mcp(server, contract, None, expected)
    assert caught.value.code == CONTRACT_MISMATCH
    assert await server.list_prompts() == []
    assert await server.list_resources() == []


@pytest.mark.anyio
async def test_mcp_argument_errors_are_structured_and_sanitized(contract, caplog):
    server = FastMCP("sanitized", instructions=contract.instructions)
    register_mcp(server, contract, None, requirement(contract))
    canary = "SYNTHETIC_MCP_SECRET_CANARY_BF20"
    for arguments in ({canary: canary}, {"scenario_text": [canary]}, {"scenario_text": canary + "\x00"}, {"scenario_text": "Given an app", canary: canary}):
        with pytest.raises(ValueError) as caught:
            await server.get_prompt("execute_scenario", arguments)
        assert "AUTOGENESIS_CONTRACT_INTEGRITY_ERROR" in str(caught.value)
        assert canary not in str(caught.value) + caplog.text


@pytest.mark.anyio
@pytest.mark.parametrize("collision", ["execute_scenario", "generate_scenario_test", "execute_natural_language_task", URI])
async def test_existing_canonical_names_fail_before_any_mutation(contract, collision):
    server = FastMCP("collision", instructions=contract.instructions)
    if collision == URI:
        @server.resource(URI)
        def existing_resource() -> str:
            return "preexisting resource"
    else:
        @server.prompt(name=collision)
        def existing_prompt() -> str:
            return "preexisting prompt"
    before_prompts = await server.list_prompts()
    before_resources = await server.list_resources()
    with pytest.raises(ContractError) as caught:
        register_mcp(server, contract, None, requirement(contract))
    assert caught.value.to_dict() == {"code": CONTRACT_INTEGRITY_ERROR, "reason": "mcp_registration_collision"}
    assert await server.list_prompts() == before_prompts
    assert await server.list_resources() == before_resources
    if collision == URI:
        assert list(await server.read_resource(URI))[0].content == "preexisting resource"
    else:
        assert (await server.get_prompt(collision)).messages[0].content.text == "preexisting prompt"


@pytest.mark.anyio
async def test_repeat_registration_fails_and_preserves_original_publication(contract):
    server = FastMCP("repeat", instructions=contract.instructions)
    register_mcp(server, contract, None, requirement(contract))
    original = list(await server.read_resource(URI))[0].content
    with pytest.raises(ContractError, match="mcp_registration_collision"):
        register_mcp(server, contract, None, requirement(contract))
    assert list(await server.read_resource(URI))[0].content == original


@pytest.mark.anyio
@pytest.mark.parametrize("failure", ["prompt", "resource_before", "resource_after"])
async def test_failed_registration_never_publishes_canonical_content(contract, failure):
    class FailingServer(FastMCP):
        def add_prompt(self, prompt):
            super().add_prompt(prompt)
            if failure == "prompt" and prompt.name == "generate_scenario_test":
                raise RuntimeError("injected insertion failure")

        def add_resource(self, resource):
            if failure == "resource_before":
                raise RuntimeError("injected insertion failure")
            super().add_resource(resource)
            if failure == "resource_after":
                raise RuntimeError("injected insertion failure")

    server = FailingServer("failed", instructions=contract.instructions)
    with pytest.raises(ContractError, match="mcp_registration_failed"):
        register_mcp(server, contract, None, requirement(contract))
    for prompt in await server.list_prompts():
        with pytest.raises(ValueError, match="mcp_registration_incomplete") as caught:
            await server.get_prompt(prompt.name, {"scenario_text": "Given an app", "feature_file_path": "a.feature"})
        assert contract.identity.manifest_sha256 not in str(caught.value)
    if failure == "resource_after":
        with pytest.raises(ResourceError, match="mcp_registration_incomplete") as caught:
            await server.read_resource(URI)
        assert contract.identity.manifest_sha256 not in str(caught.value)
    else:
        assert not await server.list_resources()


@pytest.mark.anyio
async def test_registration_preserves_unrelated_registrations(contract):
    server = FastMCP("unrelated", instructions=contract.instructions)

    @server.prompt()
    def unrelated_prompt() -> str:
        return "unrelated"

    @server.resource("test://unrelated/value")
    def unrelated_resource() -> str:
        return "unrelated"

    register_mcp(server, contract, None, requirement(contract))
    assert (await server.get_prompt("unrelated_prompt")).messages[0].content.text == "unrelated"
    assert list(await server.read_resource("test://unrelated/value"))[0].content == "unrelated"


@pytest.mark.anyio
async def test_sdk_dispatch_and_wire_validation_are_outside_contract_boundary(contract, caplog):
    server = FastMCP("dispatch-boundary", instructions=contract.instructions)
    register_mcp(server, contract, None, requirement(contract))
    # Use a nonsecret literal: the SDK includes unknown names in diagnostics.
    with pytest.raises(ValueError, match="Unknown prompt: not_registered"):
        await server.get_prompt("not_registered", {})
    assert "not_registered" in caplog.text
    # An invalid wire value is rejected before any registered prompt can run.
    with pytest.raises(ValidationError):
        GetPromptRequestParams(name="execute_scenario", arguments={"scenario_text": ["not-a-string"]})
    with pytest.raises(ContractError) as caught:
        contract.render("not_registered", {})
    assert caught.value.to_dict() == {"code": CONTRACT_INTEGRITY_ERROR, "reason": "unknown_workflow"}


@pytest.mark.anyio
@pytest.mark.parametrize("with_appendix", [False, True])
async def test_real_stdio_initialize_discovery_render_resource_and_snapshot(contract, tmp_path, with_appendix):
    raw = b"Domain: use the test account represented by an environment reference.\n"
    appendix_file = tmp_path / ".autogenesis/instructions.md"
    if with_appendix:
        appendix_file.parent.mkdir()
        appendix_file.write_bytes(raw)
    fixture = Path(__file__).parent / "fixtures/stdio_server.py"
    arguments = [str(fixture.resolve()), "--project-root", str(tmp_path)]
    parameters = StdioServerParameters(command=sys.executable, args=arguments, cwd=str(tmp_path))
    with (tmp_path / "server.stderr").open("w+", encoding="utf-8") as errlog:
        with anyio.fail_after(40):
            async with stdio_client(parameters, errlog=errlog) as (read, write):
                async with ClientSession(read, write) as session:
                    initialized = await session.initialize()
                    assert initialized.instructions == contract.instructions
                    assert raw.decode().strip() not in initialized.instructions
                    discovered = await session.list_prompts()
                    actual = {p.name: [(a.name, a.required) for a in p.arguments] for p in discovered.prompts}
                    assert actual == {
                        "execute_scenario": [("scenario_text", True), ("feature_file_path", False)],
                        "generate_scenario_test": [("scenario_text", True), ("feature_file_path", True)],
                        "execute_natural_language_task": [("task_text", True)],
                    }
                    listed = await session.list_resources()
                    assert [str(resource.uri) for resource in listed.resources] == [URI]
                    assert listed.resources[0].mimeType == "application/json"
                    assert (await session.list_tools()).tools == []
                    # The server must retain its initial snapshot after startup.
                    appendix_file.parent.mkdir(exist_ok=True)
                    appendix_file.write_bytes(b"Changed after initialization")
                    cases = {
                        "execute_scenario": {"scenario_text": "Background: Login\nGiven an app\nScenario: Search\nWhen I search\nThen results appear"},
                        "generate_scenario_test": {"scenario_text": "Given an app", "feature_file_path": "features/demo.feature"},
                        "execute_natural_language_task": {"task_text": "Open the app and verify its title"},
                    }
                    transcript = {}
                    for name, arguments in cases.items():
                        result = await session.get_prompt(name, arguments)
                        assert len(result.messages) == 1 and result.messages[0].role == "user"
                        rendered = result.messages[0].content.text
                        assert rendered.startswith(contract.instructions)
                        assert task_data(rendered) == arguments
                        appendix = json.loads(re.search(r"<autogenesis-project-appendix>\n(.*?)\n</autogenesis-project-appendix>", rendered, re.S).group(1))
                        assert appendix["content"] == (raw.decode() if with_appendix else "")
                        assert appendix["present"] is with_appendix
                        transcript[name] = result.model_dump(mode="json")
                    read_identity = await session.read_resource(URI)
                    identity = json.loads(read_identity.contents[0].text)
                    assert {key: identity[key] for key in contract.identity.to_dict()} == contract.identity.to_dict()
                    assert identity["appendix"]["sha256"] == (hashlib.sha256(raw).hexdigest() if with_appendix else None)
                    assert "content" not in identity["appendix"]
                    schema = json.loads(resources.files("autogenesis_agent_contract").joinpath("assets/schemas/identity.schema.json").read_bytes())
                    Draft202012Validator(schema).validate(identity)
                    canary = "SYNTHETIC_UNKNOWN_ARGUMENT_CANARY_D822"
                    with pytest.raises(McpError) as caught:
                        await session.get_prompt("execute_scenario", {"scenario_text": "Given an app", canary: canary})
                    assert "AUTOGENESIS_CONTRACT_INTEGRITY_ERROR" in str(caught.value)
                    assert canary not in str(caught.value)
                    with pytest.raises(McpError) as caught:
                        await session.get_prompt("execute_scenario", {"scenario_text": canary + "\x00"})
                    assert "AUTOGENESIS_CONTRACT_INTEGRITY_ERROR" in str(caught.value)
                    assert canary not in str(caught.value)
                    evidence(f"stdio-{'appendix' if with_appendix else 'empty'}.json", {
                        "initialize": initialized.model_dump(mode="json"),
                        "prompts_list": discovered.model_dump(mode="json"),
                        "prompts_get": transcript, "identity": identity,
                    })
        errlog.seek(0)
        assert "SYNTHETIC_UNKNOWN_ARGUMENT_CANARY_D822" not in errlog.read()
