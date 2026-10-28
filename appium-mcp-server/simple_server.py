# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
"""Source checkout entrypoint; the installed console uses the same main."""

from pathlib import Path
import sys

if __name__ == "__main__":
    source_root = Path(__file__).resolve().parent
    sys.path.insert(0, str(source_root / "src"))
    from autogenesis_appium_mcp.server import main

    raise SystemExit(main(default_config=source_root / "conf/appium_conf.json"))
