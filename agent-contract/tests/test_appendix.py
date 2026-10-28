import hashlib
import os
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

import autogenesis_agent_contract.appendix as implementation
from autogenesis_agent_contract import PROJECT_INSTRUCTIONS_INVALID, ContractError, load_project_appendix

def write_appendix(root, raw):
    parent = root / ".autogenesis"
    parent.mkdir(exist_ok=True)
    target = parent / "instructions.md"
    target.write_bytes(raw)
    return target


def link(target, destination, directory=False):
    destination.symlink_to(target, target_is_directory=directory)


def test_optional_absent_no_upward_or_alternate_discovery(tmp_path):
    write_appendix(tmp_path, b"Parent content must never be discovered")
    child = tmp_path / "business"
    child.mkdir()
    (child / "instructions.md").write_text("Alternate file must not load", encoding="utf-8")
    assert load_project_appendix(child) is None
    (child / ".autogenesis").mkdir()
    assert load_project_appendix(child) is None


def test_snapshot_exact_bytes_no_includes_expansion_or_templates(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOGENESIS_SYNTHETIC_VALUE", "EXPANDED_CANARY")
    raw = 'Domain café\r\n${AUTOGENESIS_SYNTHETIC_VALUE} {{ execute() }}\n@include https://invalid.example/policy\n'.encode()
    target = write_appendix(tmp_path, raw)
    snapshot = load_project_appendix(tmp_path)
    assert snapshot.text.encode() == raw
    assert snapshot.sha256 == hashlib.sha256(raw).hexdigest()
    assert "EXPANDED_CANARY" not in snapshot.text
    assert snapshot.text not in repr(snapshot)
    target.write_bytes(b"Changed later")
    assert snapshot.text.encode() == raw
    assert load_project_appendix(tmp_path).sha256 != snapshot.sha256
    with pytest.raises(FrozenInstanceError):
        snapshot.text = "replacement"


@pytest.mark.parametrize("raw", [b"", b"a" * 65536, "é".encode() * 32768])
def test_appendix_byte_boundary_is_inclusive(tmp_path, raw):
    write_appendix(tmp_path, raw)
    assert load_project_appendix(tmp_path).text.encode() == raw


@pytest.mark.parametrize("raw,reason", [
    (b"SYNTHETIC_PRIVATE_CANARY\xff", "appendix_not_utf8"),
    (b"a" * 65537, "appendix_too_large"),
    ("é".encode() * 32769, "appendix_too_large"),
])
def test_invalid_present_content_is_sanitized(tmp_path, raw, reason, caplog):
    write_appendix(tmp_path, raw)
    with pytest.raises(ContractError) as caught:
        load_project_appendix(tmp_path)
    assert caught.value.to_dict() == {"code": PROJECT_INSTRUCTIONS_INVALID, "reason": reason}
    assert "SYNTHETIC_PRIVATE_CANARY" not in str(caught.value) + repr(caught.value) + caplog.text


@pytest.mark.parametrize("kind", ["directory", "dangling", "external_file", "external_directory", "external_missing"])
@pytest.mark.skipif(os.name == "nt", reason="POSIX symlink cases; Windows reparse rejection is covered by native API mocks")
def test_unsafe_present_paths_fail_instead_of_becoming_empty(tmp_path, kind):
    root = tmp_path / "business"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "instructions.md").write_bytes(b"SYNTHETIC_OUTSIDE_CANARY")
    parent = root / ".autogenesis"
    if kind == "external_directory":
        link(outside, parent, True)
    elif kind == "external_missing":
        link(tmp_path / "missing-outside-directory", parent, True)
    else:
        parent.mkdir()
        target = parent / "instructions.md"
        if kind == "directory":
            target.mkdir()
        elif kind == "dangling":
            link(root / "missing", target)
        else:
            link(outside / "instructions.md", target)
    with pytest.raises(ContractError) as caught:
        load_project_appendix(root)
    assert caught.value.code == PROJECT_INSTRUCTIONS_INVALID
    assert "SYNTHETIC_OUTSIDE_CANARY" not in str(caught.value)


@pytest.mark.parametrize("directory", [False, True])
@pytest.mark.skipif(os.name == "nt", reason="Windows deliberately rejects every reparse component, including in-root links")
def test_in_root_symlinks_are_scoped_and_supported(tmp_path, directory):
    real = tmp_path / "domain"
    real.mkdir()
    (real / "instructions.md").write_bytes(b"Domain instructions")
    if directory:
        link(real, tmp_path / ".autogenesis", True)
    else:
        (tmp_path / ".autogenesis").mkdir()
        link(real / "instructions.md", tmp_path / ".autogenesis/instructions.md")
    assert load_project_appendix(tmp_path).text == "Domain instructions"


def test_explicit_root_rejects_traversal_relative_and_invalid_paths(tmp_path):
    for root in (".", "${HOME}", tmp_path / "child/../", tmp_path / "missing", None):
        with pytest.raises(ContractError) as caught:
            load_project_appendix(root)
        assert caught.value.code == PROJECT_INSTRUCTIONS_INVALID


@pytest.mark.skipif(os.name == "nt", reason="POSIX nonblocking special-file check")
def test_fifo_is_rejected_without_waiting_for_a_writer(tmp_path):
    (tmp_path / ".autogenesis").mkdir()
    os.mkfifo(tmp_path / ".autogenesis/instructions.md")
    with pytest.raises(ContractError, match="appendix_not_regular_file"):
        load_project_appendix(tmp_path)


@pytest.mark.skipif(os.name == "nt", reason="POSIX directory descriptor race test")
def test_link_swap_between_resolve_and_open_is_rejected(tmp_path, monkeypatch):
    root = tmp_path / "business"
    root.mkdir()
    target = write_appendix(root, b"Scoped text")
    outside = tmp_path / "outside.md"
    outside.write_bytes(b"SYNTHETIC_OUTSIDE_CANARY")
    original = implementation._open_posix

    def swapped(root, relative, root_stat):
        target.unlink()
        target.symlink_to(outside)
        return original(root, relative, root_stat)

    monkeypatch.setattr(implementation, "_open_posix", swapped)
    with pytest.raises(ContractError):
        load_project_appendix(root)


