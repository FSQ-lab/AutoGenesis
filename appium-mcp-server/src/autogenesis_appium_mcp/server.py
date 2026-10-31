"""Installed and source-run MCP runtime. Discovery never starts a driver session."""

import argparse
import json
import os
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
import signal
import sys
import threading

import anyio

from autogenesis_agent_contract import (
    ContractError, ContractIdentity, GenerationCommitError, RuntimeContractRequirement,
    SecretReferenceError, load_contract, register_mcp, safe_secret_error,
)
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

from . import __version__
from .driver_session import DriverSessionManager, SessionCloseError
from .tools.appium_driver_tool import register_appium_driver_tools
from .tools.android_driver_tool import register_android_driver_tools
from .tools.config_tool import register_config_tools
from .tools.gen_code_tool import register_gen_code_tools
from .tools.ios_driver_tool import register_ios_driver_tools
from .tools.mac_driver_tool import register_mac_driver_tools
from .tools.verify_tools import register_verify_tools
from .utils.config_manager import ConfigManager, ConfigurationError
from .utils.logger import configure_logging

from .stdio import cancellable_stdio
REQUIREMENT = RuntimeContractRequirement(
    "2.2.0", "a1004bd4123d6485695a0be9a483b3f5c68fad82a9e9f64285bcf43ff0305e21",
)


@contextmanager
def ignored_shutdown_signals():
    """Prevent repeated termination signals from corrupting cleanup state."""
    if os.name != "posix" or threading.current_thread() is not threading.main_thread():
        yield
        return
    previous = {name: signal.getsignal(name) for name in (signal.SIGTERM, signal.SIGINT)}
    try:
        for name in previous:
            signal.signal(name, signal.SIG_IGN)
        yield
    finally:
        for name, handler in previous.items():
            signal.signal(name, handler)


class AppiumMCP(FastMCP):
    def run(self, transport="stdio", mount_path=None):
        if transport != "stdio":
            raise ValueError("AUTOGENESIS_TRANSPORT_UNSUPPORTED: stdio is required")
        if os.name != "posix" or threading.current_thread() is not threading.main_thread():
            return super().run(transport="stdio", mount_path=mount_path)
        previous = {name: signal.getsignal(name) for name in (signal.SIGTERM, signal.SIGINT)}
        try:
            for name in previous:
                signal.signal(name, self._interrupt_blocking_call)
            try:
                anyio.run(self.run_stdio_async)
            except KeyboardInterrupt:
                pass
        finally:
            for name, handler in previous.items():
                signal.signal(name, handler)

    @staticmethod
    def _interrupt_blocking_call(signum, frame):
        raise KeyboardInterrupt


    async def run_stdio_async(self):
        if os.name != "posix":
            return await super().run_stdio_async()
        # SDK default readline runs in a blocking worker, preventing cancellation
        # while the client's stdin pipe is still open. Keep the SDK protocol
        # adapter and supply cancellable descriptors instead.
        async with cancellable_stdio() as (read, write):
            await self._mcp_server.run(read, write, self._mcp_server.create_initialization_options())

    async def call_tool(self, name, arguments):
        # Rejected names/schemas never enter execution scope. Binding errors are
        # stable and payload-free so a Coding Agent can repair the plan.
        try:
            return await super().call_tool(name, arguments)
        except ToolError as error:
            safe = safe_secret_error(error)
            raise ToolError(safe or "AutoGenesis tool request failed") from None
        except SecretReferenceError as error:
            raise ToolError(str(error)) from None
        except GenerationCommitError as error:
            raise ToolError(str(error)) from None
        except Exception:
            raise ToolError("AutoGenesis tool request failed") from None


class Runtime:
    def __init__(self, platform, config_path=None, business_root=None):
        self.config = ConfigManager(config_path)
        self.business_root = Path(business_root or Path.cwd()).resolve(strict=True)
        self.driver = None
        self._closed = False
        self._close_error = None
        try:
            if not self.config.initial_loaded or platform not in self.config.get_config():
                raise ConfigurationError("Selected platform configuration is unavailable")
            self.driver = DriverSessionManager(platform, self.config.get_config())
            self.config.on_config_change = self.driver.update_config
            contract = load_contract(ContractIdentity(REQUIREMENT.contract_version, REQUIREMENT.manifest_sha256, 2))

            @asynccontextmanager
            async def lifespan(server):
                try:
                    self.config.start_watching()
                    yield {}
                finally:
                    self.close()

            self.lifespan = lifespan
            self.server = AppiumMCP(
                "appium-mcp-server", instructions=contract.instructions,
                lifespan=lifespan, log_level="WARNING",
            )
            register_mcp(self.server, contract, None, REQUIREMENT)
            register_appium_driver_tools(self.server, self.driver)
            register_gen_code_tools(self.server, self.driver, self.business_root)
            register_verify_tools(self.server, self.driver)
            register_config_tools(self.server, self.config)
            {
                "ios": register_ios_driver_tools,
                "android": register_android_driver_tools,
                "mac": register_mac_driver_tools,
            }[platform](self.server, self.driver)
        except BaseException:
            self.close()
            raise

    def close(self):
        if self._closed:
            if self._close_error is not None:
                raise self._close_error
            return
        with ignored_shutdown_signals():
            failure = None
            session_failure = None
            try:
                self.config.stop_watching()
            except Exception as error:
                failure = error
            try:
                if self.driver is not None:
                    self.driver.session_close()
            except SessionCloseError as error:
                session_failure = error
            except Exception as error:
                if failure is None:
                    failure = error
            self._close_error = session_failure or failure
            self._closed = True
            if self._close_error is not None:
                raise self._close_error


class RuntimeArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        self.exit(2, "Invalid AutoGenesis Appium arguments; use --help.\n")


def parse_args(argv=None):
    parser = RuntimeArgumentParser(prog="autogenesis-appium-mcp", description="AutoGenesis Appium MCP runtime")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--platform", choices=("ios", "android", "mac"), default="ios")
    parser.add_argument("--transport", choices=("stdio",), default="stdio")
    parser.add_argument("--config", help="Explicit JSON configuration; otherwise cwd/conf/appium_conf.json or packaged template")
    parser.add_argument("--project-root", help="Existing business-project root; defaults to cwd")
    return parser.parse_args(argv)


def main(argv=None, *, default_config=None):
    args = parse_args(argv)
    runtime = None
    exit_code = 0
    shutdown_reported = False
    try:
        configure_logging()
        config_path = args.config
        if config_path is None and default_config is not None and Path(default_config).is_file():
            config_path = default_config
        runtime = Runtime(args.platform, config_path, business_root=args.project_root)
        # FastMCP configures logging too: restore the safe diagnostic boundary afterwards.
        configure_logging()
        runtime.server.run(transport=args.transport)
    except KeyboardInterrupt:
        pass
    except ContractError as error:
        print(json.dumps(error.to_dict(), sort_keys=True), file=sys.stderr)
        exit_code = 1
    except SessionCloseError:
        print("AutoGenesis Appium shutdown failed.", file=sys.stderr)
        shutdown_reported = True
        exit_code = 1
    except Exception:
        # No caller-controlled paths, JSON, capabilities, or SDK exception bodies.
        print("AutoGenesis Appium startup or transport failed; check configuration and contract installation.", file=sys.stderr)
        exit_code = 1
    finally:
        if runtime is not None:
            try:
                runtime.close()
            except Exception:
                if not shutdown_reported:
                    print("AutoGenesis Appium shutdown failed.", file=sys.stderr)
                    shutdown_reported = True
                exit_code = 1
    return exit_code
