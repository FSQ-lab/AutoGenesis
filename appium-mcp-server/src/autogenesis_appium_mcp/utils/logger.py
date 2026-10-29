# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
"""Payload-free logs. stdout belongs exclusively to the MCP transport."""

from autogenesis_agent_contract import GenerationCommitError, SecretReferenceError, sanitize_result, tool_execution
import json
from mcp.server.fastmcp.exceptions import ToolError
import logging
import os
from pathlib import Path
import sys
from functools import wraps




class SafeFormatter(logging.Formatter):
    def format(self, record):
        # Exception tracebacks can contain arbitrary third-party response bodies.
        if record.args or record.exc_info or not record.name.startswith("autogenesis_appium_mcp"):
            return f"{record.levelname}: Runtime dependency diagnostic"
        return f"{record.levelname}: {record.getMessage()}"


def configure_logging():
    # Secrets are never interpolated into runtime diagnostics.
    root = logging.getLogger()
    for handler in root.handlers[:]:
        root.removeHandler(handler)
        handler.close()
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(SafeFormatter())
    root.addHandler(handler)
    root.setLevel(logging.WARNING)
    # Preserve the existing opt-in directory convention without writing into site-packages.
    log_dir = os.environ.get("MCP_LOG_FILE")
    if log_dir:
        Path(log_dir).mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(Path(log_dir) / "mcp_server.log", encoding="utf-8")
        handler.setFormatter(SafeFormatter())
        root.addHandler(handler)


def get_mcp_logger(name=None):
    return logging.getLogger(name or "autogenesis_appium_mcp")


logger = get_mcp_logger()


def log_tool_call(func):
    @wraps(func)
    async def wrapper(*args, **kwargs):
        with tool_execution(func, args, kwargs) as (resolved_args, resolved_kwargs):
            logger.info("Tool call started")
            try:
                result = await func(*resolved_args, **resolved_kwargs)
                string_result = isinstance(result, str)
                for _ in range(2):
                    if not isinstance(result, str):
                        break
                    try:
                        result = json.loads(result)
                    except ValueError:
                        break
                logger.info("Tool call completed")
                sanitized = sanitize_result(result)
                return json.dumps(sanitized, ensure_ascii=False) if string_result and not isinstance(sanitized, str) else sanitized
            except (GenerationCommitError, SecretReferenceError) as error:
                raise ToolError(str(error)) from None
            except Exception:
                logger.error("Tool call failed")
                raise RuntimeError("AutoGenesis tool execution failed") from None
    return wrapper
