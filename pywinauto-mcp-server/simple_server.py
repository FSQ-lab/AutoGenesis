# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
"""Source-run entrypoint. The installed console command defaults to stdio."""

import sys
from pathlib import Path

if __name__ == "__main__":
    root = Path(__file__).resolve().parent
    sys.path.insert(0, str(root / "src"))
    from autogenesis_windows_mcp.cli import main

    local_config = root / "conf" / "pywinauto_conf.json"
    raise SystemExit(main(
        default_config=local_config if local_config.is_file() else None,
        default_transport="sse",
    ))
