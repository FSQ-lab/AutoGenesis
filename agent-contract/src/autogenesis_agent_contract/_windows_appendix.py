"""Local Windows appendix reads anchored to non-reparse component handles.

NtCreateFile supplies handle-relative opens unavailable in CreateFileW. Win32
handle metadata and ReadFile never resolve a path or compare path prefixes.
"""

import os
import re
from contextlib import ExitStack
from dataclasses import dataclass

FILE_SHARE_READ = 0x1
FILE_SHARE_WRITE = 0x2
FILE_SHARE_DELETE = 0x4
FILE_DIRECTORY_FILE = 0x1
FILE_NON_DIRECTORY_FILE = 0x40
FILE_SYNCHRONOUS_IO_NONALERT = 0x20
FILE_OPEN_REPARSE_POINT = 0x00200000
OBJ_DONT_REPARSE = 0x1000
FILE_ATTRIBUTE_DIRECTORY = 0x10
FILE_ATTRIBUTE_DEVICE = 0x40
FILE_ATTRIBUTE_REPARSE_POINT = 0x400
FILE_TYPE_DISK = 1
DIRECTORY_ACCESS = 0x001000A0  # SYNCHRONIZE | FILE_READ_ATTRIBUTES | FILE_TRAVERSE
FILE_READ_ACCESS = 0x00120089  # FILE_GENERIC_READ, including SYNCHRONIZE


class WindowsAppendixError(ValueError):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True)
class HandleInfo:
    attributes: int
    directory: bool
    size: int = 0
    file_type: int = FILE_TYPE_DISK
    delete_pending: bool = False


def _local_root(project_root) -> tuple[str, list[str]]:
    try:
        text = os.fspath(project_root)
    except TypeError:
        raise WindowsAppendixError("project_root_not_explicit") from None
    # Reject UNC, device namespaces, drive-relative paths, and malformed names
    # before even constructing the native API. No network/path probe occurs.
    if not isinstance(text, str) or re.match(r"^[A-Za-z]:[\\/]", text) is None:
        raise WindowsAppendixError("windows_root_not_local")
    tail = text[3:].replace("/", "\\").rstrip("\\")
    parts = tail.split("\\") if tail else []
    for part in parts:
        if (
            not part or part in {".", ".."} or part.endswith((".", " "))
            or any(ord(char) < 32 or char in ':<>"|?*' for char in part)
        ):
            raise WindowsAppendixError("project_root_not_explicit")
    return text[:2], parts


def _check(info: HandleInfo, directory: bool) -> None:
    if info.attributes & FILE_ATTRIBUTE_REPARSE_POINT:
        raise WindowsAppendixError("windows_reparse_point")
    if info.file_type != FILE_TYPE_DISK or info.attributes & FILE_ATTRIBUTE_DEVICE:
        raise WindowsAppendixError("appendix_not_regular_file")
    if info.directory != directory or bool(info.attributes & FILE_ATTRIBUTE_DIRECTORY) != directory:
        raise WindowsAppendixError("windows_component_type_invalid")
    if info.delete_pending:
        raise WindowsAppendixError("windows_component_delete_pending")


def load_windows_bytes(project_root, limit: int) -> bytes | None:
    drive, parts = _local_root(project_root)
    api = _windows_api()
    # QueryDosDevice only queries the DOS-device namespace. Reject network,
    # SUBST, and other aliases rather than opening a possibly redirected drive.
    # Open the verified native volume name so a later drive remapping is inert.
    volume = api.volume(drive)
    if re.fullmatch(r"\\Device\\HarddiskVolume[0-9]+", volume) is None:
        raise WindowsAppendixError("windows_root_not_local")
    with ExitStack() as handles:
        def acquire(parent, name, directory):
            options = FILE_OPEN_REPARSE_POINT | FILE_SYNCHRONOUS_IO_NONALERT
            options |= FILE_DIRECTORY_FILE if directory else FILE_NON_DIRECTORY_FILE
            handle = api.open(
                parent, name, desired_access=DIRECTORY_ACCESS if directory else FILE_READ_ACCESS,
                share_access=FILE_SHARE_READ, options=options, attributes=OBJ_DONT_REPARSE,
            )
            handles.callback(api.close, handle)
            info = api.info(handle)
            _check(info, directory)
            return handle, info

        parent, _ = acquire(None, volume + "\\", True)
        # Retain ALL ancestors, the explicit project root, and .autogenesis.
        # No delete or write sharing: replacement/retagging conflicts fail closed.
        for component in parts:
            parent, _ = acquire(parent, component, True)
        try:
            parent, _ = acquire(parent, ".autogenesis", True)
        except FileNotFoundError:
            return None
        try:
            handle, info = acquire(parent, "instructions.md", False)
        except FileNotFoundError:
            return None
        if info.size < 0 or info.size > limit:
            raise WindowsAppendixError("appendix_too_large")
        content = bytearray()
        while True:
            count = min(8192, limit + 1 - len(content))
            chunk = api.read(handle, count)
            if not isinstance(chunk, bytes) or len(chunk) > count:
                raise WindowsAppendixError("windows_appendix_read_failed")
            content.extend(chunk)
            if len(content) > limit:
                raise WindowsAppendixError("appendix_too_large")
            if not chunk:
                return bytes(content)


def _windows_api():
    """Single mockable seam; native DLLs are loaded only after root validation."""
    return _WindowsAPI()


class _WindowsAPI:
    def __init__(self):
        import ctypes as c

        self.c = c
        self.kernel = c.WinDLL("kernel32", use_last_error=True)
        self.native = c.WinDLL("ntdll", use_last_error=True)

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

        self.UnicodeString, self.ObjectAttributes, self.IOStatus = UnicodeString, ObjectAttributes, IOStatus
        self.AttributeTag, self.StandardInfo = AttributeTag, StandardInfo
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
        self.kernel.ReadFile.argtypes = [c.c_void_p, c.c_void_p, c.c_uint32, c.POINTER(c.c_uint32), c.c_void_p]
        self.kernel.ReadFile.restype = c.c_int
        self.kernel.CloseHandle.argtypes = [c.c_void_p]
        self.kernel.CloseHandle.restype = c.c_int

    def volume(self, drive):
        buffer = self.c.create_unicode_buffer(32768)
        if not self.kernel.QueryDosDeviceW(drive, buffer, len(buffer)):
            raise WindowsAppendixError("windows_root_unreadable")
        return buffer.value

    def open(self, parent, name, *, desired_access, share_access, options, attributes):
        c = self.c
        encoded = name.encode("utf-16-le")
        if len(encoded) > 65532:
            raise WindowsAppendixError("project_root_not_explicit")
        buffer = c.create_string_buffer(encoded + b"\x00\x00")
        unicode = self.UnicodeString(len(encoded), len(encoded) + 2, c.cast(buffer, c.c_void_p))
        obj = self.ObjectAttributes(c.sizeof(self.ObjectAttributes), parent, c.pointer(unicode), attributes, None, None)
        handle, status_block = c.c_void_p(), self.IOStatus()
        status = self.native.NtCreateFile(
            c.byref(handle), desired_access, c.byref(obj), c.byref(status_block), None,
            0, share_access, 1, options, None, 0,  # FILE_OPEN; never create anything
        )
        if status != 0:
            if handle.value:
                self.close(handle.value)
            code = status & 0xFFFFFFFF
            if code in {0xC0000034, 0xC000003A}:  # NAME_NOT_FOUND / PATH_NOT_FOUND
                raise FileNotFoundError()
            if code == 0xC000050B:  # STATUS_REPARSE_POINT_ENCOUNTERED
                raise WindowsAppendixError("windows_reparse_point")
            raise WindowsAppendixError("windows_component_open_failed")
        if not handle.value:
            raise WindowsAppendixError("windows_component_open_failed")
        return handle.value

    def info(self, handle):
        c = self.c
        kind = self.kernel.GetFileType(handle)
        if kind != FILE_TYPE_DISK:
            return HandleInfo(0, False, file_type=kind)
        attributes, standard = self.AttributeTag(), self.StandardInfo()
        if not self.kernel.GetFileInformationByHandleEx(handle, 9, c.byref(attributes), c.sizeof(attributes)):
            raise WindowsAppendixError("windows_component_metadata_failed")
        if not self.kernel.GetFileInformationByHandleEx(handle, 1, c.byref(standard), c.sizeof(standard)):
            raise WindowsAppendixError("windows_component_metadata_failed")
        return HandleInfo(attributes.Attributes, bool(standard.Directory), standard.EndOfFile, kind, bool(standard.DeletePending))

    def read(self, handle, count):
        c = self.c
        buffer, received = c.create_string_buffer(count), c.c_uint32()
        if not self.kernel.ReadFile(handle, buffer, count, c.byref(received), None):
            if c.get_last_error() == 38:  # ERROR_HANDLE_EOF
                return b""
            raise WindowsAppendixError("windows_appendix_read_failed")
        return buffer.raw[:received.value]

    def close(self, handle):
        if not self.kernel.CloseHandle(handle):
            raise WindowsAppendixError("windows_handle_close_failed")
