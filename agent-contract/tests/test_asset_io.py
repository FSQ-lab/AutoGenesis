import os
import stat
from types import SimpleNamespace

import pytest

import autogenesis_agent_contract._asset_io as asset_io
import autogenesis_agent_contract.contract as implementation
from autogenesis_agent_contract import CONTRACT_INTEGRITY_ERROR, ContractError, load_contract


@pytest.mark.parametrize("mode,attributes", [
    (stat.S_IFIFO, 0), (stat.S_IFSOCK, 0), (stat.S_IFCHR, 0),
    (stat.S_IFDIR, 0), (stat.S_IFLNK, 0), (stat.S_IFREG, 0x400),
])
def test_nonregular_and_reparse_assets_fail_before_open(tmp_path, monkeypatch, mode, attributes):
    target = tmp_path / "asset.md"
    original = asset_io.Path.lstat

    def metadata(path):
        if path == target:
            return SimpleNamespace(st_mode=mode, st_file_attributes=attributes, st_size=0)
        return original(path)

    def forbidden(*args, **kwargs):
        raise AssertionError("Nonregular assets must never be opened")

    monkeypatch.setattr(asset_io.Path, "lstat", metadata)
    monkeypatch.setattr(asset_io.os, "open", forbidden)
    with pytest.raises(asset_io.AssetReadError):
        asset_io.read_asset(tmp_path, "asset.md")


def test_asset_read_is_bounded_even_if_file_grows_after_stat(tmp_path, monkeypatch):
    target = tmp_path / "asset.md"
    target.write_bytes(b"small")
    original = os.fdopen
    requested = []

    class GrowingStream:
        def __init__(self, stream):
            self.stream = stream

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.stream.close()

        def fileno(self):
            return self.stream.fileno()

        def read(self, size):
            requested.append(size)
            with target.open("ab") as writer:
                writer.write(b"x" * 100)
            return self.stream.read(size)

    monkeypatch.setattr(asset_io.os, "fdopen", lambda descriptor, mode: GrowingStream(original(descriptor, mode)))
    with pytest.raises(asset_io.AssetReadError, match="asset_too_large"):
        asset_io.read_asset(tmp_path, "asset.md", 16)
    assert requested == [17]


@pytest.mark.parametrize("name,limit", [
    ("manifest.json", asset_io.MAX_MANIFEST_BYTES), ("core-policy.md", asset_io.MAX_ASSET_BYTES),
])
def test_oversized_packaged_input_is_rejected_before_hashing(tmp_path, monkeypatch, name, limit):
    target = tmp_path / name
    with target.open("wb") as stream:
        stream.truncate(limit + 1)

    def forbidden(*args, **kwargs):
        raise AssertionError("Oversized bytes must not reach hashing")

    monkeypatch.setattr(asset_io.os, "open", forbidden)
    with pytest.raises(asset_io.AssetReadError, match="asset_too_large"):
        asset_io.read_asset(tmp_path, name, limit)
    if name == "manifest.json":
        monkeypatch.setattr(implementation, "_assets_root", lambda: tmp_path)
        monkeypatch.setattr(implementation.hashlib, "sha256", forbidden)
        with pytest.raises(ContractError) as caught:
            load_contract()
        assert caught.value.code == CONTRACT_INTEGRITY_ERROR
        assert caught.value.reason == "asset_too_large"


@pytest.mark.skipif(os.name == "nt", reason="POSIX special-file asset check")
def test_fifo_manifest_is_rejected_without_blocking(tmp_path, monkeypatch):
    os.mkfifo(tmp_path / "manifest.json")
    monkeypatch.setattr(implementation, "_assets_root", lambda: tmp_path)
    with pytest.raises(ContractError) as caught:
        load_contract()
    assert caught.value.to_dict() == {"code": CONTRACT_INTEGRITY_ERROR, "reason": "asset_not_regular_file"}


def test_directory_manifest_is_rejected(tmp_path, monkeypatch):
    (tmp_path / "manifest.json").mkdir()
    monkeypatch.setattr(implementation, "_assets_root", lambda: tmp_path)
    with pytest.raises(ContractError) as caught:
        load_contract()
    assert caught.value.reason == "asset_not_regular_file"
