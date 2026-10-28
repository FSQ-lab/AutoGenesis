"""Small scoped, atomic writer for generated repository artifacts."""

import os
import tempfile
from pathlib import Path


def atomic_write(root: Path, relative: str, content: bytes) -> None:
    root = root.resolve(strict=True)
    destination = root / relative
    destination.relative_to(root)
    if ".." in Path(relative).parts or Path(relative).is_absolute():
        raise ValueError("Generated path must be relative to its explicit root")
    current = root
    for component in Path(relative).parts:
        current = current / component
        if current.is_symlink():
            raise ValueError("Generated path must not contain symlinks")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.parent.resolve(strict=True).relative_to(root)
    descriptor, temporary = tempfile.mkstemp(prefix=".autogenesis-", dir=destination.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o644)
        os.replace(temporary, destination)
    finally:
        Path(temporary).unlink(missing_ok=True)
