"""Configuration snapshots and directory watching, including atomic replacements."""

from copy import deepcopy
from importlib.resources import files
import json
import os
from pathlib import Path
import re
import threading
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from .logger import get_mcp_logger
from .redaction import remember_configuration

logger = get_mcp_logger()
_ENV_REFERENCE = re.compile(r"^[$][{]([A-Za-z_][A-Za-z0-9_]*)[}]$")


class ConfigurationError(ValueError):
    pass


def resolve_environment(value):
    if isinstance(value, dict):
        return {key: resolve_environment(child) for key, child in value.items()}
    if isinstance(value, list):
        return [resolve_environment(child) for child in value]
    if isinstance(value, str):
        match = _ENV_REFERENCE.fullmatch(value)
        if match:
            resolved = os.environ.get(match[1])
            if not resolved:
                raise ConfigurationError("Required configuration environment variable is missing")
            return resolved
    return value


class ConfigFileHandler(FileSystemEventHandler):
    def __init__(self, config_manager):
        self.config_manager = config_manager

    def on_any_event(self, event):
        if event.is_directory or event.event_type not in {"modified", "created", "moved", "deleted"}:
            return
        paths = (event.src_path, getattr(event, "dest_path", ""))
        if any(path and Path(path).resolve() == Path(self.config_manager.config_path) for path in paths):
            self.config_manager.reload_config()


class ConfigManager:
    def __init__(self, config_path=None, on_config_change=None):
        local = Path.cwd() / "conf/appium_conf.json"
        self._use_template = config_path is None and not local.is_file()
        selected = config_path if config_path is not None else local
        if self._use_template:
            selected = files("autogenesis_appium_mcp").joinpath("conf/appium_conf.template.json")
        self.config_path = str(Path(str(selected)).resolve())
        self.on_config_change = on_config_change
        self._config = {}
        self._lock = threading.RLock()
        self._reload_lock = threading.Lock()
        self._observer = None
        self._closed = False
        self.initial_loaded = self.reload_config()

    def start_watching(self):
        if self._observer is not None or self._use_template or self._closed:
            return
        observer = Observer()
        try:
            observer.schedule(ConfigFileHandler(self), str(Path(self.config_path).parent), recursive=False)
            observer.start()
        except Exception:
            observer.stop()
            if observer.is_alive():
                observer.join(timeout=5)
            raise ConfigurationError("Configuration watcher could not start") from None
        self._observer = observer

    def stop_watching(self):
        self._closed = True
        observer, self._observer = self._observer, None
        if observer is not None:
            observer.stop()
            observer.join(timeout=5)
            if observer.is_alive():
                raise ConfigurationError("Configuration watcher did not stop")

    def reload_config(self):
        # Serialize callbacks too, so a slow previous reload cannot overwrite a newer one.
        with self._reload_lock:
            if self._closed:
                return False
            try:
                raw = json.loads(Path(self.config_path).read_text(encoding="utf-8"))
                config = resolve_environment(raw)["APPIUM_DRIVER_CONFIGS"]
                if not isinstance(config, dict) or not config or set(config) - {"ios", "android", "mac"}:
                    raise ConfigurationError("Invalid platform configuration")
                for platform, profile in config.items():
                    if not isinstance(profile, dict) or not isinstance(profile.get("server_url"), str) or not profile["server_url"]:
                        raise ConfigurationError("Invalid platform configuration")
                with self._lock:
                    # Reject removal of an already selected platform before publishing a snapshot.
                    if self.on_config_change and self.on_config_change(deepcopy(config)) is False:
                        return False
                    remember_configuration(config)
                    self._config = config
                return True
            except Exception:
                logger.warning("Configuration reload failed; previous snapshot retained")
                return False

    def get_config(self):
        with self._lock:
            return deepcopy(self._config)

    def get_platform_config(self, platform):
        with self._lock:
            return deepcopy(self._config.get(platform))
