# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

# tools/browser_manager.py

from autogenesis_agent_contract import contains_credential_url, resolve, sanitize_result
import time
import logging

import threading
from datetime import datetime
from appium import webdriver
from appium.options.ios import XCUITestOptions
from appium.options.mac import Mac2Options  # Add this import for Mac automation
from selenium.webdriver.remote.command import Command
from appium.options.android import UiAutomator2Options  # Add this for Android if needed
from .utils.logger import get_mcp_logger

logger = get_mcp_logger()
SESSION_CLOSE_TIMEOUT_SECONDS = 5


class SessionCloseError(RuntimeError):
    """The Runtime could not confirm destruction of its owned session."""



class DriverSessionManager:
    def __init__(self, device: str, driver_configs: dict = None):
        if device not in driver_configs:
            raise ValueError(f"Unsupported device: {device}")
        self.device = device
        self.driver_configs = driver_configs  # Store all configs
        self.config = driver_configs[device]
        self.gen_code_id = None
        self.gen_code_cache = []
        self.proposed_changes = None  # Store proposed code changes
        self.pending_write = None
        self.recording_warnings = []
        self.header_code = ""
        self._driver = None
        self.server_url = self.config["server_url"]
        self.is_executing = False
        self._session_close_lock = threading.Lock()
        self._session_close_thread = None
        self._session_close_driver = None
        self._session_close_failed = False


    def update_config(self, new_driver_configs: dict):
        """Update configuration dynamically without restarting"""
        logger.info("Operation diagnostic; private details omitted")

        if self.device not in new_driver_configs:
            logger.error("Operation diagnostic; private details omitted")
            return False

        self.driver_configs = new_driver_configs
        self.config = new_driver_configs[self.device]
        self.server_url = self.config["server_url"]

        logger.info("Configuration updated successfully. Changes will take effect on next session creation.")
        return True

    def start_tool_execution(self, tool_name):
        if self.is_executing:
            logger.warning("Operation diagnostic; private details omitted")
            return False
        self.is_executing = True
        logger.info("Operation diagnostic; private details omitted")
        return True

    def finish_tool_execution(self, tool_name):
        self.is_executing = False
        logger.info("Operation diagnostic; private details omitted")

    def _is_session_valid(self):
        """Check if the current driver session is still valid"""
        if not self._driver:
            return False
        try:
            # Try to get the session status to validate the session
            self._driver.get_window_size()
            return True
        except Exception as e:
            return False

    def app_launch(self, kill_existing: int = 0, arguments: list = None):
        self._settle_session_close()
        # Normalize arguments: ensure it's a valid list or None
        if not isinstance(arguments, list) or not arguments:
            arguments = None
        if kill_existing == 1:
            self.app_close()

        if self.device == "mac" and self._driver and self._is_session_valid():
            logger.info("Mac platform: closing existing session before new session")
            self.session_close()

        if self._driver and self._is_session_valid():
            logger.info("Driver session already exists and is valid, reusing it.")
            package = self.app_package()
            logger.info("start activate app")
            try:
                self._driver.activate_app(package)
                return self._driver
            except Exception:
                logger.warning("Operation diagnostic; private details omitted")
                self.session_close()

        try:
            runtime_config = resolve(self.config)
            server_url = runtime_config["server_url"]
            if contains_credential_url(server_url):
                raise ValueError("AUTOGENESIS_SECRET_REFERENCE_REQUIRED: server_url")
            logger.info("Operation diagnostic; private details omitted")

            # Resolved plaintext remains local to session creation only.
            config_copy = runtime_config.copy()
            
            # Add or override arguments if provided
            if arguments is not None:
                config_copy["arguments"] = arguments
                logger.info("Operation diagnostic; private details omitted")
            
            logger.info("Operation diagnostic; private details omitted")

            # Use appropriate options based on device type
            if self.device == "ios":
                options = XCUITestOptions().load_capabilities(config_copy)
            elif self.device == "mac":
                options = Mac2Options().load_capabilities(config_copy)
            elif self.device == "android":
                options = UiAutomator2Options().load_capabilities(config_copy)
            else:
                raise ValueError(f"Unsupported device type: {self.device}")
            self._driver = webdriver.Remote(server_url, options=options)
            # Remote clients may retain returned capabilities; keep only safe
            # literals and reference requirements in the long-lived object.
            capabilities = getattr(self._driver, "capabilities", None)
            if isinstance(capabilities, dict):
                safe_capabilities = sanitize_result(capabilities)
                capabilities.clear()
                capabilities.update(safe_capabilities)
            logger.info("Driver session created successfully")

            # Try to activate app, but don't fail if method is not implemented
            package = self.app_package()
            if package and self.device in ["ios", "android"]:
                logger.info("Attempting to activate app")
                try:
                    self._driver.activate_app(package)
                    logger.info("App activated successfully")
                except Exception as e:
                    logger.warning("Operation diagnostic; private details omitted")
            else:
                logger.info("Mac platform or no bundleId found, skipping app activation")

            return self._driver

        except Exception:
            logger.error("Operation diagnostic; private details omitted")
            if self._driver is not None:
                self.session_close()
            raise

    def app_package(self):
        """Get from config first (reliable), then from capabilities (fallback)."""
        runtime_config = resolve(self.config)
        if self.device in ["ios", "mac"]:
            package = runtime_config.get("bundleId")
        elif self.device == "android":
            package = runtime_config.get("appPackage")
        else:
            package = None

        if package:
            return package

        # Priority 2: From capabilities (fallback for compatibility)
        if self._driver:
            caps = self._driver.capabilities
            return (caps.get("bundleId") or 
                    caps.get("appium:bundleId") or 
                    caps.get("appPackage") or 
                    caps.get("appium:appPackage"))

        return None

    def app_close(self):
        if self._driver and self._is_session_valid():
            package = self.app_package()
            if package and self.device in ["ios", "android"]:
                # For iOS and Android, terminate the app using bundle ID
                logger.info("Operation diagnostic; private details omitted")
                self._driver.terminate_app(package)
        else:
            logger.warning("No app to close or driver session is invalid.")

    @staticmethod
    def _destroy_session(driver):
        """Delete one owned WebDriver session and validate the protocol response."""
        executor = getattr(driver, "command_executor", None)
        session_id = getattr(driver, "session_id", None)
        if not isinstance(session_id, str) or not session_id or not hasattr(executor, "execute"):
            driver.quit()
            return

        response = executor.execute(Command.QUIT, {"sessionId": session_id})
        if not isinstance(response, dict) or response.get("status") not in (None, 0):
            raise SessionCloseError("AUTOGENESIS_SESSION_CLOSE_FAILED")
        value = response.get("value")
        if isinstance(value, dict) and value.get("error"):
            raise SessionCloseError("AUTOGENESIS_SESSION_CLOSE_FAILED")
        driver.session_id = None
        try:
            driver.stop_client()
        finally:
            executor.close()

    def _settle_session_close(self):
        """Resolve a completed close attempt before a driver can be replaced."""
        with self._session_close_lock:
            close_thread = self._session_close_thread
            if close_thread is None:
                return
            if close_thread.is_alive():
                raise SessionCloseError("AUTOGENESIS_SESSION_CLOSE_IN_PROGRESS")
            if self._session_close_failed:
                raise SessionCloseError("AUTOGENESIS_SESSION_CLOSE_FAILED")
            if self._driver is self._session_close_driver:
                self._driver = None
            self._session_close_thread = None
            self._session_close_driver = None

    def session_close(self):
        """Destroy the Runtime-owned session without closing the application explicitly."""
        with self._session_close_lock:
            driver = self._driver
            if driver is None:
                return
            if self._session_close_thread is None:
                self._session_close_driver = driver
                self._session_close_failed = False

                def quit_driver():
                    try:
                        self._destroy_session(driver)
                    except Exception:
                        self._session_close_failed = True

                self._session_close_thread = threading.Thread(target=quit_driver, daemon=True)
                self._session_close_thread.start()
            elif self._session_close_driver is not driver:
                raise SessionCloseError("AUTOGENESIS_SESSION_CLOSE_IN_PROGRESS")
            close_thread = self._session_close_thread

        close_thread.join(timeout=SESSION_CLOSE_TIMEOUT_SECONDS)
        if close_thread.is_alive():
            raise SessionCloseError("AUTOGENESIS_SESSION_CLOSE_TIMEOUT")

        self._settle_session_close()

    def get_app(self):
        if self._driver and self._is_session_valid():
            return self._driver

        self.app_launch()
        return self._driver

    def push_data_to_gen_code(self, caller, tool_name, step, scenario, param=None):
        if self.gen_code_id:
            data = {
                "gen_code_id": self.gen_code_id,
                "tool_name": tool_name,
                "step": step,
                "scenario": scenario,
                "param": param,
                "caller": caller,
            }
            self.gen_code_cache.append(data)
        else:
            logger.warning("No gen_code_id found. Cannot push data.")

    def clear_gen_code_cache(self):
        self.gen_code_cache.clear()
        self.gen_code_id = None
        self.pending_write = None
        self.recording_warnings.clear()
        self.proposed_changes = None
        self.header_code = ""

    def is_keyboard_shown(self) -> bool | None:
        """
        Check if the keyboard is currently displayed.

        Returns:
            bool: True if the keyboard is shown, False otherwise.
        """
        if self._driver and self._is_session_valid():
            try:
                if self.device in ["android", "ios"]:
                    return self._driver.is_keyboard_shown()
                else:
                    logger.warning("Operation diagnostic; private details omitted")
                    return None
            except Exception as e:
                logger.warning("Operation diagnostic; private details omitted")
                return None
        else:
            logger.warning("Driver session is not valid. Cannot check keyboard visibility.")
            return None
