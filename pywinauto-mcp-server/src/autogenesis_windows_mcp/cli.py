"""Synchronous console entrypoint shared by the wheel and source launcher."""

from autogenesis_agent_contract import safe_secret_error
import argparse
import logging
import io
import json
import os
from asyncio import CancelledError
import sys
from contextlib import redirect_stdout
from pathlib import Path

import anyio
from autogenesis_agent_contract import ContractError
from dotenv import load_dotenv

from .config import ConfigurationError, load_app_config
from .server import create_server
from .utils.logger import configure_logging

logger = logging.getLogger(__name__)


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        self.exit(2, "AUTOGENESIS_ARGUMENTS_INVALID: use --help for supported arguments." + chr(10))


class _ProtocolStdout:
    """Only the MCP transport may access stdout's binary protocol stream.

    Drop incidental print() calls, including during driver imports. Never move
    those values to stderr, where dependency diagnostics could disclose input.
    """

    def __init__(self, stream):
        self.buffer = stream.buffer

    encoding = "utf-8"
    errors = "strict"

    def isatty(self):
        return False

    def writable(self):
        return True

    def write(self, text):
        return len(text)

    def flush(self):
        pass


class _Stdin:
    """A blocked console read must not hold shutdown open after SIGINT."""

    def __init__(self):
        self.pending = b""
        self.closed = anyio.Event()
        self.fd = sys.stdin.fileno()
        self.windows = None
        if sys.platform == "win32":
            from ._windows_stdin import WindowsStdin
            self.windows = WindowsStdin(self.fd)

    def __aiter__(self):
        return self

    async def __anext__(self):
        while bytes([10]) not in self.pending:
            if self.windows is not None:
                chunk = await self.windows.read(4096)
            else:
                # POSIX keeps the existing raw reader; Windows never starts a
                # worker blocked in ReadFile on an open, idle stdin pipe.
                chunk = await anyio.to_thread.run_sync(os.read, self.fd, 4096, abandon_on_cancel=True)
            if not chunk:
                if not self.pending:
                    self.closed.set()
                    raise StopAsyncIteration
                line, self.pending = self.pending, b""
                return line.decode("utf-8")
            self.pending += chunk
        line, _, self.pending = self.pending.partition(bytes([10]))
        return (line + bytes([10])).decode("utf-8")

    def close(self):
        if self.windows is not None:
            self.windows.close()
        self.closed.set()


class _ProtocolWriter:
    """SDK wire-model errors also precede the FastMCP tool/prompt boundary."""

    def __init__(self):
        # Own a duplicate handle, so closing the transport never closes the
        # interpreter's stdout buffer or causes an exit-time flush failure.
        binary = os.fdopen(os.dup(sys.stdout.buffer.fileno()), "wb", buffering=0)
        self.text_stream = io.TextIOWrapper(binary, encoding="utf-8", newline="", write_through=True)
        self.stream = anyio.wrap_file(self.text_stream)
    async def write(self, text):
        message = json.loads(text)
        if "error" in message:
            message["error"] = {
                "code": message["error"]["code"],
                "message": "MCP request failed; check the method and parameters.",
            }
        result = message.get("result")
        if isinstance(result, dict) and result.get("isError"):
            current = " ".join(
                item.get("text", "") for item in result.get("content", []) if isinstance(item, dict)
            )
            safe = safe_secret_error(current)
            result["content"] = [{
                "type": "text",
                "text": safe or "Tool request failed; check the tool name, arguments, and application state.",
            }]
            result.pop("structuredContent", None)
        await self.stream.write(json.dumps(message, ensure_ascii=False) + chr(10))

    async def flush(self):
        await self.stream.flush()

    def close(self):
        self.text_stream.close()


async def _serve(server, transport):
    from mcp.server.stdio import stdio_server

    writer = _ProtocolWriter()
    stdin = _Stdin()

    async def cancel_on_eof(scope):
        await stdin.closed.wait()
        scope.cancel()

    try:
        async with anyio.create_task_group() as lifecycle:
            lifecycle.start_soon(cancel_on_eof, lifecycle.cancel_scope)
            try:
                async with stdio_server(stdin=stdin, stdout=writer) as (read_stream, write_stream):
                    await server._mcp_server.run(
                        read_stream, write_stream, server._mcp_server.create_initialization_options(),
                    )
            finally:
                lifecycle.cancel_scope.cancel()
    finally:
        stdin.close()
        writer.close()


def _client_disconnected(error):
    children = getattr(error, "exceptions", None)
    if children is not None:
        return bool(children) and all(_client_disconnected(child) for child in children)
    return isinstance(error, (KeyboardInterrupt, CancelledError, EOFError, BrokenPipeError, anyio.BrokenResourceError, anyio.ClosedResourceError, anyio.EndOfStream))


def main(argv=None, *, default_config=None, default_transport="stdio") -> int:
    parser = _Parser(description="AutoGenesis Windows MCP runtime")
    parser.add_argument("--app", help="Application profile; defaults to the first apps_config entry")
    parser.add_argument("--transport", choices=["stdio"], default=default_transport)
    parser.add_argument("--config", default=default_config, help="Path to UTF-8 application-profile JSON")
    parser.add_argument("--project-root", help="Existing business-project root; defaults to cwd")
    args = parser.parse_args(argv)
    configure_logging()
    try:
        # Explicit business-directory dotenv only; never load files beside an
        # installed wheel. Existing environment values always take precedence.
        load_dotenv(Path.cwd() / ".env", override=False)
        app_config = load_app_config(args.app, args.config)
        with redirect_stdout(_ProtocolStdout(sys.stdout)):
            server = create_server(app_config, args.project_root)
            anyio.run(_serve, server, args.transport)
        return 0
    except KeyboardInterrupt:
        return 0
    except ConfigurationError as error:
        logger.error(str(error))
        return 2
    except ContractError as error:
        logger.error("Agent Contract validation failed: %s", error.code)
        return 2
    except BaseException as error:
        if _client_disconnected(error):
            return 0
        if isinstance(error, (SystemExit, GeneratorExit)):
            raise
        logger.error("AUTOGENESIS_STARTUP_FAILED: check the Windows platform, installed dependencies, and application configuration.")
        return 1
