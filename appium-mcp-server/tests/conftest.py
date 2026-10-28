import json
from pathlib import Path

import pytest
from mcp.server.fastmcp import FastMCP


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(autouse=True)
def isolated_redaction_registry(monkeypatch):
    from autogenesis_appium_mcp.utils import redaction
    from autogenesis_appium_mcp import server
    # Real diagnostic configuration is exercised in the subprocess wire tests.
    monkeypatch.setattr(server, "configure_logging", lambda: None)
    with redaction._lock:
        previous = redaction._values.copy()
        redaction._values.clear()
    yield
    with redaction._lock:
        redaction._values.clear()
        redaction._values.update(previous)


@pytest.fixture
def config_path(tmp_path):
    path = tmp_path / "appium.json"
    path.write_text(json.dumps({"APPIUM_DRIVER_CONFIGS": {
        platform: {"server_url": "http://127.0.0.1:9", "platformName": platform}
        for platform in ("ios", "android", "mac")
    }}), encoding="utf-8")
    return path


def reference_server(platform):
    """Reconstruct only frozen pre-packaging signatures, never old tool bodies."""
    from typing import Optional
    snapshot = json.loads((Path(__file__).parent / "fixtures/legacy_tools.json").read_text())
    groups = ["appium_driver_tool", "gen_code_tool", "verify_tools", "config_tool", platform + "_driver_tool"]
    reference = FastMCP("legacy-contract")
    for group in groups:
        for source in snapshot[group]:
            namespace = {"Optional": Optional, "__name__": "legacy_tool_fixture"}
            # This fixture is fixed repository test data, never project or model input.
            exec(compile(source, "legacy_tools.json", "exec"), namespace)
            function = next(value for value in namespace.values() if callable(value) and getattr(value, "__module__", None) == "legacy_tool_fixture")
            reference.tool()(function)
    return reference


def pytest_sessionfinish(session, exitstatus):
    """Record counts and exit status, without test logs, node IDs, or failure data."""
    import os
    destination = os.environ.get("AUTOGENESIS_APPIUM_EVIDENCE_DIR")
    if destination:
        root = Path(destination).resolve(strict=True)
        temporary = root / "pytest-status.json.tmp"
        temporary.write_text(json.dumps({
            "exit_code": int(exitstatus), "collected": session.testscollected,
            "failed": session.testsfailed,
        }, indent=2) + "\n", encoding="utf-8")
        temporary.replace(root / "pytest-status.json")
