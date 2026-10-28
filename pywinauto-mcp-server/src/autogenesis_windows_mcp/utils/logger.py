# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
"""Metadata-only logging; no package-directory writes or exception tracebacks."""

import inspect
import logging
import sys
import time
from functools import wraps

from ..security import remember_tool_inputs, scrub, scrub_tool_result, safe_error

logger = logging.getLogger(__name__)


class _SafeDiagnostic(logging.Filter):
    def filter(self, record):
        if record.name.startswith("autogenesis_windows_mcp"):
            record.msg = scrub(record.getMessage())
        else:
            # Third-party SDK/HTTP/driver diagnostics can contain request bodies,
            # headers or validation values. They are never diagnostic evidence.
            record.msg = "Dependency diagnostic withheld."
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
    signature = inspect.signature(func)

    @wraps(func)
    async def wrapper(*args, **kwargs):
        remember_tool_inputs(signature.bind_partial(*args, **kwargs).arguments)
        started = time.monotonic()
        logger.info("Tool started: %s", func.__name__)
        try:
            result = await func(*args, **kwargs)
            logger.info("Tool finished: %s (%.3fs)", func.__name__, time.monotonic() - started)
            return scrub_tool_result(result)
        except Exception:
            logger.error("Tool failed: %s", func.__name__)
            raise RuntimeError(safe_error()) from None

    return wrapper
