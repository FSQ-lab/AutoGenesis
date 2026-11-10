"""Construct the runtime once, against the released Agent Contract adapter."""

from contextlib import asynccontextmanager
import sys

from autogenesis_agent_contract import (
    ContractIdentity, GenerationCommitError, RuntimeContractRequirement,
    SecretReferenceError, load_contract, register_mcp, safe_secret_error,
)
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ResourceError, ToolError


RUNTIME_CONTRACT = RuntimeContractRequirement(
    contract_version="2.1.0",
    manifest_sha256="0b3f0e71800ed02c57c10146f6893dac7b864b8a54348c9c3516ab15bd65e145",
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


class Runtime:
    """Own one Windows MCP server and release its binding on shutdown."""

    def __init__(self, app_config: dict, business_root=None):
        self.manager = None
        self.server = None
        self._closed = False
        try:
            contract = load_contract(ContractIdentity(
                RUNTIME_CONTRACT.contract_version, RUNTIME_CONTRACT.manifest_sha256, 2,
            ))
            if sys.platform != "win32":
                raise RuntimeError("AUTOGENESIS_PLATFORM_UNSUPPORTED: Windows is required to serve automation tools.")

            from .app_session import AppSessionManager
            from .tools.common_tool import register_common_tools
            from .tools.gen_code_tool import register_gen_code_tools
            from .tools.mouse_tool import register_mouse_tools
            from .tools.verify_tool import register_verify_tools

            self.manager = AppSessionManager(app_config)

            @asynccontextmanager
            async def lifespan(server):
                try:
                    yield {}
                finally:
                    self.close()

            self.server = WindowsMCP(
                "pywinauto-mcp-server", instructions=contract.instructions,
                lifespan=lifespan, log_level="INFO",
            )
            register_mcp(self.server, contract, None, RUNTIME_CONTRACT)
            register_common_tools(self.server, self.manager)
            register_mouse_tools(self.server, self.manager)
            register_gen_code_tools(self.server, self.manager, business_root)
            register_verify_tools(self.server, self.manager)
        except BaseException:
            self.close()
            raise

    def close(self):
        if self._closed:
            return
        if self.manager is not None:
            self.manager.release_binding()
        self._closed = True


def create_runtime(app_config: dict, business_root=None) -> Runtime:
    return Runtime(app_config, business_root)


def create_server(app_config: dict, business_root=None) -> WindowsMCP:
    return create_runtime(app_config, business_root).server
