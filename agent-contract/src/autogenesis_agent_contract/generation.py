"""Preview-bound, project-scoped atomic generated-code commits."""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import hmac
import json
import os
from pathlib import Path
import stat
import tempfile
import threading
import uuid


GENERATION_PREVIEW_REQUIRED = "AUTOGENESIS_GENERATION_PREVIEW_REQUIRED"
GENERATION_APPROVAL_REQUIRED = "AUTOGENESIS_GENERATION_APPROVAL_REQUIRED"
GENERATION_PREVIEW_MISMATCH = "AUTOGENESIS_GENERATION_PREVIEW_MISMATCH"
GENERATION_PREVIEW_STALE = "AUTOGENESIS_GENERATION_PREVIEW_STALE"
GENERATION_DESTINATION_INVALID = "AUTOGENESIS_GENERATION_DESTINATION_INVALID"
GENERATION_WRITE_FAILED = "AUTOGENESIS_GENERATION_WRITE_FAILED"


class GenerationCommitError(ValueError):
    """Stable, payload-free generation workflow failure."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(slots=True)
class _CommitState:
    committed: bool = False
    lock: threading.Lock = field(default_factory=threading.Lock)


@dataclass(frozen=True, slots=True)
class GenerationPreview:
    """Immutable approval data plus private commit state.

    Callers may retain only :meth:`to_dict`; the private paths and state remain
    process-local and never cross the MCP interface.
    """

    preview_id: str
    digest: str
    generation_id: str
    destination: str
    append_payload: str
    base_sha256: str
    base_exists: bool
    _project_root: Path = field(repr=False, compare=False)
    _target: Path = field(repr=False, compare=False)
    _state: _CommitState = field(default_factory=_CommitState, repr=False, compare=False)

    def to_dict(self) -> dict[str, object]:
        return {
            "preview_id": self.preview_id,
            "digest": self.digest,
            "generation_id": self.generation_id,
            "destination": self.destination,
            "append_payload": self.append_payload,
            "base_sha256": self.base_sha256,
            "base_exists": self.base_exists,
        }


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()

def _preview_digest(
    preview_id: str,
    generation_id: str,
    destination: str,
    base_exists: bool,
    base_sha256: str,
    append_payload: str,
) -> str:
    frame = {
        "base_exists": base_exists,
        "base_sha256": base_sha256,
        "destination": destination,
        "generation_id": generation_id,
        "payload_sha256": _sha256(append_payload.encode("utf-8")),
        "preview_id": preview_id,
        "version": 1,
    }
    return _sha256(json.dumps(frame, sort_keys=True, separators=(",", ":")).encode("utf-8"))


def _invalid_destination() -> GenerationCommitError:
    return GenerationCommitError(GENERATION_DESTINATION_INVALID)


def _validated_target(project_root: Path, destination: str | os.PathLike[str]) -> Path:
    try:
        root = project_root.resolve(strict=True)
        if not root.is_dir():
            raise _invalid_destination()
        requested = Path(destination)
        candidate = requested if requested.is_absolute() else root / requested
        lexical = Path(os.path.abspath(os.fspath(candidate)))
        lexical_relative = lexical.relative_to(root)
        if not lexical_relative.parts:
            raise _invalid_destination()

        current = root
        for part in lexical_relative.parts:
            current /= part
            if current.is_symlink():
                raise _invalid_destination()

        resolved = candidate.resolve(strict=False)
        resolved.relative_to(root)
        if resolved == root or resolved.exists() and not resolved.is_file():
            raise _invalid_destination()
        return resolved
    except GenerationCommitError:
        raise
    except (OSError, RuntimeError, TypeError, ValueError):
        raise _invalid_destination() from None


def _snapshot(target: Path) -> tuple[bool, bytes]:
    try:
        if not target.exists():
            return False, b""
        if target.is_symlink() or not target.is_file():
            raise _invalid_destination()
        return True, target.read_bytes()
    except GenerationCommitError:
        raise
    except OSError:
        raise _invalid_destination() from None


def prepare_generation_preview(
    project_root: str | os.PathLike[str],
    destination: str | os.PathLike[str],
    generation_id: str,
    append_payload: str,
) -> GenerationPreview:
    """Bind complete append bytes to session, destination, and base-file state.

    This function is read-only: it never creates the destination or its parent.
    """

    if not isinstance(generation_id, str) or not generation_id:
        raise GenerationCommitError(GENERATION_PREVIEW_REQUIRED)
    if not isinstance(append_payload, str) or not append_payload:
        raise GenerationCommitError(GENERATION_PREVIEW_REQUIRED)

    target = validate_generation_destination(project_root, destination)
    root = Path(project_root).resolve(strict=True)
    base_exists, base = _snapshot(target)
    base_sha256 = _sha256(base)
    preview_id = uuid.uuid4().hex
    relative = target.relative_to(root).as_posix()
    digest = _preview_digest(
        preview_id,
        generation_id,
        relative,
        base_exists,
        base_sha256,
        append_payload,
    )
    return GenerationPreview(
        preview_id=preview_id,
        digest=digest,
        generation_id=generation_id,
        destination=relative,
        append_payload=append_payload,
        base_sha256=base_sha256,
        base_exists=base_exists,
        _project_root=root,
        _target=target,
    )

def validate_generation_destination(
    project_root: str | os.PathLike[str],
    destination: str | os.PathLike[str],
) -> Path:
    """Return the canonical destination or reject escape and symlink paths."""

    return _validated_target(Path(project_root), destination)



def _base_matches(preview: GenerationPreview) -> tuple[bool, bytes]:
    exists, base = _snapshot(preview._target)
    return exists == preview.base_exists and hmac.compare_digest(_sha256(base), preview.base_sha256), base


def _sync_directory(directory: Path) -> None:
    try:
        descriptor = os.open(directory, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)


def commit_generation_preview(
    preview: GenerationPreview | None,
    *,
    preview_id: str,
    digest: str,
    approved: bool,
) -> str:
    """Atomically commit exactly one approved preview and invalidate it."""

    if preview is None:
        raise GenerationCommitError(GENERATION_PREVIEW_REQUIRED)
    if approved is not True:
        raise GenerationCommitError(GENERATION_APPROVAL_REQUIRED)
    if not isinstance(preview_id, str) or not isinstance(digest, str):
        raise GenerationCommitError(GENERATION_PREVIEW_MISMATCH)
    expected_digest = _preview_digest(
        preview.preview_id,
        preview.generation_id,
        preview.destination,
        preview.base_exists,
        preview.base_sha256,
        preview.append_payload,
    )
    if (
        not hmac.compare_digest(preview.preview_id, preview_id)
        or not hmac.compare_digest(preview.digest, digest)
        or not hmac.compare_digest(preview.digest, expected_digest)
    ):
        raise GenerationCommitError(GENERATION_PREVIEW_MISMATCH)

    with preview._state.lock:
        if preview._state.committed:
            raise GenerationCommitError(GENERATION_PREVIEW_STALE)
        target = _validated_target(preview._project_root, preview._target)
        if target != preview._target:
            raise GenerationCommitError(GENERATION_DESTINATION_INVALID)
        matches, base = _base_matches(preview)
        if not matches:
            raise GenerationCommitError(GENERATION_PREVIEW_STALE)

        temporary: Path | None = None
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            if _validated_target(preview._project_root, target) != target:
                raise _invalid_destination()
            matches, latest_base = _base_matches(preview)
            if not matches or latest_base != base:
                raise GenerationCommitError(GENERATION_PREVIEW_STALE)

            descriptor, temporary_name = tempfile.mkstemp(
                dir=target.parent,
                prefix=f".{target.name}.",
                suffix=".tmp",
            )
            temporary = Path(temporary_name)
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(base)
                stream.write(preview.append_payload.encode("utf-8"))
                stream.flush()
                os.fsync(stream.fileno())
            if preview.base_exists:
                os.chmod(temporary, stat.S_IMODE(target.stat().st_mode))

            if _validated_target(preview._project_root, target) != target:
                raise _invalid_destination()
            matches, latest_base = _base_matches(preview)
            if not matches or latest_base != base:
                raise GenerationCommitError(GENERATION_PREVIEW_STALE)
            os.replace(temporary, target)
            temporary = None
            _sync_directory(target.parent)
            preview._state.committed = True
            return preview.destination
        except GenerationCommitError:
            raise
        except OSError:
            raise GenerationCommitError(GENERATION_WRITE_FAILED) from None
        finally:
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass
