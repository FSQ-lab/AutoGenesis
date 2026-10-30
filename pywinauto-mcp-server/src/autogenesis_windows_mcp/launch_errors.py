"""Stable, secret-safe Windows application launch failure contract."""

from dataclasses import dataclass
from enum import Enum


class LaunchErrorCode(str, Enum):
    PROCESS_START_FAILED = "PROCESS_START_FAILED"
    ELEVATION_REQUIRED = "ELEVATION_REQUIRED"
    WINDOW_NOT_FOUND = "WINDOW_NOT_FOUND"
    WINDOW_AMBIGUOUS = "WINDOW_AMBIGUOUS"
    WINDOW_NOT_VISIBLE = "WINDOW_NOT_VISIBLE"
    WINDOW_NOT_ENABLED = "WINDOW_NOT_ENABLED"
    WINDOW_BIND_FAILED = "WINDOW_BIND_FAILED"
    WINDOW_CONNECTION_LOST = "WINDOW_CONNECTION_LOST"
    SNAPSHOT_FAILED = "SNAPSHOT_FAILED"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class LaunchStage(str, Enum):
    PROCESS_START = "process_start"
    WINDOW_DISCOVERY = "window_discovery"
    WINDOW_READINESS = "window_readiness"
    WINDOW_BINDING = "window_binding"
    WINDOW_CONNECTION = "window_connection"
    SNAPSHOT = "snapshot"
    INTERNAL = "internal"


@dataclass(frozen=True)
class _FailureSpec:
    stage: LaunchStage
    retryable: bool
    description: str


_FAILURE_SPECS = {
    LaunchErrorCode.PROCESS_START_FAILED: _FailureSpec(
        LaunchStage.PROCESS_START, False, "Application process could not be started."
    ),
    LaunchErrorCode.ELEVATION_REQUIRED: _FailureSpec(
        LaunchStage.PROCESS_START, False, "Application launch requires elevation."
    ),
    LaunchErrorCode.WINDOW_NOT_FOUND: _FailureSpec(
        LaunchStage.WINDOW_DISCOVERY,
        True,
        "Application window was not found before the launch deadline.",
    ),
    LaunchErrorCode.WINDOW_AMBIGUOUS: _FailureSpec(
        LaunchStage.WINDOW_DISCOVERY,
        False,
        "Application profile matched multiple launched windows.",
    ),
    LaunchErrorCode.WINDOW_NOT_VISIBLE: _FailureSpec(
        LaunchStage.WINDOW_READINESS,
        True,
        "Application window did not become visible before the launch deadline.",
    ),
    LaunchErrorCode.WINDOW_NOT_ENABLED: _FailureSpec(
        LaunchStage.WINDOW_READINESS,
        True,
        "Application window did not become enabled before the launch deadline.",
    ),
    LaunchErrorCode.WINDOW_BIND_FAILED: _FailureSpec(
        LaunchStage.WINDOW_BINDING,
        True,
        "Application window could not be bound before the launch deadline.",
    ),
    LaunchErrorCode.WINDOW_CONNECTION_LOST: _FailureSpec(
        LaunchStage.WINDOW_CONNECTION,
        True,
        "The verified application window is no longer available.",
    ),
    LaunchErrorCode.SNAPSHOT_FAILED: _FailureSpec(
        LaunchStage.SNAPSHOT, True, "Application snapshot extraction failed."
    ),
    LaunchErrorCode.INTERNAL_ERROR: _FailureSpec(
        LaunchStage.INTERNAL, False, "Application launch failed internally."
    ),
}


class LaunchFailure(RuntimeError):
    """Internal failure containing only a stable error-code enum."""

    __slots__ = ("code",)

    def __init__(self, code: LaunchErrorCode):
        self.code = code
        super().__init__(code.value)


def launch_failure_fields(error: BaseException) -> dict:
    """Serialize only fixed contract fields; unknown exceptions fail closed."""
    code = error.code if isinstance(error, LaunchFailure) else LaunchErrorCode.INTERNAL_ERROR
    spec = _FAILURE_SPECS[code]
    return {
        "error": spec.description,
        "error_code": code.value,
        "stage": spec.stage.value,
        "retryable": spec.retryable,
    }


def is_launch_failure_payload(value: object) -> bool:
    if not isinstance(value, dict):
        return False
    try:
        code = LaunchErrorCode(value.get("error_code"))
    except (TypeError, ValueError):
        return False
    spec = _FAILURE_SPECS[code]
    return (
        value.get("status") == "error"
        and value.get("error") == spec.description
        and value.get("stage") == spec.stage.value
        and value.get("retryable") is spec.retryable
    )
