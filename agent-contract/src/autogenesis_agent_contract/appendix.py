"""Load one bounded, explicit-root appendix and retain an immutable snapshot."""

import hashlib
import os
import stat
from dataclasses import dataclass, field
from pathlib import Path

from .errors import PROJECT_INSTRUCTIONS_INVALID, ContractError
from ._windows_appendix import WindowsAppendixError, load_windows_bytes

APPENDIX_PATH = ".autogenesis/instructions.md"
MAX_APPENDIX_BYTES = 64 * 1024


@dataclass(frozen=True, slots=True, init=False)
class ProjectAppendix:
    text: str = field(repr=False)
    sha256: str

    @classmethod
    def _snapshot(cls, raw: bytes) -> "ProjectAppendix":
        if len(raw) > MAX_APPENDIX_BYTES:
            raise ContractError(PROJECT_INSTRUCTIONS_INVALID, "appendix_too_large")
        try:
            text = raw.decode("utf-8")
        except UnicodeError:
            raise ContractError(PROJECT_INSTRUCTIONS_INVALID, "appendix_not_utf8") from None
        result = object.__new__(cls)
        object.__setattr__(result, "text", text)
        object.__setattr__(result, "sha256", hashlib.sha256(raw).hexdigest())
        return result


def _invalid(reason: str) -> ContractError:
    return ContractError(PROJECT_INSTRUCTIONS_INVALID, reason)


def _open_posix(root: Path, relative: Path, root_stat: os.stat_result) -> int:
    # Anchor every component to a held directory descriptor. Symlinks were
    # resolved inside root already; reject replacement links during the open.
    directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        opened = os.fstat(directory)
        if (opened.st_dev, opened.st_ino) != (root_stat.st_dev, root_stat.st_ino):
            raise _invalid("appendix_path_changed")
        for component in relative.parts[:-1]:
            child = os.open(
                component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory
            )
            os.close(directory)
            directory = child
        return os.open(
            relative.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory
        )
    finally:
        os.close(directory)


def _is_windows() -> bool:
    return os.name == "nt"


def load_project_appendix(project_root: str | os.PathLike[str]) -> ProjectAppendix | None:
    """Read only <absolute project_root>/.autogenesis/instructions.md.

    Missing means None. An invalid present path fails closed. No content is
    interpreted, expanded, followed as an include, or used in diagnostics.
    Windows uses held component handles instead of path resolution/containment.
    """
    if _is_windows():
        try:
            raw = load_windows_bytes(project_root, MAX_APPENDIX_BYTES)
            return None if raw is None else ProjectAppendix._snapshot(raw)
        except ContractError:
            raise
        except WindowsAppendixError as error:
            raise _invalid(error.reason) from None
        except (OSError, ValueError, TypeError, RuntimeError):
            raise _invalid("appendix_unreadable_or_unsafe") from None
    try:
        root = Path(project_root)
        if not root.is_absolute() or ".." in root.parts:
            raise _invalid("project_root_not_explicit")
        root = root.resolve(strict=True)
        root_stat = root.stat()
        if not stat.S_ISDIR(root_stat.st_mode):
            raise _invalid("project_root_not_directory")
        candidate = root / APPENDIX_PATH
        # Inspect intermediate links even if the leaf is absent. Dangling and
        # escaping links are invalid, rather than silently treated as missing.
        current = root
        for component in Path(APPENDIX_PATH).parts:
            current = current / component
            try:
                current.lstat()
            except FileNotFoundError:
                return None
            resolved = current.resolve(strict=True)
            if not resolved.is_relative_to(root):
                raise _invalid("appendix_outside_project")
        target = candidate.resolve(strict=True)
        relative = target.relative_to(root)
        if not relative.parts:
            raise _invalid("appendix_not_regular_file")
        descriptor = _open_posix(root, relative, root_stat)
        with os.fdopen(descriptor, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode):
                raise _invalid("appendix_not_regular_file")
            if info.st_size > MAX_APPENDIX_BYTES:
                raise _invalid("appendix_too_large")
            raw = stream.read(MAX_APPENDIX_BYTES + 1)
        return ProjectAppendix._snapshot(raw)
    except ContractError:
        raise
    except (OSError, ValueError, TypeError, RuntimeError):
        raise _invalid("appendix_unreadable_or_unsafe") from None
