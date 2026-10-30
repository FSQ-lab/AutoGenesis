# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

# tools/app_manager.py

from autogenesis_agent_contract import resolve
from dataclasses import dataclass
from enum import IntEnum
import asyncio
import os
import re
import psutil
import time
import logging
import subprocess
from pywinauto import Application, Desktop
import win32process
from pywinauto.findwindows import ElementNotFoundError



logger = logging.getLogger(__name__)
            
_WINDIR_REFERENCE = re.compile(r"%WINDIR%", re.IGNORECASE)
_PROCESS_TIME_TOLERANCE = 0.01
_DEFAULT_LAUNCH_TIMEOUT_SECONDS = 15
_POLL_INTERVAL_SECONDS = 0.5
_monotonic = time.monotonic
_sleep = asyncio.sleep


class _LaunchState(IntEnum):
    PROCESS_STARTED = 1
    WINDOW_FOUND = 2
    CONNECTED = 3
    EXISTS = 4
    VISIBLE = 5
    ENABLED = 6
    BOUND = 7


class _LaunchTimeout(RuntimeError):
    def __init__(self, deepest_state: _LaunchState):
        self.deepest_state = deepest_state
        super().__init__("The application did not become ready before the launch deadline.")


class _WindowAmbiguous(RuntimeError):
    pass

@dataclass(frozen=True)
class _WindowBinding:
    handle: int
    process_id: int
    runtime_id: tuple[int, ...]
    generation: int
    element_info: object
    window: object


class _WindowConnectionLost(RuntimeError):
    pass




def _expand_environment(value):
    """Expand embedded environment references without mutating stored config."""
    if isinstance(value, dict):
        return {key: _expand_environment(child) for key, child in value.items()}
    if isinstance(value, list):
        return [_expand_environment(child) for child in value]
    if isinstance(value, str):
        # MCP stdio clients inherit SYSTEMROOT but may omit the equivalent
        # WINDIR variable used by existing Windows application profiles.
        system_root = os.environ.get("SYSTEMROOT")
        if system_root and not os.environ.get("WINDIR"):
            value = _WINDIR_REFERENCE.sub(lambda match: system_root, value)
        return os.path.expandvars(value)
    return value


class AppSessionManager:
    def __init__(self, app_conf: dict):
        # Retain literals and SecretRefs only; resolve plaintext per operation.
        self.config = app_conf.copy()
        self.launch_args = self.config.get('launch_args', []).copy()

        self.app_name = self.config.get('app_name', "")
        self.launch_timeout_seconds = self.config.get(
            "launch_timeout_seconds", _DEFAULT_LAUNCH_TIMEOUT_SECONDS
        )
        self._app = None  # Application instance
        self._binding: _WindowBinding | None = None
        self._session_generation = 0


        self.gen_code_id = None
        self.gen_code_cache = []
        self.proposed_changes = None  # Store proposed code changes
        self.pending_write = None
        self.recording_warnings = []
        self.header_code = ""
        self.steps_dir = None  # Directory for step files
        self.step_file_target = None  # Target step file for code generation

        self.is_executing = False

    def runtime_config(self) -> dict:
        return _expand_environment(resolve(self.config))

    def runtime_launch_args(self) -> list[str]:
        return _expand_environment(resolve(self.launch_args.copy()))

    def start_tool_execution(self, tool_name):
        if self.is_executing:
            logger.warning('Tool [redacted] blocked: another tool is executing')
            return False
        self.is_executing = True
        logger.info('Tool [redacted] started execution')
        return True

    def finish_tool_execution(self, tool_name):
        self.is_executing = False
        logger.info('Tool [redacted] finished execution')

    def _invalidate_binding(self):
        self._session_generation += 1
        self._binding = None
        self._app = None

    @staticmethod
    def _runtime_id(element_info) -> tuple[int, ...]:
        value = element_info.runtime_id
        if not value:
            return ()
        if isinstance(value, int):
            return (value,)
        return tuple(int(part) for part in value)

    @staticmethod
    def _belongs_to_launch(
        process_id: int,
        launched_process_id: int,
        launched_created_at: float,
        launched_process_handle,
    ) -> bool:
        try:
            candidate_created_at = psutil.Process(process_id).create_time()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return False
        if candidate_created_at + _PROCESS_TIME_TOLERANCE < launched_created_at:
            return False

        current_process_id = process_id
        visited = set()
        while current_process_id > 0 and current_process_id not in visited:
            if current_process_id == launched_process_id:
                try:
                    current_created_at = psutil.Process(current_process_id).create_time()
                except psutil.NoSuchProcess:
                    exit_time = win32process.GetProcessTimes(launched_process_handle)["ExitTime"].timestamp()
                    return (
                        launched_created_at <= candidate_created_at + _PROCESS_TIME_TOLERANCE
                        and candidate_created_at <= exit_time + _PROCESS_TIME_TOLERANCE
                    )
                except psutil.AccessDenied:
                    return False
                return abs(current_created_at - launched_created_at) <= _PROCESS_TIME_TOLERANCE
            visited.add(current_process_id)
            try:
                current_process_id = int(psutil.Process(current_process_id).ppid())
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                return False
        return False


    def _window_for_identity(
        self,
        app,
        handle: int,
        process_id: int,
        runtime_id: tuple[int, ...],
        original_element_info,
        generation: int | None = None,
    ):
        def matches(candidate):
            try:
                return (
                    (generation is None or self._session_generation == generation)
                    and int(candidate.handle) == handle
                    and int(candidate.process_id) == process_id
                    and self._runtime_id(candidate) == runtime_id
                    and candidate == original_element_info
                )
            except Exception:
                return False

        return app.window(
            control_type="Window",
            visible_only=False,
            enabled_only=False,
            predicate_func=matches,
        )

    def _bind_window(self, app, wrapper):
        handle = int(wrapper.handle)
        process_id = int(wrapper.element_info.process_id)
        runtime_id = self._runtime_id(wrapper.element_info)
        if handle <= 0 or process_id <= 0 or not runtime_id:
            raise RuntimeError("Unable to bind the verified application window.")

        self._session_generation += 1
        generation = self._session_generation
        window = self._window_for_identity(
            app,
            handle,
            process_id,
            runtime_id,
            wrapper.element_info,
            generation,
        )
        self._app = app
        self._binding = _WindowBinding(
            handle=handle,
            process_id=process_id,
            runtime_id=runtime_id,
            generation=generation,
            element_info=wrapper.element_info,
            window=window,
        )

    def _get_bound_window(self):
        binding = self._binding
        if (
            self._app is None
            or binding is None
            or binding.generation != self._session_generation
        ):
            raise _WindowConnectionLost("No verified application window is bound.")

        try:
            binding.window.wrapper_object()
            return binding.window
        except Exception:
            self._invalidate_binding()
            raise _WindowConnectionLost("The verified application window is unavailable.") from None


    async def _new_launch(self, args: list[str]):
        self._invalidate_binding()
        self.kill_app_process_by_path()

        config = self.runtime_config()
        valid_exe_path = config["exe"]

        # CreateProcess receives one Windows-escaped command line and retains the
        # launcher handle so transferred children can be authenticated after exit.
        cmd = subprocess.list2cmdline([valid_exe_path, *args])
        deadline = _monotonic() + self.launch_timeout_seconds
        logger.info('[AppManager] Launching new [redacted]: [redacted]')
        process_handle, thread_handle, launched_process_id, _ = win32process.CreateProcess(
            None,
            cmd,
            None,
            None,
            False,
            0,
            None,
            None,
            win32process.STARTUPINFO(),
        )
        thread_handle.Close()
        launched_created_at = win32process.GetProcessTimes(process_handle)["CreationTime"].timestamp()
        deepest_state = _LaunchState.PROCESS_STARTED
        try:
            while _monotonic() < deadline:
                try:
                    candidates = Desktop(backend="uia").windows(
                        title_re=config["window_title_re"],
                        control_type="Window",
                        visible_only=False,
                        enabled_only=False,
                    )
                    trusted = [
                        candidate for candidate in candidates
                        if self._belongs_to_launch(
                            int(candidate.element_info.process_id),
                            int(launched_process_id),
                            launched_created_at,
                            process_handle,
                        )
                    ]
                    if len(trusted) > 1:
                        raise _WindowAmbiguous(
                            "The application profile matched multiple windows from this launch."
                        )
                    if trusted:
                        wrapper = trusted[0]
                        deepest_state = max(deepest_state, _LaunchState.WINDOW_FOUND)
                        app = Application(backend="uia").connect(handle=int(wrapper.handle))
                        deepest_state = max(deepest_state, _LaunchState.CONNECTED)
                        handle = int(wrapper.handle)
                        process_id = int(wrapper.element_info.process_id)
                        runtime_id = self._runtime_id(wrapper.element_info)
                        if handle <= 0 or process_id <= 0 or not runtime_id:
                            raise RuntimeError("Unable to identify the discovered application window.")
                        main_window = self._window_for_identity(
                            app,
                            handle,
                            process_id,
                            runtime_id,
                            wrapper.element_info,
                        )
                        if main_window.exists(timeout=0):
                            deepest_state = max(deepest_state, _LaunchState.EXISTS)
                            verified_wrapper = main_window.wrapper_object()
                            if verified_wrapper.is_visible():
                                deepest_state = max(deepest_state, _LaunchState.VISIBLE)
                                if verified_wrapper.is_enabled():
                                    deepest_state = max(deepest_state, _LaunchState.ENABLED)
                                    self._bind_window(app, verified_wrapper)
                                    deepest_state = _LaunchState.BOUND
                                    if _monotonic() < deadline:
                                        logger.info('[AppManager] Launching new [redacted] using pywinauto: done')
                                        return
                                    self._invalidate_binding()
                except _WindowAmbiguous:
                    raise
                except Exception:
                    logger.error('[AppManager] Launching new [redacted] readiness probe error: [redacted]')

                remaining = deadline - _monotonic()
                if remaining <= 0:
                    break
                await _sleep(min(_POLL_INTERVAL_SECONDS, remaining))
        finally:
            process_handle.Close()

        self._invalidate_binding()
        raise _LaunchTimeout(deepest_state)

    async def app_launch(
            self, 
            kill_existing: int = 0, 
            ):
            
        if kill_existing == 1:
            await self.app_close()

        if self._binding is not None:
            try:
                self._get_bound_window()
                return False
            except _WindowConnectionLost:
                logger.error('[AppManager] Existing app window binding was lost: [redacted]')
        args = self.runtime_launch_args()

        await self._new_launch(args=args)
        return True

    

    async def app_close(self):
        app = self._app
        if self._binding is not None and app is not None:
            try:
                main_window = self._get_bound_window()
                main_window.close()
                app.kill()
            except Exception:
                logger.error('[AppManager] Error closing app application: [redacted]')
            finally:
                self._invalidate_binding()
        else:
            logger.info("No app session to close.")
            self._invalidate_binding()

        self.kill_app_process_by_path()

    def kill_app_process_by_path(self):
        exe_path = os.path.normcase(os.path.normpath(self.runtime_config()["exe"]))
        killed = False

        for proc in psutil.process_iter(["pid", "name", "exe"]):
            try:
                proc_exe = proc.info["exe"]
                if proc_exe and os.path.normcase(os.path.normpath(proc_exe)) == exe_path:
                    logger.info('Killing existing app process: PID=[redacted], Exe=[redacted]')
                    proc.kill()
                    killed = True
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
            except Exception as e:
                logger.error('Error checking/killing process [redacted] [redacted]: [redacted]')
                continue

        if killed:
            time.sleep(2)
        else:
            logger.info("No existing app process found to kill.")

    async def get_main_window(self, main_window_type: str = ""):
        if main_window_type == "screenshot_cn":
            return self.get_screenshot_window()

        try:
            return self._get_bound_window()
        except _WindowConnectionLost:
            logger.error("Verified main window binding is unavailable.")
            raise RuntimeError("Verified main window binding is unavailable.") from None
    
    
    def get_screenshot_window(self):
        try:
            main_window = self._get_bound_window()
        except _WindowConnectionLost:
            logger.error('No verified app window binding found for screenshot.')
            raise RuntimeError("Verified main window binding is unavailable.") from None

        screenshot_window = main_window.child_window(
            title="",
            control_type="Pane",
            class_name="Chrome_WidgetWin_1",
            found_index=0,
        )
        if screenshot_window.exists(timeout=5):
            return screenshot_window

        logger.error("No screenshot window found.")
        return None

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
            pass

    def clear_gen_code_cache(self):
        self.gen_code_cache.clear()
        self.gen_code_id = None
        self.proposed_changes = None
        self.pending_write = None
        self.recording_warnings.clear()
        self.header_code = ""
        self.steps_dir = None
        self.step_file_target = None
