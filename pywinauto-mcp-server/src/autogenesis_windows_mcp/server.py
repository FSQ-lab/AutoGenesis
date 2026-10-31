"""Construct the runtime once, against the released Agent Contract adapter."""

import sys

from autogenesis_agent_contract import (
    ContractIdentity, GenerationCommitError, RuntimeContractRequirement,
    SecretReferenceError, load_contract, register_mcp, safe_secret_error,
)
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ResourceError, ToolError


RUNTIME_CONTRACT = RuntimeContractRequirement(
    contract_version="2.1.0",
    manifest_sha256="ec097a569aa4d62da8211f3ad23fb00eccb95d9d9cee871e360af6ac05ca1dd6",
)


class WindowsMCP(FastMCP):
    """Keep SDK argument-validation errors from echoing submitted values."""

    async def call_tool(self, name, arguments):
        try:
            return await super().call_tool(name, arguments)
        except ToolError as error:
            safe = safe_secret_error(error)
            raise ToolError(safe or "Tool request failed; check the tool name, arguments, and application state.") from None
        except SecretReferenceError as error:
            raise ToolError(str(error)) from None
        except GenerationCommitError as error:
            raise ToolError(str(error)) from None
        except Exception:
            raise ToolError("Tool request failed; check the tool name, arguments, and application state.") from None

    async def get_prompt(self, name, arguments=None):
        try:
            return await super().get_prompt(name, arguments)
        except Exception:
            raise ValueError("Prompt request failed; check the canonical workflow and arguments.") from None

    async def read_resource(self, uri):
        try:
            return await super().read_resource(uri)
        except Exception:
            raise ResourceError("Resource request failed; check the resource URI.") from None


def create_server(app_config: dict, business_root=None) -> WindowsMCP:
    contract = load_contract(ContractIdentity(
        RUNTIME_CONTRACT.contract_version, RUNTIME_CONTRACT.manifest_sha256, 2,
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
    register_gen_code_tools(server, manager, business_root)
    register_verify_tools(server, manager)
    return server
