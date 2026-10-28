"""Mock native handles on every runner; real Windows reads also use common tests."""

import hashlib
from dataclasses import replace

import pytest

import autogenesis_agent_contract.appendix as implementation
import autogenesis_agent_contract._windows_appendix as windows
from autogenesis_agent_contract import ContractError, PROJECT_INSTRUCTIONS_INVALID, load_project_appendix

ROOT = r"C:\Work\Project"
VOLUME = r"\Device\HarddiskVolume3"
PROJECT = ("Work", "Project")
DIRECTORY = PROJECT + (".autogenesis",)
FILE = DIRECTORY + ("instructions.md",)


class FakeWindowsAPI:
    def __init__(self, content=b"Domain instructions\n", size=None):
        directory = windows.HandleInfo(windows.FILE_ATTRIBUTE_DIRECTORY, True)
        self.nodes = {(): directory, ("Work",): directory, PROJECT: directory, DIRECTORY: directory}
        self.nodes[FILE] = windows.HandleInfo(0, False, len(content) if size is None else size)
        self.content = content
        self.volume_name = VOLUME
        self.live = {}
        self.opened = []
        self.closed = []
        self.reads = []
        self.offset = 0
        self.counter = 0

    def volume(self, drive):
        assert drive == "C:"
        return self.volume_name

    def open(self, parent, name, **flags):
        if parent is None:
            assert name == self.volume_name + "\\"
            key = ()
        else:
            assert parent in self.live
            key = self.live[parent] + (name,)
        self.opened.append({"key": key, "parent": parent, "name": name, **flags})
        if key not in self.nodes:
            raise FileNotFoundError()
        self.counter += 1
        self.live[self.counter] = key
        return self.counter

    def info(self, handle):
        return self.nodes[self.live[handle]]

    def read(self, handle, count):
        assert self.live[handle] == FILE
        # All ancestors, explicit root, and .autogenesis remain held during reads.
        assert set(self.live.values()) == {(), ("Work",), PROJECT, DIRECTORY, FILE}
        self.reads.append(count)
        result = self.content[self.offset:self.offset + count]
        self.offset += len(result)
        return result

    def close(self, handle):
        assert handle in self.live
        self.closed.append(handle)
        del self.live[handle]


@pytest.fixture
def native(monkeypatch):
    api = FakeWindowsAPI()
    monkeypatch.setattr(implementation, "_is_windows", lambda: True)
    monkeypatch.setattr(windows, "_windows_api", lambda: api)

    def forbidden(*args, **kwargs):
        raise AssertionError("Windows loading must not resolve or compare filesystem paths")

    monkeypatch.setattr(implementation, "Path", forbidden)
    return api


def test_ordinary_file_snapshot_and_component_replacement_flags(native):
    raw = "Domain café\r\nUse the sandbox.\n".encode("utf-8")
    native.content = raw
    native.nodes[FILE] = windows.HandleInfo(0, False, len(raw))
    snapshot = load_project_appendix(ROOT)
    assert snapshot.text.encode("utf-8") == raw
    assert snapshot.sha256 == hashlib.sha256(raw).hexdigest()
    assert not native.live
    assert native.closed == [5, 4, 3, 2, 1]
    assert [entry["key"] for entry in native.opened] == [(), ("Work",), PROJECT, DIRECTORY, FILE]
    for entry in native.opened:
        assert entry["share_access"] == windows.FILE_SHARE_READ
        assert not entry["share_access"] & (windows.FILE_SHARE_DELETE | windows.FILE_SHARE_WRITE)
        assert entry["options"] & windows.FILE_OPEN_REPARSE_POINT
        assert entry["options"] & windows.FILE_SYNCHRONOUS_IO_NONALERT
        assert entry["attributes"] == windows.OBJ_DONT_REPARSE
        if entry["key"] == FILE:
            assert entry["options"] & windows.FILE_NON_DIRECTORY_FILE
            assert entry["desired_access"] == windows.FILE_READ_ACCESS
        else:
            assert entry["options"] & windows.FILE_DIRECTORY_FILE
            assert entry["desired_access"] == windows.DIRECTORY_ACCESS


@pytest.mark.parametrize("missing", [DIRECTORY, FILE])
def test_optional_absent_file_or_directory_returns_none_and_closes_handles(native, missing):
    del native.nodes[missing]
    assert load_project_appendix(ROOT) is None
    assert not native.live and not native.reads


def test_missing_explicit_root_is_invalid_instead_of_absent(native):
    del native.nodes[PROJECT]
    with pytest.raises(ContractError) as caught:
        load_project_appendix(ROOT)
    assert caught.value.code == PROJECT_INSTRUCTIONS_INVALID
    assert not native.live and not native.reads


@pytest.mark.parametrize("key", [("Work",), PROJECT, DIRECTORY, FILE])
def test_junction_or_final_symlink_is_rejected_without_target_access(native, key, caplog):
    info = native.nodes[key]
    native.nodes[key] = replace(info, attributes=info.attributes | windows.FILE_ATTRIBUTE_REPARSE_POINT)
    # Targets may be local siblings or UNC shares. The fake deliberately exposes
    # no resolution API; neither path nor target may be requested by the loader.
    with pytest.raises(ContractError) as caught:
        load_project_appendix(ROOT)
    assert caught.value.to_dict() == {"code": PROJECT_INSTRUCTIONS_INVALID, "reason": "windows_reparse_point"}
    assert not native.live and not native.reads
    assert native.opened[-1]["key"] == key
    assert "Domain instructions" not in str(caught.value) + caplog.text


@pytest.mark.parametrize("junction", [False, True])
def test_case_sensitive_sibling_cannot_be_substituted_for_explicit_root(native, junction):
    sibling = ("Work", "PROJECT")
    native.nodes[sibling] = windows.HandleInfo(windows.FILE_ATTRIBUTE_DIRECTORY, True)
    if junction:
        native.nodes[PROJECT] = windows.HandleInfo(windows.FILE_ATTRIBUTE_DIRECTORY | windows.FILE_ATTRIBUTE_REPARSE_POINT, True)
    else:
        del native.nodes[PROJECT]
    with pytest.raises(ContractError):
        load_project_appendix(ROOT)
    assert all(entry["key"] != sibling for entry in native.opened)
    assert not native.live and not native.reads


@pytest.mark.parametrize("root", [
    r"\\server\share\project", "//server/share/project", r"\\?\UNC\server\share\project",
    r"\\.\C:\Work\Project", r"C:Work\Project", r"C:\Work\..\outside",
])
def test_unc_and_nonexplicit_roots_fail_before_any_native_call(monkeypatch, root, caplog):
    monkeypatch.setattr(implementation, "_is_windows", lambda: True)

    def forbidden():
        raise AssertionError("Invalid roots must not query a device or access a network")

    monkeypatch.setattr(windows, "_windows_api", forbidden)
    with pytest.raises(ContractError) as caught:
        load_project_appendix(root)
    assert caught.value.code == PROJECT_INSTRUCTIONS_INVALID
    assert root not in str(caught.value) + caplog.text


@pytest.mark.parametrize("target", [r"\Device\Mup\server\share", r"\??\C:\outside", r"\Device\LanmanRedirector\server\share"])
def test_remote_or_subst_drive_targets_are_never_opened(native, target):
    native.volume_name = target
    with pytest.raises(ContractError, match="windows_root_not_local"):
        load_project_appendix(ROOT)
    assert not native.opened and not native.reads


@pytest.mark.parametrize("info", [
    windows.HandleInfo(0, False, file_type=3),
    windows.HandleInfo(windows.FILE_ATTRIBUTE_DEVICE, False),
    windows.HandleInfo(windows.FILE_ATTRIBUTE_DIRECTORY, True),
    windows.HandleInfo(0, False, delete_pending=True),
])
def test_special_or_invalid_final_handles_are_rejected_before_read(native, info):
    native.nodes[FILE] = info
    with pytest.raises(ContractError):
        load_project_appendix(ROOT)
    assert not native.live and not native.reads


@pytest.mark.parametrize("size", [0, 65536])
def test_windows_byte_limit_is_inclusive(native, size):
    native.content = b"a" * size
    native.nodes[FILE] = windows.HandleInfo(0, False, size)
    assert load_project_appendix(ROOT).text.encode() == native.content
    assert all(0 < count <= 8192 for count in native.reads)
    assert not native.live


@pytest.mark.parametrize("reported_size", [0, 65537])
def test_oversized_content_is_bounded_even_when_metadata_underreports(native, reported_size):
    native.content = b"a" * 65537
    native.nodes[FILE] = windows.HandleInfo(0, False, reported_size)
    with pytest.raises(ContractError, match="appendix_too_large"):
        load_project_appendix(ROOT)
    assert native.offset <= 65537
    assert all(0 < count <= 8192 for count in native.reads)
    if reported_size > 65536:
        assert not native.reads
    assert not native.live


def test_invalid_utf8_is_sanitized_and_handles_are_closed(native, caplog):
    native.content = b"SYNTHETIC_WINDOWS_PRIVATE_CANARY\xff"
    native.nodes[FILE] = windows.HandleInfo(0, False, len(native.content))
    with pytest.raises(ContractError) as caught:
        load_project_appendix(ROOT)
    assert caught.value.to_dict() == {"code": PROJECT_INSTRUCTIONS_INVALID, "reason": "appendix_not_utf8"}
    assert "SYNTHETIC_WINDOWS_PRIVATE_CANARY" not in str(caught.value) + caplog.text
    assert not native.live
