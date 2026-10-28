import os
import sys
from pathlib import Path

import pytest



@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def app_config():
    return {
        "exe": str(Path(os.environ.get("WINDIR", "C:/Windows")) / "System32/notepad.exe"),
        "window_title_re": ".*AutoGenesis acceptance.*",
        "launch_args": [],
    }


@pytest.fixture
def console_command():
    executable = Path(sys.executable).parent / ("autogenesis-windows-mcp.exe" if os.name == "nt" else "autogenesis-windows-mcp")
    if not executable.is_file():
        pytest.fail("Install the built runtime wheel before running console acceptance.")
    return [str(executable)]
