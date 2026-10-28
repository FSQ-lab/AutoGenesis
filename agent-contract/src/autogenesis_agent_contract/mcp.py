"""Startup registration through FastMCP public APIs; scoped prompt validation.

Unknown dispatch and wire-model validation belong to the SDK, before our prompt
adapter runs. This module does not claim to sanitize those SDK diagnostics.
"""

import asyncio
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.prompts import Prompt
from mcp.server.fastmcp.prompts.base import Message, PromptArgument, UserMessage
from mcp.server.fastmcp.resources import FunctionResource

from ._layout import WORKFLOWS
from .appendix import ProjectAppendix
from .contract import AgentContract, appendix_metadata
from .errors import CONTRACT_INTEGRITY_ERROR, CONTRACT_MISMATCH, PROJECT_INSTRUCTIONS_INVALID, ContractError
from .identity import RuntimeContractRequirement

IDENTITY_URI = "autogenesis://agent-contract/identity"
_REGISTRATION_LOCK = threading.RLock()


class _WorkflowPrompt(Prompt):
    async def render(self, arguments: dict[str, Any] | None = None, context=None) -> list[Message]:
        # The SDK's default adapter interpolates unexpected argument names into
        # errors. Validate the complete mapping through our sanitized boundary.
        return [UserMessage(self.fn({} if arguments is None else arguments))]


def _registry(server: FastMCP) -> tuple[set[str], set[str]]:
    async def discover():
        return (
            {prompt.name for prompt in await server.list_prompts()},
            {str(resource.uri) for resource in await server.list_resources()},
        )

    # register_mcp is synchronous, including when its caller already has an
    # event loop. These public SDK discovery methods inspect in-memory registries;
    # a worker loop avoids nesting the caller's loop or touching private managers.
    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            return executor.submit(lambda: asyncio.run(discover())).result()
    except Exception:
        raise ContractError(CONTRACT_INTEGRITY_ERROR, "mcp_registry_unavailable") from None


def _require_publication(published: threading.Event) -> None:
    if not published.is_set():
        raise ContractError(CONTRACT_INTEGRITY_ERROR, "mcp_registration_incomplete")


def _render_published(published, contract, name, appendix, arguments):
    _require_publication(published)
    return contract.render(name, arguments, appendix)


def register_mcp(
    server: FastMCP,
    contract: AgentContract,
    appendix: ProjectAppendix | None,
    runtime_identity: RuntimeContractRequirement,
) -> None:
    """Register once on a quiescent server, before serving any client.

    Construct FastMCP(..., instructions=contract.instructions) first. FastMCP
    exposes instructions as a read-only property. Existing canonical names/URI
    fail before mutation. Content remains gated until every insertion succeeds.
    The SDK has no public prompt/resource rollback: discard a failed server;
    never catch a registration failure and start or reuse that instance.
    """
    if not isinstance(runtime_identity, RuntimeContractRequirement) or not runtime_identity.matches(contract.identity):
        raise ContractError(CONTRACT_MISMATCH, "runtime_identity_mismatch")
    if server.instructions != contract.instructions:
        raise ContractError(CONTRACT_MISMATCH, "server_instructions_mismatch")
    if appendix is not None and not isinstance(appendix, ProjectAppendix):
        raise ContractError(PROJECT_INSTRUCTIONS_INVALID, "invalid_snapshot")
    with _REGISTRATION_LOCK:
        names, uris = _registry(server)
        if names.intersection(WORKFLOWS) or IDENTITY_URI in uris:
            raise ContractError(CONTRACT_INTEGRITY_ERROR, "mcp_registration_collision")
        published = threading.Event()
        try:
            prompts = []
            for name in WORKFLOWS:
                schema = contract._argument_schema(name)
                prompts.append(_WorkflowPrompt(
                    name=name,
                    description=f"Official AutoGenesis {name} workflow; fixed policy and subordinate task data.",
                    arguments=[
                        PromptArgument(
                            name=key, description=spec["description"], required=key in schema["required"]
                        )
                        for key, spec in schema["properties"].items()
                    ],
                    fn=partial(_render_published, published, contract, name, appendix),
                ))
            identity_json = json.dumps({
                **contract.identity.to_dict(), "appendix": appendix_metadata(appendix)
            }, sort_keys=True)

            def identity_resource() -> str:
                _require_publication(published)
                return identity_json

            resource = FunctionResource.from_function(
                identity_resource, IDENTITY_URI, name="autogenesis_agent_contract_identity",
                description="Verified contract identity and appendix hash, never its content.",
                mime_type="application/json",
            )
            # Construct all SDK objects before inserting anything. Identity is
            # inserted last and its content shares the same commit gate.
            for prompt in prompts:
                server.add_prompt(prompt)
            inserted_names, inserted_uris = _registry(server)
            if not set(WORKFLOWS).issubset(inserted_names) or IDENTITY_URI in inserted_uris:
                raise ContractError(CONTRACT_INTEGRITY_ERROR, "mcp_registration_incomplete")
            server.add_resource(resource)
            final_names, final_uris = _registry(server)
            if not set(WORKFLOWS).issubset(final_names) or IDENTITY_URI not in final_uris:
                raise ContractError(CONTRACT_INTEGRITY_ERROR, "mcp_registration_incomplete")
            published.set()
        except Exception:
            # Do not expose SDK exceptions or caller-controlled registry values.
            # Any already inserted adapters retain their permanently closed gate.
            raise ContractError(CONTRACT_INTEGRITY_ERROR, "mcp_registration_failed") from None
