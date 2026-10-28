"""Bounded, regular-file-only reads shared by loading and release generation."""

import os
import stat
from pathlib import Path

MAX_MANIFEST_BYTES = 64 * 1024
MAX_ASSET_BYTES = 256 * 1024


class AssetReadError(ValueError):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def _plain(info: os.stat_result) -> bool:
    return not (
        stat.S_ISLNK(info.st_mode)
        or getattr(info, "st_file_attributes", 0) & 0x400  # FILE_ATTRIBUTE_REPARSE_POINT
    )


def read_asset(root, relative: str, limit: int = MAX_ASSET_BYTES) -> bytes:
    """Never open a known special file or issue an unbounded read.

    Installed wheel assets must be filesystem files, not a zip/custom Traversable.
    All components under the package asset root must be plain directories/files.
    """
    try:
        root = Path(root)
    except TypeError:
        raise AssetReadError("unsupported_asset_storage") from None
    try:
        parts = Path(relative)
        if parts.is_absolute() or ".." in parts.parts or not parts.parts:
            raise AssetReadError("invalid_asset_path")
        current = root
        info = current.lstat()
        if not _plain(info) or not stat.S_ISDIR(info.st_mode):
            raise AssetReadError("unsafe_asset_directory")
        for index, part in enumerate(parts.parts):
            current = current / part
            info = current.lstat()
            if not _plain(info):
                raise AssetReadError("unsafe_asset_path")
            if index < len(parts.parts) - 1 and not stat.S_ISDIR(info.st_mode):
                raise AssetReadError("unsafe_asset_directory")
        if not stat.S_ISREG(info.st_mode):
            raise AssetReadError("asset_not_regular_file")
        if info.st_size > limit:
            raise AssetReadError("asset_too_large")
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        descriptor = os.open(current, flags)
        with os.fdopen(descriptor, "rb") as stream:
            opened = os.fstat(stream.fileno())
            if not stat.S_ISREG(opened.st_mode) or not _plain(opened):
                raise AssetReadError("asset_not_regular_file")
            if (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino):
                raise AssetReadError("asset_changed_during_open")
            if opened.st_size > limit:
                raise AssetReadError("asset_too_large")
            raw = stream.read(limit + 1)
        if len(raw) > limit:
            raise AssetReadError("asset_too_large")
        return raw
    except (OSError, ValueError) as error:
        if isinstance(error, AssetReadError):
            raise
        raise AssetReadError("asset_unreadable") from None
