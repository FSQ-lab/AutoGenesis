# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

# tools/app_manager.py

from autogenesis_agent_contract import resolve
from .launch_errors import LaunchErrorCode, LaunchFailure
from dataclasses import dataclass
from enum import IntEnum
import ctypes
from ctypes import wintypes
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
_NOTEPAD_PACKAGE_FAMILY_NAME = "Microsoft.WindowsNotepad_8wekyb3d8bbwe"
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_ERROR_INSUFFICIENT_BUFFER = 122
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


def _timeout_error_code(deepest_state: _LaunchState) -> LaunchErrorCode:
    if deepest_state is _LaunchState.PROCESS_STARTED:
        return LaunchErrorCode.WINDOW_NOT_FOUND
    if deepest_state in (_LaunchState.WINDOW_FOUND, _LaunchState.CONNECTED):
        return LaunchErrorCode.WINDOW_BIND_FAILED
    if deepest_state is _LaunchState.EXISTS:
        return LaunchErrorCode.WINDOW_NOT_VISIBLE
    if deepest_state is _LaunchState.VISIBLE:
        return LaunchErrorCode.WINDOW_NOT_ENABLED
    return LaunchErrorCode.WINDOW_BIND_FAILED


class _LaunchTimeout(LaunchFailure):
    __slots__ = ("deepest_state",)

    def __init__(self, deepest_state: _LaunchState):
        self.deepest_state = deepest_state
        super().__init__(_timeout_error_code(deepest_state))


class _WindowAmbiguous(LaunchFailure):
    def __init__(self):
        super().__init__(LaunchErrorCode.WINDOW_AMBIGUOUS)


@dataclass(frozen=True)
class _WindowBinding:
    handle: int
    process_id: int
    runtime_id: tuple[int, ...]
    generation: int
    element_info: object
    window: object


class _WindowConnectionLost(LaunchFailure):
    def __init__(self):
        super().__init__(LaunchErrorCode.WINDOW_CONNECTION_LOST)



def _winerror(error: BaseException) -> int | None:
    value = getattr(error, "winerror", None)
    if isinstance(value, int):
        return value
    if error.args and isinstance(error.args[0], int):
        return error.args[0]
    return None

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

    @classmethod
    def _window_identity(cls, wrapper) -> tuple[int, int, tuple[int, ...]] | None:
        try:
            handle = int(wrapper.handle)
            process_id = int(wrapper.element_info.process_id)
            runtime_id = cls._runtime_id(wrapper.element_info)
        except Exception:
            return None
        if handle <= 0 or process_id <= 0 or not runtime_id:
            return None
        return handle, process_id, runtime_id


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

    @staticmethod
    def _matching_windows(config: dict):
        return Desktop(backend="uia").windows(
            title_re=config["window_title_re"],
            control_type="Window",
            visible_only=False,
            enabled_only=False,
        )

    @staticmethod
    def _all_windows():
        return Desktop(backend="uia").windows(
            control_type="Window",
            visible_only=False,
            enabled_only=False,
        )

    @staticmethod
    def _window_matches_title(candidate, title_pattern) -> bool:
        try:
            return title_pattern.match(candidate.window_text()) is not None
        except Exception:
            return False

    @staticmethod
    def _same_process_incarnation(process_id: int, created_at: float) -> bool:
        try:
            return abs(psutil.Process(process_id).create_time() - created_at) <= _PROCESS_TIME_TOLERANCE
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return False


    def _is_notepad_profile(self) -> bool:
        executable = self.config.get("exe")
        return (
            self.app_name.casefold() == "notepad"
            and isinstance(executable, str)
            and os.path.basename(executable).casefold() == "notepad.exe"
        )

    @staticmethod
    def _package_family_name(process_id: int) -> str | None:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.GetPackageFamilyName.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(wintypes.UINT),
            wintypes.LPWSTR,
        ]
        kernel32.GetPackageFamilyName.restype = wintypes.LONG
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        handle = kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, process_id)
        if not handle:
            return None
        try:
            length = wintypes.UINT(0)
            result = kernel32.GetPackageFamilyName(handle, ctypes.byref(length), None)
            if result != _ERROR_INSUFFICIENT_BUFFER or length.value == 0:
                return None
            value = ctypes.create_unicode_buffer(length.value)
            if kernel32.GetPackageFamilyName(handle, ctypes.byref(length), value) != 0:
                return None
            return value.value
        finally:
            kernel32.CloseHandle(handle)

    def _matches_configured_application(self, process_id: int, executable: str) -> bool:
        try:
            actual_executable = psutil.Process(process_id).exe()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return False
        if os.path.normcase(os.path.abspath(actual_executable)) == os.path.normcase(os.path.abspath(executable)):
            return True
        return (
            self._is_notepad_profile()
            and self._package_family_name(process_id) == _NOTEPAD_PACKAGE_FAMILY_NAME
        )

    @staticmethod
    def _dismiss_notepad_close_confirmation(main_window):
        buttons = [
            button
            for button in main_window.wrapper_object().descendants(control_type="Button")
            if button.element_info.automation_id == "SecondaryButton"
            and button.is_visible()
            and button.is_enabled()
        ]
        if len(buttons) != 1:
            raise RuntimeError("Notepad close confirmation was not unique.")
        buttons[0].invoke()


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

    def _bind_window(
        self,
        app,
        wrapper,
        authenticated_identity: tuple[int, int, tuple[int, ...]],
        authenticated_element_info,
    ):
        if (
            self._window_identity(wrapper) != authenticated_identity
            or wrapper.element_info != authenticated_element_info
        ):
            raise _WindowConnectionLost()
        handle, process_id, runtime_id = authenticated_identity

        self._session_generation += 1
        generation = self._session_generation
        window = self._window_for_identity(
            app,
            handle,
            process_id,
            runtime_id,
            authenticated_element_info,
            generation,
        )
        self._app = app
        self._binding = _WindowBinding(
            handle=handle,
            process_id=process_id,
            runtime_id=runtime_id,
            generation=generation,
            element_info=authenticated_element_info,
            window=window,
        )

    def _get_bound_window(self):
        binding = self._binding
        if (
            self._app is None
            or binding is None
            or binding.generation != self._session_generation
        ):
            raise _WindowConnectionLost()

        try:
            binding.window.wrapper_object()
            return binding.window
        except Exception:
            self._invalidate_binding()
            raise _WindowConnectionLost() from None


    async def _new_launch(self, args: list[str]):
        self._invalidate_binding()

        config = self.runtime_config()
        deadline = _monotonic() + self.launch_timeout_seconds
        valid_exe_path = config["exe"]

        try:
            title_pattern = re.compile(config["window_title_re"])
            baseline_windows = self._all_windows()
            baseline_identities = {
                identity
                for candidate in baseline_windows
                if (identity := self._window_identity(candidate)) is not None
            }
            singleton_processes = {}
            for candidate in baseline_windows:
                identity = self._window_identity(candidate)
                if identity is None or not self._window_matches_title(candidate, title_pattern):
                    continue
                if not self._matches_configured_application(identity[1], valid_exe_path):
                    continue
                try:
                    singleton_processes[identity[1]] = psutil.Process(identity[1]).create_time()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
        except Exception:
            raise LaunchFailure(LaunchErrorCode.WINDOW_BIND_FAILED) from None

        if _monotonic() >= deadline:
            raise _LaunchTimeout(_LaunchState.PROCESS_STARTED)

        # CreateProcess receives one Windows-escaped command line and retains the
        # launcher handle so transferred children can be authenticated after exit.
        cmd = subprocess.list2cmdline([valid_exe_path, *args])
        logger.info('[AppManager] Launching new [redacted]: [redacted]')
        try:
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
        except Exception as error:
            code = (
                LaunchErrorCode.ELEVATION_REQUIRED
                if _winerror(error) == 740
                else LaunchErrorCode.PROCESS_START_FAILED
            )
            raise LaunchFailure(code) from None
        thread_handle.Close()
        try:
            launched_created_at = win32process.GetProcessTimes(process_handle)["CreationTime"].timestamp()
        except Exception:
            process_handle.Close()
            raise LaunchFailure(LaunchErrorCode.PROCESS_START_FAILED) from None
        fallback_identity = None
        authenticated_selection = None
        authenticated_window = None
        deepest_state = _LaunchState.PROCESS_STARTED
        try:
            while _monotonic() < deadline:
                try:
                    if authenticated_selection is None:
                        candidates = self._matching_windows(config)
                        lineage = []
                        singleton = []
                        for candidate in candidates:
                            identity = self._window_identity(candidate)
                            if identity is None or identity in baseline_identities:
                                continue
                            process_id = identity[1]
                            if self._belongs_to_launch(
                                process_id,
                                int(launched_process_id),
                                launched_created_at,
                                process_handle,
                            ):
                                lineage.append((candidate, identity, candidate.element_info))
                            elif (
                                process_id in singleton_processes
                                and self._same_process_incarnation(process_id, singleton_processes[process_id])
                                and self._matches_configured_application(process_id, valid_exe_path)
                            ):
                                singleton.append((candidate, identity, candidate.element_info))
                        eligible = lineage + singleton
                        if len(eligible) > 1:
                            raise _WindowAmbiguous()
                        trusted = []
                        if lineage:
                            fallback_identity = None
                            trusted = [lineage[0]]
                        elif singleton:
                            candidate, identity, element_info = singleton[0]
                            if fallback_identity == identity:
                                trusted = [(candidate, identity, element_info)]
                            else:
                                fallback_identity = identity
                        else:
                            fallback_identity = None
                        if trusted:
                            wrapper, authenticated_identity, authenticated_element_info = trusted[0]
                            authenticated_selection = (
                                authenticated_identity,
                                authenticated_element_info,
                            )
                            if (
                                self._window_identity(wrapper) != authenticated_identity
                                or wrapper.element_info != authenticated_element_info
                            ):
                                raise _WindowConnectionLost()
                            deepest_state = max(deepest_state, _LaunchState.WINDOW_FOUND)
                            handle, process_id, runtime_id = authenticated_identity
                            app = Application(backend="uia").connect(handle=handle)
                            deepest_state = max(deepest_state, _LaunchState.CONNECTED)
                            main_window = self._window_for_identity(
                                app,
                                handle,
                                process_id,
                                runtime_id,
                                authenticated_element_info,
                            )
                            authenticated_window = (app, main_window)

                    if authenticated_selection is not None:
                        authenticated_identity, authenticated_element_info = authenticated_selection
                        app, main_window = authenticated_window
                        if not main_window.exists(timeout=0):
                            raise _WindowConnectionLost()
                        deepest_state = max(deepest_state, _LaunchState.EXISTS)
                        verified_wrapper = main_window.wrapper_object()
                        if (
                            self._window_identity(verified_wrapper) != authenticated_identity
                            or verified_wrapper.element_info != authenticated_element_info
                        ):
                            raise _WindowConnectionLost()
                        if verified_wrapper.is_visible():
                            deepest_state = max(deepest_state, _LaunchState.VISIBLE)
                            if verified_wrapper.is_enabled():
                                deepest_state = max(deepest_state, _LaunchState.ENABLED)
                                self._bind_window(
                                    app,
                                    verified_wrapper,
                                    authenticated_identity,
                                    authenticated_element_info,
                                )
                                deepest_state = _LaunchState.BOUND
                                if _monotonic() < deadline:
                                    logger.info('[AppManager] Launching new [redacted] using pywinauto: done')
                                    return
                                self._invalidate_binding()
                except (_WindowAmbiguous, _WindowConnectionLost):
                    raise
                except Exception:
                    if authenticated_selection is not None:
                        raise _WindowConnectionLost() from None
                    fallback_identity = None
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
        """Close only the application instance bound by this Runtime."""
        if self._binding is None or self._app is None:
            logger.info("No app session to close.")
            self._invalidate_binding()
            return
        try:
            main_window = self._get_bound_window()
            main_window.close()
            if main_window.exists(timeout=0.5):
                if not self._is_notepad_profile():
                    raise RuntimeError("Selected window requested close confirmation.")
                self._dismiss_notepad_close_confirmation(main_window)
                if main_window.exists(timeout=5):
                    raise RuntimeError("Selected Notepad window remained open.")
        except Exception:
            logger.error('[AppManager] Error closing app application: [redacted]')
            raise RuntimeError("AUTOGENESIS_APP_CLOSE_FAILED: selected application closure was not confirmed.") from None
        self._invalidate_binding()

    def release_binding(self):
        """Release Runtime-owned binding and transient state without closing the app."""
        self._invalidate_binding()
        self.is_executing = False
        self.gen_code_id = None
        self.gen_code_cache.clear()
        self.proposed_changes = None
        self.recording_warnings.clear()
        self.header_code = ""
        self.steps_dir = None
        self.step_file_target = None

    async def get_main_window(self, main_window_type: str = ""):
        if main_window_type == "screenshot_cn":
            return self.get_screenshot_window()

        try:
            return self._get_bound_window()
        except _WindowConnectionLost:
            logger.error("Verified main window binding is unavailable.")
            raise
    
    
    def get_screenshot_window(self):
        try:
            main_window = self._get_bound_window()
        except _WindowConnectionLost:
            logger.error('No verified app window binding found for screenshot.')
            raise

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
        self.recording_warnings.clear()
        self.header_code = ""
        self.steps_dir = None
        self.step_file_target = None
