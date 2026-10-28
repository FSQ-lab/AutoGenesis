# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
"""Metadata-only logging; no package-directory writes or exception tracebacks."""

from autogenesis_agent_contract import SecretReferenceError, sanitize_result, tool_execution
import json
from mcp.server.fastmcp.exceptions import ToolError
import logging
import sys
import time
from functools import wraps



logger = logging.getLogger(__name__)


class _SafeDiagnostic(logging.Filter):
    def filter(self, record):
        if record.args or record.exc_info or not record.name.startswith("autogenesis_windows_mcp"):
            record.msg = "Runtime diagnostic withheld."
        else:
            record.msg = record.getMessage()
        record.args = ()
        record.exc_info = None
        record.exc_text = None
        record.stack_info = None
        return True


def configure_logging():
    handler = logging.StreamHandler(sys.stderr)
    handler.addFilter(_SafeDiagnostic())
    handler.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
    logging.basicConfig(level=logging.INFO, handlers=[handler], force=True)
    logging.captureWarnings(True)
    # Use one filtered sink, even if a dependency configured a named handler.
    for item in logging.root.manager.loggerDict.values():
        if isinstance(item, logging.Logger):
            item.handlers.clear()
            item.propagate = True


def log_tool_call(func):


    @wraps(func)
    async def wrapper(*args, **kwargs):
        with tool_execution(func, args, kwargs) as (resolved_args, resolved_kwargs):
            started = time.monotonic()
            logger.info("Tool started")
            try:
                result = await func(*resolved_args, **resolved_kwargs)
                string_result = isinstance(result, str)
                if isinstance(result, str):
                    try:
                        result = json.loads(result)
                    except ValueError:
                        pass
                logger.info("Tool finished")
                sanitized = sanitize_result(result)
                return json.dumps(sanitized, ensure_ascii=False) if string_result and not isinstance(sanitized, str) else sanitized
            except SecretReferenceError as error:
                raise ToolError(str(error)) from None
            except Exception:
                logger.error("Tool failed")
                raise RuntimeError("Automation operation failed; sensitive details withheld.") from None

    return wrapper
