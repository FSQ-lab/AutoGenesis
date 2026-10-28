"""Construct the runtime once, against the released Agent Contract adapter."""

import sys

from autogenesis_agent_contract import (
    ContractIdentity, RuntimeContractRequirement, load_contract, register_mcp,
)
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ResourceError, ToolError
from .security import scrub

RUNTIME_CONTRACT = RuntimeContractRequirement(
    contract_version="1.0.0",
    manifest_sha256="302a8d779a3c30c26f8c5d801fcf06852f802eeaf18e677924a1d9a791b93412",
)


class WindowsMCP(FastMCP):
    """Keep SDK argument-validation errors from echoing submitted values."""

    async def call_tool(self, name, arguments):
        try:
            return await super().call_tool(name, arguments)
        except Exception:
            raise ToolError("Tool request failed; check the tool name, arguments, and application state.") from None

    async def get_prompt(self, name, arguments=None):
        try:
            return await super().get_prompt(name, scrub(arguments))
        except Exception:
            raise ValueError("Prompt request failed; check the canonical workflow and arguments.") from None

    async def read_resource(self, uri):
        try:
            return await super().read_resource(uri)
        except Exception:
            raise ResourceError("Resource request failed; check the resource URI.") from None


def create_server(app_config: dict) -> WindowsMCP:
    # Validate the immutable contract before importing platform drivers. Never
    # fall back to duplicated prompts or serve a partially registered server.
    contract = load_contract(ContractIdentity(
        RUNTIME_CONTRACT.contract_version, RUNTIME_CONTRACT.manifest_sha256,
    ))
    server = WindowsMCP("pywinauto-mcp-server", instructions=contract.instructions, log_level="INFO")
    register_mcp(server, contract, None, RUNTIME_CONTRACT)
    if sys.platform != "win32":
        raise RuntimeError("AUTOGENESIS_PLATFORM_UNSUPPORTED: Windows is required to serve automation tools.")

    from .app_session import AppSessionManager
    from .tools.common_tool import register_common_tools
    from .tools.gen_code_tool import register_gen_code_tools
    from .tools.mouse_tool import register_mouse_tools
    from .tools.verify_tool import register_verify_tools

    manager = AppSessionManager(app_config)
    register_common_tools(server, manager)
    register_mouse_tools(server, manager)
    register_gen_code_tools(server, manager)
    register_verify_tools(server, manager)
    return server
