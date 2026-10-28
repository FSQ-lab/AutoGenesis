"""Installed-runtime shutdown probe with a real watcher and a synthetic driver."""

import json
from pathlib import Path
import sys

from autogenesis_appium_mcp.server import Runtime
from autogenesis_appium_mcp.utils.logger import configure_logging

configure_logging()
runtime = Runtime("mac", sys.argv[1])
configure_logging()
marker = Path(sys.argv[2])
observers = []
start_watching = runtime.config.start_watching


def observe():
    start_watching()
    observers.append(runtime.config._observer)


class Driver:
    def quit(self):
        temporary = marker.with_suffix(".tmp")
        temporary.write_text(json.dumps({
            "driver_quit": True,
            "watcher_stopped": bool(observers) and all(not observer.is_alive() for observer in observers),
        }), encoding="utf-8")
        temporary.replace(marker)


runtime.config.start_watching = observe
runtime.driver._driver = Driver()
try:
    runtime.server.run(transport="stdio")
finally:
    runtime.close()
