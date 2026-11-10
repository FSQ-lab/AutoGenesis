"""Install verified AutoGenesis Skills without trusting mutable package paths."""

from __future__ import annotations

import argparse
import errno
import hashlib
import json
import os
import re
import secrets
import stat
import sys
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path, PureWindowsPath
from typing import Any

from autogenesis_agent_contract import (
    CONTRACT_INTEGRITY_ERROR, ContractError, load_appium_skills, load_contract,
)

from . import __version__

SKILLS = ("autogenesis",)
EXPECTED = {
    "autogenesis-agent-contract": "2.1.0",
    "autogenesis-appium-mcp": "0.5.0",
    "autogenesis-windows-mcp": "0.5.0",
}
EXPECTED_CONTRACT_MANIFEST = "33c1cf4b22d21c5cf33a012c78dbfe59265db65bbc9c6b94b22681289a04f79d"
_UNSAFE = "AUTOGENESIS_SKILL_DESTINATION_UNSAFE"
_CONFLICT = "AUTOGENESIS_SKILL_CONFLICT: existing Skill differs"
_INTEGRITY = "AUTOGENESIS_SKILL_INTEGRITY_ERROR"


class InstallError(RuntimeError):
    pass


def _host_packages() -> tuple[str, ...]:
    if sys.platform == "darwin":
        return ("autogenesis-agent-contract", "autogenesis-appium-mcp")
    if sys.platform == "win32":
        return (
            "autogenesis-agent-contract",
            "autogenesis-appium-mcp",
            "autogenesis-windows-mcp",
        )
    raise InstallError("AUTOGENESIS_PLATFORM_UNSUPPORTED: native macOS or Windows is required")


def _verify_packages(names: tuple[str, ...]) -> dict[str, str]:
    versions = {}
    for name in names:
        try:
            actual = metadata.version(name)
        except metadata.PackageNotFoundError:
            raise InstallError(f"AUTOGENESIS_PACKAGE_MISSING: {name}") from None
        if actual != EXPECTED[name]:
            raise InstallError(f"AUTOGENESIS_PACKAGE_MISMATCH: {name}")
        versions[name] = actual
    return versions

def _verified_contract():
    contract = load_contract()
    if (
        contract.identity.contract_version != EXPECTED["autogenesis-agent-contract"]
        or contract.identity.manifest_sha256 != EXPECTED_CONTRACT_MANIFEST
    ):
        raise InstallError("AUTOGENESIS_CONTRACT_MISMATCH")
    return contract


def _install_bytes() -> tuple[dict[str, str], dict[str, bytes]]:
    packages = _verify_packages(_host_packages())
    contract = _verified_contract()
    skills = {name: contract.read_skill(name) for name in SKILLS}
    if any(not isinstance(raw, bytes) or not raw.endswith(b"\n") or b"\r" in raw for raw in skills.values()):
        raise InstallError(_INTEGRITY)
    # The same verified Contract snapshot is supplied so this check cannot cause
    # a second Contract/package-resource load.
    load_appium_skills(contract)
    return packages, skills


def _safe_posix_parts(path: Path) -> tuple[str, ...]:
    if not path.is_absolute():
        raise InstallError("AUTOGENESIS_SKILL_DESTINATION_NOT_ABSOLUTE")
    parts = path.parts[1:]
    if any(part in {"", ".", ".."} for part in parts):
        raise InstallError(_UNSAFE)
    return parts


def _safe_windows_parts(path: Any) -> tuple[str, tuple[str, ...]]:
    value = os.fspath(path)
    parsed = PureWindowsPath(value)
    if not isinstance(value, str) or not parsed.is_absolute() or parsed.root != "\\" or not parsed.drive:
        raise InstallError("AUTOGENESIS_SKILL_DESTINATION_NOT_ABSOLUTE")
    if parsed.drive.startswith("\\") or len(parsed.drive) != 2 or parsed.drive[1] != ":":
        raise InstallError(_UNSAFE)
    parts = parsed.parts[1:]
    for part in parts:
        if (
            part in {"", ".", ".."}
            or part.endswith((".", " "))
            or any(ord(char) < 32 or char in ':<>"|?*\\/' for char in part)
        ):
            raise InstallError(_UNSAFE)
    return parsed.drive, parts


@dataclass
class _PosixFile:
    parent: int
    name: str
    temporary: str | None = None
    identity: tuple[int, int] | None = None
    linked: bool = False


@dataclass
class _PosixDirectory:
    parent: int
    name: str
    identity: tuple[int, int] | None = None


class _PosixTransaction:
    """Handle-anchored create-if-absent transaction for native macOS."""

    def __init__(self, root: Path):
        self.root = root
        self.parts = _safe_posix_parts(root)
        flags = os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_CLOEXEC", 0)
        self._root_fd = os.open("/", flags)
        self._directories: dict[tuple[str, ...], int] = {(): self._root_fd}
        self._directory_identity: dict[tuple[str, ...], tuple[int, int]] = {
            (): self._identity(os.fstat(self._root_fd))
        }
        self._created_directories: list[_PosixDirectory] = []
        self._files: list[_PosixFile] = []
        self._closed = False

    @staticmethod
    def _identity(info: os.stat_result) -> tuple[int, int]:
        return info.st_dev, info.st_ino

    @staticmethod
    def _directory_flags() -> int:
        return (
            os.O_RDONLY
            | os.O_DIRECTORY
            | os.O_NOFOLLOW
            | getattr(os, "O_CLOEXEC", 0)
        )

    @staticmethod
    def _file_flags() -> int:
        return os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NONBLOCK", 0)

    def _directory(self, parts: tuple[str, ...], create: bool) -> int | None:
        current = self._root_fd
        prefix: tuple[str, ...] = ()
        for component in parts:
            prefix += (component,)
            if prefix in self._directories:
                current = self._directories[prefix]
                continue
            try:
                child = os.open(component, self._directory_flags(), dir_fd=current)
                created = False
            except FileNotFoundError:
                if not create:
                    return None
                record = _PosixDirectory(current, component)
                self._created_directories.append(record)
                try:
                    os.mkdir(component, 0o755, dir_fd=current)
                    created = True
                except FileExistsError:
                    created = False
                    self._created_directories.remove(record)
                try:
                    child = os.open(component, self._directory_flags(), dir_fd=current)
                except OSError:
                    raise InstallError(_UNSAFE) from None
            except OSError:
                raise InstallError(_UNSAFE) from None
            info = os.fstat(child)
            if not stat.S_ISDIR(info.st_mode):
                os.close(child)
                raise InstallError(_UNSAFE)
            identity = self._identity(info)
            self._directories[prefix] = child
            self._directory_identity[prefix] = identity
            if created:
                record.identity = identity
            current = child
        return current

    @staticmethod
    def _read(descriptor: int, limit: int) -> bytes:
        os.lseek(descriptor, 0, os.SEEK_SET)
        result = bytearray()
        while len(result) <= limit:
            chunk = os.read(descriptor, min(8192, limit + 1 - len(result)))
            if not chunk:
                return bytes(result)
            result.extend(chunk)
        return bytes(result)

    def _opened_file(self, parent: int, name: str) -> int | None:
        try:
            descriptor = os.open(name, self._file_flags(), dir_fd=parent)
        except FileNotFoundError:
            return None
        except OSError:
            raise InstallError(_UNSAFE) from None
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode):
            os.close(descriptor)
            raise InstallError(_UNSAFE)
        return descriptor

    def preflight(self, relative: tuple[str, ...], raw: bytes) -> str:
        parent = self._directory(self.parts + relative[:-1], False)
        if parent is None:
            return "pending"
        descriptor = self._opened_file(parent, relative[-1])
        if descriptor is None:
            return "pending"
        try:
            if self._read(descriptor, len(raw)) == raw:
                return "unchanged"
        finally:
            os.close(descriptor)
        raise InstallError(_CONFLICT)

    @staticmethod
    def _random_name(prefix: str) -> str:
        return f".{prefix}-{secrets.token_hex(16)}"

    def create(self, relative: tuple[str, ...], raw: bytes) -> None:
        parent = self._directory(self.parts + relative[:-1], True)
        assert parent is not None
        record = _PosixFile(parent, relative[-1])
        self._files.append(record)  # Include the current object before commit/verification can fail.
        temporary = self._random_name("autogenesis-skill")
        record.temporary = temporary
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0)
        descriptor = os.open(temporary, flags, 0o600, dir_fd=parent)
        try:
            record.identity = self._identity(os.fstat(descriptor))
            view = memoryview(raw)
            while view:
                written = os.write(descriptor, view)
                if written <= 0:
                    raise OSError("short Skill write")
                view = view[written:]
            os.fsync(descriptor)
            os.fchmod(descriptor, 0o644)
        finally:
            os.close(descriptor)
        try:
            os.link(temporary, relative[-1], src_dir_fd=parent, dst_dir_fd=parent, follow_symlinks=False)
        except FileExistsError:
            raise InstallError(_CONFLICT) from None
        record.linked = True
        self._verify_record(record, raw)

    def _verify_record(self, record: _PosixFile, raw: bytes) -> None:
        descriptor = self._opened_file(record.parent, record.name)
        if descriptor is None:
            raise InstallError(_INTEGRITY)
        try:
            if self._identity(os.fstat(descriptor)) != record.identity or self._read(descriptor, len(raw)) != raw:
                raise InstallError(_INTEGRITY)
        finally:
            os.close(descriptor)

    def verify(self, plan: list[tuple[str, tuple[str, ...], bytes, str]]) -> None:
        for _name, relative, raw, _status in plan:
            parent = self._directory(self.parts + relative[:-1], False)
            if parent is None:
                raise InstallError(_INTEGRITY)
            descriptor = self._opened_file(parent, relative[-1])
            if descriptor is None:
                raise InstallError(_INTEGRITY)
            try:
                if self._read(descriptor, len(raw)) != raw:
                    raise InstallError(_INTEGRITY)
            finally:
                os.close(descriptor)
        self._verify_spelling()

    def _verify_spelling(self) -> None:
        for expected_parts, expected_identity in self._directory_identity.items():
            current = os.open("/", os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_CLOEXEC", 0))
            try:
                for component in expected_parts:
                    child = os.open(component, self._directory_flags(), dir_fd=current)
                    os.close(current)
                    current = child
                if self._identity(os.fstat(current)) != expected_identity:
                    raise InstallError(_UNSAFE)
            except (FileNotFoundError, NotADirectoryError, OSError):
                raise InstallError(_UNSAFE) from None
            finally:
                os.close(current)

    @staticmethod
    def _rename_exclusive(parent: int, source: str, destination: str) -> None:
        # macOS renameatx_np(RENAME_EXCL) is the directory equivalent of the
        # create-if-absent hard link used for files. It never replaces a name
        # that appeared concurrently during rollback.
        import ctypes as c

        library = c.CDLL(None, use_errno=True)
        rename = getattr(library, "renameatx_np", None)
        if rename is None:
            raise InstallError(_UNSAFE)
        rename.argtypes = [c.c_int, c.c_char_p, c.c_int, c.c_char_p, c.c_uint]
        rename.restype = c.c_int
        if rename(parent, os.fsencode(source), parent, os.fsencode(destination), 0x00000004) != 0:
            code = c.get_errno()
            if code == errno.ENOENT:
                raise FileNotFoundError(source)
            if code == errno.EEXIST:
                raise FileExistsError(destination)
            raise OSError(code, os.strerror(code))

    def _move_and_remove_exact(self, parent: int, name: str, identity: tuple[int, int], directory: bool = False) -> None:
        quarantine = self._random_name("autogenesis-rollback")
        try:
            self._rename_exclusive(parent, name, quarantine)
        except FileNotFoundError:
            return
        try:
            info = os.stat(quarantine, dir_fd=parent, follow_symlinks=False)
            exact = self._identity(info) == identity
            if exact:
                try:
                    if directory:
                        os.rmdir(quarantine, dir_fd=parent)
                    else:
                        os.unlink(quarantine, dir_fd=parent)
                    return
                except OSError as error:
                    if not directory or error.errno not in {errno.ENOTEMPTY, errno.EEXIST}:
                        raise
            # A concurrent replacement, or a transaction directory now containing
            # concurrent content, belongs back at the public name. A hard link is
            # create-if-absent, so a still later replacement is never overwritten.
            try:
                if directory:
                    self._rename_exclusive(parent, quarantine, name)
                else:
                    os.link(quarantine, name, src_dir_fd=parent, dst_dir_fd=parent, follow_symlinks=False)
                    os.unlink(quarantine, dir_fd=parent)
            except FileExistsError:
                pass
        except Exception:
            try:
                if directory:
                    self._rename_exclusive(parent, quarantine, name)
                else:
                    os.link(quarantine, name, src_dir_fd=parent, dst_dir_fd=parent, follow_symlinks=False)
                    os.unlink(quarantine, dir_fd=parent)
            except OSError:
                pass
            raise

    def rollback(self) -> None:
        for record in reversed(self._files):
            if record.linked and record.identity is not None:
                self._move_and_remove_exact(record.parent, record.name, record.identity)
            if record.temporary is not None and record.identity is not None:
                self._move_and_remove_exact(record.parent, record.temporary, record.identity)
        for directory in reversed(self._created_directories):
            if directory.identity is not None:
                self._move_and_remove_exact(directory.parent, directory.name, directory.identity, True)
        self.close()

    def commit(self) -> None:
        for record in self._files:
            if record.temporary is not None and record.identity is not None:
                self._move_and_remove_exact(record.parent, record.temporary, record.identity)
        self.close()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        for descriptor in reversed(tuple(dict.fromkeys(self._directories.values()))):
            try:
                os.close(descriptor)
            except OSError:
                pass


@dataclass
class _WindowsFile:
    handle: Any | None = None
    created: bool = False


@dataclass
class _WindowsDirectory:
    handle: Any | None = None
    created: bool = False

class _WindowsTransaction:
    """Parent-handle transaction; the native adapter rejects every reparse point."""

    def __init__(self, root: Any, api: Any | None = None):
        self.root = root
        self.drive, self.parts = _safe_windows_parts(root)
        self.api = api if api is not None else _windows_api()
        root_handle = self.api.open_root(self.drive)
        self._directories: dict[tuple[str, ...], Any] = {(): root_handle}
        self._created_directories: list[_WindowsDirectory] = []
        self._existing_files: list[Any] = []
        self._files: list[_WindowsFile] = []
        self._verified_handles: dict[tuple[str, ...], Any] = {}
        self._closed = False

    def _directory(self, parts: tuple[str, ...], create: bool) -> Any | None:
        current = self._directories[()]
        prefix: tuple[str, ...] = ()
        for component in parts:
            prefix += (component,)
            if prefix in self._directories:
                current = self._directories[prefix]
                continue
            try:
                child, _ = self.api.open_directory(current, component, create=False)
                record = None
            except FileNotFoundError:
                if not create:
                    return None
                record = _WindowsDirectory()
                self._created_directories.append(record)
                child, created = self.api.open_directory(current, component, create=True)
                record.handle = child
                record.created = created
            try:
                self.api.require_safe(child, directory=True)
            except BaseException:
                if record is None or not record.created:
                    self.api.close(child)
                    if record is not None:
                        record.handle = None
                raise
            self._directories[prefix] = child
            current = child
        return current

    def preflight(self, relative: tuple[str, ...], raw: bytes) -> str:
        parent = self._directory(self.parts + relative[:-1], False)
        if parent is None:
            return "pending"
        try:
            handle = self.api.open_file(parent, relative[-1])
        except FileNotFoundError:
            return "pending"
        try:
            self.api.require_safe(handle, directory=False)
        except BaseException:
            self.api.close(handle)
            raise
        self._existing_files.append(handle)  # Retain it to deny replacement/writes through commit.
        self._verified_handles[relative] = handle
        if self.api.read_all(handle, len(raw)) == raw:
            return "unchanged"
        raise InstallError(_CONFLICT)

    def create(self, relative: tuple[str, ...], raw: bytes) -> None:
        parent = self._directory(self.parts + relative[:-1], True)
        assert parent is not None
        record = _WindowsFile()
        self._files.append(record)
        try:
            record.handle = self.api.create_file(parent, relative[-1])
        except FileExistsError:
            raise InstallError(_CONFLICT) from None
        record.created = True
        self._verified_handles[relative] = record.handle
        self.api.require_safe(record.handle, directory=False)
        self.api.write_all(record.handle, raw)
        self.api.flush(record.handle)
        if self.api.read_all(record.handle, len(raw)) != raw:
            raise InstallError(_INTEGRITY)

    def verify(self, plan: list[tuple[str, tuple[str, ...], bytes, str]]) -> None:
        for _name, relative, raw, _status in plan:
            handle = self._verified_handles.get(relative)
            if handle is None or self.api.read_all(handle, len(raw)) != raw:
                raise InstallError(_INTEGRITY)

    def rollback(self) -> None:
        failure: BaseException | None = None
        for record in reversed(self._files):
            if record.created and record.handle is not None:
                try:
                    self.api.delete(record.handle, directory=False)
                except BaseException as error:
                    failure = failure or error
                finally:
                    try:
                        self.api.close(record.handle)
                    except OSError:
                        pass
                    record.handle = None
        for record in reversed(self._created_directories):
            if record.created and record.handle is not None:
                try:
                    self.api.delete(record.handle, directory=True)
                except BaseException as error:
                    failure = failure or error
                finally:
                    try:
                        self.api.close(record.handle)
                    except OSError:
                        pass
                    record.handle = None
        self.close()
        if failure is not None:
            raise failure

    def commit(self) -> None:
        self.close()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        handles = (
            self._existing_files
            + [record.handle for record in self._files if record.handle is not None]
            + list(reversed(tuple(dict.fromkeys(self._directories.values()))))
        )
        for handle in handles:
            try:
                self.api.close(handle)
            except OSError:
                pass


def _windows_api():
    return _NativeWindowsAPI()


class _NativeWindowsAPI:
    """Small NtCreateFile adapter loaded only on a validated native Windows path."""

    FILE_ATTRIBUTE_DIRECTORY = 0x10
    FILE_ATTRIBUTE_DEVICE = 0x40
    FILE_ATTRIBUTE_REPARSE_POINT = 0x400
    FILE_TYPE_DISK = 1

    def __init__(self):
        import ctypes as c

        self.c = c
        self.kernel = c.WinDLL("kernel32", use_last_error=True)
        self.native = c.WinDLL("ntdll", use_last_error=True)
        self._define_types()

    def _define_types(self) -> None:
        c = self.c

        class UnicodeString(c.Structure):
            _fields_ = [("Length", c.c_uint16), ("MaximumLength", c.c_uint16), ("Buffer", c.c_void_p)]

        class ObjectAttributes(c.Structure):
            _fields_ = [
                ("Length", c.c_uint32), ("RootDirectory", c.c_void_p),
                ("ObjectName", c.POINTER(UnicodeString)), ("Attributes", c.c_uint32),
                ("SecurityDescriptor", c.c_void_p), ("SecurityQualityOfService", c.c_void_p),
            ]

        class IOStatus(c.Structure):
            _fields_ = [("StatusOrPointer", c.c_void_p), ("Information", c.c_size_t)]

        class AttributeTag(c.Structure):
            _fields_ = [("Attributes", c.c_uint32), ("ReparseTag", c.c_uint32)]

        class StandardInfo(c.Structure):
            _fields_ = [
                ("AllocationSize", c.c_int64), ("EndOfFile", c.c_int64),
                ("NumberOfLinks", c.c_uint32), ("DeletePending", c.c_ubyte), ("Directory", c.c_ubyte),
            ]

        self.UnicodeString = UnicodeString
        self.ObjectAttributes = ObjectAttributes
        self.IOStatus = IOStatus
        self.AttributeTag = AttributeTag
        self.StandardInfo = StandardInfo
        self.kernel.QueryDosDeviceW.argtypes = [c.c_wchar_p, c.c_wchar_p, c.c_uint32]
        self.kernel.QueryDosDeviceW.restype = c.c_uint32
        self.native.NtCreateFile.argtypes = [
            c.POINTER(c.c_void_p), c.c_uint32, c.POINTER(ObjectAttributes), c.POINTER(IOStatus),
            c.c_void_p, c.c_uint32, c.c_uint32, c.c_uint32, c.c_uint32, c.c_void_p, c.c_uint32,
        ]
        self.native.NtCreateFile.restype = c.c_int32
        self.kernel.GetFileType.argtypes = [c.c_void_p]
        self.kernel.GetFileType.restype = c.c_uint32
        self.kernel.GetFileInformationByHandleEx.argtypes = [c.c_void_p, c.c_int, c.c_void_p, c.c_uint32]
        self.kernel.GetFileInformationByHandleEx.restype = c.c_int
        self.kernel.SetFilePointerEx.argtypes = [c.c_void_p, c.c_int64, c.c_void_p, c.c_uint32]
        self.kernel.SetFilePointerEx.restype = c.c_int
        self.kernel.ReadFile.argtypes = [c.c_void_p, c.c_void_p, c.c_uint32, c.POINTER(c.c_uint32), c.c_void_p]
        self.kernel.ReadFile.restype = c.c_int
        self.kernel.WriteFile.argtypes = [c.c_void_p, c.c_void_p, c.c_uint32, c.POINTER(c.c_uint32), c.c_void_p]
        self.kernel.WriteFile.restype = c.c_int
        self.kernel.FlushFileBuffers.argtypes = [c.c_void_p]
        self.kernel.FlushFileBuffers.restype = c.c_int
        self.kernel.SetFileInformationByHandle.argtypes = [c.c_void_p, c.c_int, c.c_void_p, c.c_uint32]
        self.kernel.SetFileInformationByHandle.restype = c.c_int
        self.kernel.CloseHandle.argtypes = [c.c_void_p]
        self.kernel.CloseHandle.restype = c.c_int

    def _open(self, parent: Any, name: str, *, directory: bool, disposition: int) -> tuple[Any, bool]:
        c = self.c
        encoded = name.encode("utf-16-le")
        if len(encoded) > 65532:
            raise InstallError(_UNSAFE)
        buffer = c.create_string_buffer(encoded + b"\x00\x00")
        unicode = self.UnicodeString(len(encoded), len(encoded) + 2, c.cast(buffer, c.c_void_p))
        obj = self.ObjectAttributes(c.sizeof(self.ObjectAttributes), parent, c.pointer(unicode), 0x1000, None, None)
        handle, status_block = c.c_void_p(), self.IOStatus()
        desired = 0x00100000 | 0x80  # SYNCHRONIZE | FILE_READ_ATTRIBUTES
        creating = disposition != 1
        if creating:
            desired |= 0x00010000  # DELETE, retained for exact-handle rollback
        desired |= 0x20 if directory else 0x1  # FILE_TRAVERSE or FILE_READ_DATA
        if creating and not directory:
            desired |= 0x2  # FILE_WRITE_DATA
        options = 0x00200000 | 0x20 | (0x1 if directory else 0x40)
        status = self.native.NtCreateFile(
            c.byref(handle), desired, c.byref(obj), c.byref(status_block), None,
            0, 0x1, disposition, options, None, 0,
        )
        if status != 0:
            if handle.value:
                self.close(handle.value)
            code = status & 0xFFFFFFFF
            if code in {0xC0000034, 0xC000003A}:
                raise FileNotFoundError()
            if code in {0xC0000035, 0xC00000BA}:
                raise FileExistsError()
            if code == 0xC000050B:
                raise InstallError(_UNSAFE)
            raise OSError("native Skill path open failed")
        if not handle.value:
            raise OSError("native Skill path open failed")
        return handle.value, status_block.Information == 2

    def open_root(self, drive: str) -> Any:
        c = self.c
        buffer = c.create_unicode_buffer(32768)
        if not self.kernel.QueryDosDeviceW(drive, buffer, len(buffer)):
            raise InstallError(_UNSAFE)
        volume = buffer.value
        import re
        if re.fullmatch(r"\\Device\\HarddiskVolume[0-9]+", volume) is None:
            raise InstallError(_UNSAFE)
        return self._open(None, volume + "\\", directory=True, disposition=1)[0]

    def open_directory(self, parent: Any, name: str, *, create: bool) -> tuple[Any, bool]:
        return self._open(parent, name, directory=True, disposition=3 if create else 1)

    def open_file(self, parent: Any, name: str) -> Any:
        return self._open(parent, name, directory=False, disposition=1)[0]

    def create_file(self, parent: Any, name: str) -> Any:
        return self._open(parent, name, directory=False, disposition=2)[0]

    def require_safe(self, handle: Any, *, directory: bool) -> None:
        c = self.c
        if self.kernel.GetFileType(handle) != self.FILE_TYPE_DISK:
            raise InstallError(_UNSAFE)
        attributes, standard = self.AttributeTag(), self.StandardInfo()
        if not self.kernel.GetFileInformationByHandleEx(handle, 9, c.byref(attributes), c.sizeof(attributes)):
            raise OSError("native Skill metadata failed")
        if not self.kernel.GetFileInformationByHandleEx(handle, 1, c.byref(standard), c.sizeof(standard)):
            raise OSError("native Skill metadata failed")
        if (
            attributes.Attributes & (self.FILE_ATTRIBUTE_REPARSE_POINT | self.FILE_ATTRIBUTE_DEVICE)
            or bool(attributes.Attributes & self.FILE_ATTRIBUTE_DIRECTORY) != directory
            or bool(standard.Directory) != directory
            or standard.DeletePending
        ):
            raise InstallError(_UNSAFE)

    def read_all(self, handle: Any, limit: int) -> bytes:
        c = self.c
        position = c.c_int64(0)
        if not self.kernel.SetFilePointerEx(handle, position, None, 0):
            raise OSError("native Skill seek failed")
        content = bytearray()
        while len(content) <= limit:
            count = min(8192, limit + 1 - len(content))
            buffer, received = c.create_string_buffer(count), c.c_uint32()
            if not self.kernel.ReadFile(handle, buffer, count, c.byref(received), None):
                if c.get_last_error() == 38:
                    break
                raise OSError("native Skill read failed")
            if not received.value:
                break
            content.extend(buffer.raw[:received.value])
        return bytes(content)

    def write_all(self, handle: Any, raw: bytes) -> None:
        c = self.c
        position = c.c_int64(0)
        if not self.kernel.SetFilePointerEx(handle, position, None, 0):
            raise OSError("native Skill seek failed")
        offset = 0
        while offset < len(raw):
            chunk = raw[offset:offset + 8192]
            buffer = c.create_string_buffer(chunk)
            written = c.c_uint32()
            if not self.kernel.WriteFile(handle, buffer, len(chunk), c.byref(written), None) or not written.value:
                raise OSError("native Skill write failed")
            offset += written.value

    def flush(self, handle: Any) -> None:
        if not self.kernel.FlushFileBuffers(handle):
            raise OSError("native Skill flush failed")

    def delete(self, handle: Any, *, directory: bool) -> None:
        flag = self.c.c_ubyte(1)
        if not self.kernel.SetFileInformationByHandle(handle, 4, self.c.byref(flag), self.c.sizeof(flag)):
            raise OSError("native Skill rollback failed")

    def close(self, handle: Any) -> None:
        if not self.kernel.CloseHandle(handle):
            raise OSError("native Skill close failed")


def _filesystem(skills_dir: Any):
    if sys.platform == "darwin":
        return _PosixTransaction(skills_dir)
    if sys.platform == "win32":
        return _WindowsTransaction(skills_dir)
    raise InstallError("AUTOGENESIS_PLATFORM_UNSUPPORTED: native macOS or Windows is required")

_LEGACY_SKILLS = ("autogenesis-setup", "autogenesis-run")


def _entry_exists(path: Path) -> bool:
    try:
        path.lstat()
    except FileNotFoundError:
        return False
    except OSError:
        raise InstallError("AUTOGENESIS_SKILL_DISCOVERY_UNSAFE") from None
    return True


def _require_single_discovery_scope(selected: Path, roots: tuple[Path, ...]) -> None:
    for root in roots:
        for name in (*SKILLS, *_LEGACY_SKILLS):
            if root == selected and name in SKILLS:
                continue
            if _entry_exists(root / name):
                raise InstallError("AUTOGENESIS_SKILL_DISCOVERY_CONFLICT")


def _selected_scope(scope: str, project_root: Path) -> tuple[Path, tuple[Path, ...]]:
    if scope not in {"user", "project"} or not project_root.is_absolute():
        raise InstallError("AUTOGENESIS_SKILL_SCOPE_INVALID")
    try:
        project_info = project_root.lstat()
    except OSError:
        raise InstallError("AUTOGENESIS_SKILL_SCOPE_INVALID") from None
    if not stat.S_ISDIR(project_info.st_mode) or stat.S_ISLNK(project_info.st_mode):
        raise InstallError("AUTOGENESIS_SKILL_SCOPE_INVALID")
    user = Path.home() / ".agents" / "skills"
    project = project_root / ".agents" / "skills"
    selected = user if scope == "user" else project
    return selected, (user, project)



def install(skills_dir: Path, *, discovery_roots: tuple[Path, ...] = ()) -> dict:
    # Platform rejection and all package/Contract/Appium verification precede any
    # destination probe or filesystem mutation.
    packages, raw_skills = _install_bytes()
    transaction = _filesystem(skills_dir)
    plan: list[tuple[str, tuple[str, ...], bytes, str]] = []
    try:
        if discovery_roots:
            _require_single_discovery_scope(skills_dir, discovery_roots)
        for name in SKILLS:
            raw = raw_skills[name]
            relative = (name, "SKILL.md")
            plan.append((name, relative, raw, transaction.preflight(relative, raw)))
        for _name, relative, raw, status in plan:
            if status == "pending":
                transaction.create(relative, raw)
        transaction.verify(plan)
        if discovery_roots:
            _require_single_discovery_scope(skills_dir, discovery_roots)
        transaction.commit()
    except BaseException:
        transaction.rollback()
        raise
    installed = {
        name: {
            "status": "installed" if status == "pending" else status,
            "path": str(skills_dir / name / "SKILL.md"),
            "sha256": hashlib.sha256(raw).hexdigest(),
        }
        for name, _relative, raw, status in plan
    }
    return {"status": "ready", "platform": sys.platform, "packages": packages, "skills": installed,
            "discovery_root": str(skills_dir)}


def _appium_metadata(bundle: Any) -> dict[str, Any]:
    return {
        "status": "ready",
        "source": bundle.source,
        "commit": bundle.commit,
        "license": bundle.license,
        "assets": dict(bundle.assets),
        "asset_count": len(bundle.assets),
        "node_majors": list(bundle.node_majors),
    }

def _appium_workflow_metadata(bundle: Any, workflow_id: str) -> dict[str, Any]:
    workflow = bundle.load_workflow(workflow_id)
    return {
        "status": "ready",
        "source": bundle.source,
        "commit": bundle.commit,
        "workflow_id": workflow.workflow_id,
        "entrypoint": workflow.entrypoint,
        "content": workflow.content.decode("utf-8"),
        "required_contexts": list(workflow.required_contexts),
        "optional_contexts": list(workflow.optional_contexts),
        "tools": list(workflow.tools),
        "assets": dict(workflow.assets),
    }



def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="autogenesis")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)
    command = subparsers.add_parser("install", help="install the host bundle's canonical Skill")
    command.add_argument(
        "--scope", choices=("user", "project"), default="user",
        help="Skill discovery scope (default: user)",
    )
    command.add_argument(
        "--project-root", type=Path, default=Path.cwd(),
        help="absolute business project root used for discovery precedence",
    )
    command.add_argument("--json", action="store_true", help="emit machine-readable result")
    appium_skills = subparsers.add_parser(
        "appium-skills", help="describe the verified official Appium Skills snapshot"
    )
    appium_skills.add_argument("--json", action="store_true", help="emit machine-readable result")
    appium_workflow = subparsers.add_parser(
        "appium-workflow", help="load one supported authenticated Appium workflow by ID"
    )
    appium_workflow.add_argument("workflow_id")
    appium_workflow.add_argument("--json", action="store_true", help="emit machine-readable result")
    reference = subparsers.add_parser(
        "reference", help="load one authenticated internal AutoGenesis reference by ID"
    )
    reference.add_argument("reference_id")
    reference.add_argument("--json", action="store_true", help="emit machine-readable result")
    appium_asset = subparsers.add_parser(
        "appium-asset", help="write one held verified Appium Skills asset to stdout"
    )
    appium_asset.add_argument("workflow_id")
    appium_asset.add_argument("relative_path")
    args = parser.parse_args(argv)
    binary_result: bytes | None = None
    try:
        if args.command == "install":
            selected, discovery_roots = _selected_scope(args.scope, args.project_root.expanduser())
            result = install(selected, discovery_roots=discovery_roots)
        elif args.command == "appium-skills":
            result = _appium_metadata(load_appium_skills(_verified_contract()))
        elif args.command == "appium-workflow":
            bundle = load_appium_skills(_verified_contract())
            result = _appium_workflow_metadata(bundle, args.workflow_id)
        elif args.command == "reference":
            contract = _verified_contract()
            content = contract.read_reference(args.reference_id)
            result = {
                "status": "ready",
                "reference_id": args.reference_id,
                "contract_identity": contract.identity.to_dict(),
                "content": content,
            }
        elif args.command == "appium-asset":
            bundle = load_appium_skills(_verified_contract())
            workflow = bundle.load_workflow(args.workflow_id)
            if args.relative_path not in workflow.assets:
                raise ContractError(CONTRACT_INTEGRITY_ERROR, "appium_asset_outside_workflow")
            binary_result = bundle.read_asset(args.relative_path)
            result = None
    except (ContractError, InstallError, OSError, ValueError) as error:
        if isinstance(error, ContractError):
            message = "AUTOGENESIS_CONTRACT_INTEGRITY_ERROR"
        else:
            message = str(error) if isinstance(error, InstallError) else "AUTOGENESIS_INSTALL_FAILED"
        if getattr(args, "json", False):
            print(json.dumps({"status": "error", "error": message}, sort_keys=True))
        else:
            print(message, file=sys.stderr)
        return 1
    if binary_result is not None:
        sys.stdout.buffer.write(binary_result)
        sys.stdout.buffer.flush()
    elif args.json:
        print(json.dumps(result, sort_keys=True))
    elif args.command == "install":
        print("AutoGenesis machine installation is ready.")
        for name, detail in result["skills"].items():
            print(f"{name}: {detail['status']} ({detail['path']})")
    else:
        print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
