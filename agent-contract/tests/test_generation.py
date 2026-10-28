from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from autogenesis_agent_contract import (
    GENERATION_APPROVAL_REQUIRED,
    GENERATION_DESTINATION_INVALID,
    GENERATION_PREVIEW_MISMATCH,
    GENERATION_PREVIEW_STALE,
    GENERATION_WRITE_FAILED,
    GenerationCommitError,
    commit_generation_preview,
    prepare_generation_preview,
    safe_secret_error,
)


def assert_code(code, call):
    with pytest.raises(GenerationCommitError) as caught:
        call()
    assert caught.value.code == code
    assert str(caught.value) == code

def test_generation_errors_are_payload_free_and_allowlisted():
    error = GenerationCommitError(GENERATION_PREVIEW_MISMATCH)
    assert str(error) == GENERATION_PREVIEW_MISMATCH
    assert safe_secret_error(f"wrapped: {error}") == GENERATION_PREVIEW_MISMATCH


def test_preview_is_read_only_and_commit_requires_exact_explicit_approval(tmp_path):
    project = tmp_path / "business"
    project.mkdir()
    destination = project / "features/steps/generated.py"
    preview = prepare_generation_preview(project, destination, "session-1", "generated()\n")

    assert not destination.parent.exists()
    assert preview.to_dict() == {
        "preview_id": preview.preview_id,
        "digest": preview.digest,
        "generation_id": "session-1",
        "destination": "features/steps/generated.py",
        "append_payload": "generated()\n",
        "base_sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        "base_exists": False,
    }
    with pytest.raises(FrozenInstanceError):
        preview.append_payload = "tampered()\n"
    assert_code(GENERATION_APPROVAL_REQUIRED, lambda: commit_generation_preview(
        preview, preview_id=preview.preview_id, digest=preview.digest, approved=False,
    ))
    assert_code(GENERATION_PREVIEW_MISMATCH, lambda: commit_generation_preview(
        preview, preview_id="wrong", digest=preview.digest, approved=True,
    ))
    assert not destination.parent.exists()

    committed = commit_generation_preview(
        preview, preview_id=preview.preview_id, digest=preview.digest, approved=True,
    )
    assert committed == "features/steps/generated.py"
    assert destination.read_bytes() == b"generated()\n"
    assert_code(GENERATION_PREVIEW_STALE, lambda: commit_generation_preview(
        preview, preview_id=preview.preview_id, digest=preview.digest, approved=True,
    ))


def test_base_file_change_invalidates_preview_without_writing(tmp_path):
    project = tmp_path / "business"
    project.mkdir()
    destination = project / "steps.py"
    destination.write_text("base\n", encoding="utf-8")
    preview = prepare_generation_preview(project, destination, "session-2", "approved\n")
    destination.write_text("changed\n", encoding="utf-8")

    assert_code(GENERATION_PREVIEW_STALE, lambda: commit_generation_preview(
        preview, preview_id=preview.preview_id, digest=preview.digest, approved=True,
    ))
    assert destination.read_text(encoding="utf-8") == "changed\n"


def test_destination_must_remain_inside_project_without_symlinks(tmp_path):
    project = tmp_path / "business"
    project.mkdir()
    outside = tmp_path / "outside.py"
    assert_code(GENERATION_DESTINATION_INVALID, lambda: prepare_generation_preview(
        project, outside, "session-3", "generated()\n",
    ))

    external = tmp_path / "external"
    external.mkdir()
    link = project / "linked"
    try:
        link.symlink_to(external, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation is unavailable")
    assert_code(GENERATION_DESTINATION_INVALID, lambda: prepare_generation_preview(
        project, link / "steps.py", "session-3", "generated()\n",
    ))
    assert not (external / "steps.py").exists()


def test_atomic_replace_failure_preserves_base_and_removes_temporary_file(tmp_path, monkeypatch):
    from autogenesis_agent_contract import generation

    project = tmp_path / "business"
    project.mkdir()
    destination = project / "steps.py"
    destination.write_bytes(b"base\n")
    preview = prepare_generation_preview(project, destination, "session-4", "generated()\n")

    def fail_replace(source, target):
        raise OSError("simulated interruption")

    monkeypatch.setattr(generation.os, "replace", fail_replace)
    assert_code(GENERATION_WRITE_FAILED, lambda: commit_generation_preview(
        preview, preview_id=preview.preview_id, digest=preview.digest, approved=True,
    ))
    assert destination.read_bytes() == b"base\n"
    assert list(project.glob(".steps.py.*.tmp")) == []
