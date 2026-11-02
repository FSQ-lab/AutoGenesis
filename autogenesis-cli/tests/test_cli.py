import hashlib
import json
import os
import sys
from pathlib import Path, PureWindowsPath

import pytest

from autogenesis_cli import cli


SKILL_BYTES = {
    "autogenesis": b"---\nname: autogenesis\n---\nheld skill\n",
}


class Contract:
    class Identity:
        contract_version = cli.EXPECTED["autogenesis-agent-contract"]
        manifest_sha256 = cli.EXPECTED_CONTRACT_MANIFEST

    identity = Identity()

    def __init__(self, skills=None):
        source = SKILL_BYTES if skills is None else skills
        self._skills = {name: bytes(raw) for name, raw in source.items()}
        self.reads = []

    def read_skill(self, name):
        self.reads.append(name)
        return self._skills[name]


class Bundle:
    source = "https://github.com/appium/skills"
    commit = "e907024c210fe024c956ed9c74146fc27b1dd013"
    license = "Apache-2.0"
    node_majors = (20, 22, 24)
    assets = {
        "skills/setup-mac2/SKILL.md": "0" * 64,
        "skills/setup-mac2/context/macos.md": "1" * 64,
    }
    def __init__(self, payloads=None):
        self.payloads = payloads or {name: (b"payload:" + name.encode()) for name in self.assets}
        self.assets = {name: str(index) * 64 for index, name in enumerate(self.payloads, start=1)}

    def read_asset(self, relative):
        if relative not in self.assets:
            raise cli.ContractError("AUTOGENESIS_CONTRACT_INTEGRITY_ERROR", "invalid_appium_asset_path")
        return self.payloads[relative]

    def load_workflow(self, workflow_id):
        if workflow_id != "setup-mac2":
            raise cli.ContractError("AUTOGENESIS_CONTRACT_INTEGRITY_ERROR", "unsupported_appium_workflow")
        return type("Workflow", (), {
            "workflow_id": workflow_id,
            "entrypoint": "skills/setup-mac2/SKILL.md",
            "content": b"official workflow\n",
            "required_contexts": ("contexts/platform/macos/profile.md",),
            "optional_contexts": (),
            "tools": ("tools/appium/setup/scripts/check-mac2-env.mjs",),
            "assets": {"skills/setup-mac2/SKILL.md": "0" * 64},
        })()


def ready(monkeypatch, contract=None, bundle=None):
    contract = contract or Contract()
    bundle = bundle or Bundle()
    monkeypatch.setattr(cli, "_verify_packages", lambda names: {name: cli.EXPECTED[name] for name in names})
    monkeypatch.setattr(cli, "load_contract", lambda: contract)
    calls = []

    def load_appium(verified=None):
        calls.append(verified)
        return bundle

    monkeypatch.setattr(cli, "load_appium_skills", load_appium)
    return contract, bundle, calls


def test_install_uses_one_contract_snapshot_and_is_idempotent(tmp_path, monkeypatch):
    contract, _bundle, calls = ready(monkeypatch)
    loads = []

    def load_contract():
        loads.append(contract)
        return contract

    monkeypatch.setattr(cli, "load_contract", load_contract)
    root = tmp_path / "skills"
    first = cli.install(root)
    second = cli.install(root)
    assert [target.read_bytes() for target in (root / name / "SKILL.md" for name in cli.SKILLS)] == [
        SKILL_BYTES[name] for name in cli.SKILLS
    ]
    assert {detail["status"] for detail in first["skills"].values()} == {"installed"}
    assert {detail["status"] for detail in second["skills"].values()} == {"unchanged"}
    assert loads == [contract, contract]
    assert contract.reads == list(cli.SKILLS) * 2
    assert calls == [contract, contract]


def test_package_bytes_swapped_after_contract_load_are_never_installed(tmp_path, monkeypatch):
    package_bytes = dict(SKILL_BYTES)
    contract = Contract(package_bytes)
    ready(monkeypatch, contract=contract)

    def load_once():
        package_bytes["autogenesis"] = b"modified package bytes\n"
        return contract

    monkeypatch.setattr(cli, "load_contract", load_once)
    root = tmp_path / "skills"
    cli.install(root)
    assert (root / "autogenesis" / "SKILL.md").read_bytes() == SKILL_BYTES["autogenesis"]


def test_appium_snapshot_failure_stops_before_destination_probe(tmp_path, monkeypatch):
    contract, _bundle, _calls = ready(monkeypatch)
    monkeypatch.setattr(
        cli,
        "load_appium_skills",
        lambda verified: (_ for _ in ()).throw(
            cli.ContractError("AUTOGENESIS_CONTRACT_INTEGRITY_ERROR", "modified snapshot")
        ),
    )
    root = tmp_path / "skills"
    with pytest.raises(cli.ContractError, match="modified snapshot"):
        cli.install(root)
    assert contract.reads == list(cli.SKILLS)
    assert not root.exists()

def test_contract_manifest_mismatch_stops_before_writes(tmp_path, monkeypatch):
    contract = Contract()
    contract.identity = type("Identity", (), {
        "contract_version": cli.EXPECTED["autogenesis-agent-contract"],
        "manifest_sha256": "0" * 64,
    })()
    ready(monkeypatch, contract=contract)
    root = tmp_path / "skills"
    with pytest.raises(cli.InstallError, match="CONTRACT_MISMATCH"):
        cli.install(root)
    assert not root.exists()


def test_unsupported_host_stops_before_contract_or_writes(tmp_path, monkeypatch):
    called = False

    def load_contract():
        nonlocal called
        called = True

    monkeypatch.setattr(cli, "load_contract", load_contract)
    monkeypatch.setattr(cli.sys, "platform", "linux")
    root = tmp_path / "skills"
    with pytest.raises(cli.InstallError, match="PLATFORM_UNSUPPORTED"):
        cli.install(root)
    assert not called
    assert not root.exists()


def test_relative_destination_is_rejected_without_resolution(monkeypatch):
    ready(monkeypatch)
    with pytest.raises(cli.InstallError, match="NOT_ABSOLUTE"):
        cli.install(Path("relative"))


def test_absolute_destination_spelling_is_preserved(tmp_path, monkeypatch):
    ready(monkeypatch)
    root = tmp_path / "skills"
    result = cli.install(root)
    assert result["skills"]["autogenesis"]["path"] == str(root / "autogenesis" / "SKILL.md")


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="requires symlinks")
def test_symlink_destination_ancestor_is_rejected(tmp_path, monkeypatch):
    ready(monkeypatch)
    external = tmp_path / "external"
    external.mkdir()
    root = tmp_path / "skills"
    root.symlink_to(external, target_is_directory=True)
    with pytest.raises(cli.InstallError, match="DESTINATION_UNSAFE"):
        cli.install(root)
    assert not list(external.iterdir())


def test_existing_skill_conflict_prevents_write(tmp_path, monkeypatch):
    ready(monkeypatch)
    root = tmp_path / "skills"
    target = root / "autogenesis" / "SKILL.md"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"user content\n")
    with pytest.raises(cli.InstallError, match="SKILL_CONFLICT"):
        cli.install(root)
    assert target.read_bytes() == b"user content\n"


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX descriptor race")
def test_conflict_appearing_after_preflight_is_never_overwritten(tmp_path, monkeypatch):
    ready(monkeypatch)
    root = tmp_path / "skills"
    root.mkdir()
    original = cli._PosixTransaction.create
    raced = False

    def create(transaction, relative, raw):
        nonlocal raced
        if not raced:
            raced = True
            target = root.joinpath(*relative)
            target.parent.mkdir(parents=True)
            target.write_bytes(b"concurrent owner\n")
        return original(transaction, relative, raw)

    monkeypatch.setattr(cli._PosixTransaction, "create", create)
    with pytest.raises(cli.InstallError, match="SKILL_CONFLICT"):
        cli.install(root)
    assert (root / "autogenesis" / "SKILL.md").read_bytes() == b"concurrent owner\n"


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX descriptor race")
def test_ancestor_swap_is_rejected_and_held_target_is_rolled_back(tmp_path, monkeypatch):
    ready(monkeypatch)
    root = tmp_path / "skills"
    moved = tmp_path / "held-original"
    root.mkdir()
    original = cli._PosixTransaction.create
    swapped = False

    def create(transaction, relative, raw):
        nonlocal swapped
        if not swapped:
            swapped = True
            root.rename(moved)
            root.mkdir()
            (root / "concurrent.txt").write_bytes(b"concurrent\n")
        return original(transaction, relative, raw)

    monkeypatch.setattr(cli._PosixTransaction, "create", create)
    with pytest.raises(cli.InstallError, match="DESTINATION_UNSAFE"):
        cli.install(root)
    assert (root / "concurrent.txt").read_bytes() == b"concurrent\n"
    assert not (moved / "autogenesis").exists()


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX descriptor rollback")
def test_failure_after_file_commit_rolls_back_current_file(tmp_path, monkeypatch):
    ready(monkeypatch)
    root = tmp_path / "skills"

    def fail_verification(self, record, raw):
        raise cli.InstallError(cli._INTEGRITY)

    monkeypatch.setattr(cli._PosixTransaction, "_verify_record", fail_verification)
    with pytest.raises(cli.InstallError, match="INTEGRITY_ERROR"):
        cli.install(root)
    assert not (root / "autogenesis").exists()




class FakeWindowsAPI:
    def __init__(self, directories=(), files=None, reparses=()):
        self.directories = set(directories)
        self.files = dict(files or {})
        self.reparses = set(reparses)
        self.created_files = []
        self.created_directories = []
        self.deleted = []
        self.closed = []

    def open_root(self, drive):
        return drive

    def open_directory(self, parent, name, *, create):
        handle = parent + "\\" + name
        if handle not in self.directories:
            if not create:
                raise FileNotFoundError
            self.directories.add(handle)
            self.created_directories.append(handle)
            return handle, True
        return handle, False

    def require_safe(self, handle, *, directory):
        if handle in self.reparses:
            raise cli.InstallError(cli._UNSAFE)

    def open_file(self, parent, name):
        handle = parent + "\\" + name
        if handle not in self.files:
            raise FileNotFoundError
        return handle

    def create_file(self, parent, name):
        handle = parent + "\\" + name
        if handle in self.files:
            raise FileExistsError
        self.files[handle] = b""
        self.created_files.append(handle)
        return handle

    def read_all(self, handle, limit):
        return self.files[handle][: limit + 1]

    def write_all(self, handle, raw):
        self.files[handle] = bytes(raw)

    def flush(self, handle):
        pass

    def delete(self, handle, *, directory):
        self.deleted.append((handle, directory))
        if directory:
            self.directories.discard(handle)
        else:
            self.files.pop(handle, None)

    def close(self, handle):
        self.closed.append(handle)


def test_windows_reparse_ancestor_is_rejected_before_creation():
    api = FakeWindowsAPI(
        directories={"C:\\Users", "C:\\Users\\person", "C:\\Users\\person\\skills"},
        reparses={"C:\\Users\\person"},
    )
    transaction = cli._WindowsTransaction(PureWindowsPath("C:/Users/person/skills"), api)
    with pytest.raises(cli.InstallError, match="DESTINATION_UNSAFE"):
        transaction.preflight(("autogenesis", "SKILL.md"), SKILL_BYTES["autogenesis"])
    transaction.rollback()
    assert not api.created_files
    assert not api.created_directories

def test_windows_reparse_final_file_is_rejected_and_closed():
    parent = "C:\\Users\\person\\skills\\autogenesis"
    target = parent + "\\SKILL.md"
    api = FakeWindowsAPI(
        directories={"C:\\Users", "C:\\Users\\person", "C:\\Users\\person\\skills", parent},
        files={target: SKILL_BYTES["autogenesis"]},
        reparses={target},
    )
    transaction = cli._WindowsTransaction(PureWindowsPath("C:/Users/person/skills"), api)
    with pytest.raises(cli.InstallError, match="DESTINATION_UNSAFE"):
        transaction.preflight(("autogenesis", "SKILL.md"), SKILL_BYTES["autogenesis"])
    transaction.rollback()
    assert target in api.closed



def test_windows_uses_handle_exact_rollback_for_committed_file():
    api = FakeWindowsAPI(directories={"C:\\Users", "C:\\Users\\person", "C:\\Users\\person\\skills"})
    transaction = cli._WindowsTransaction(PureWindowsPath("C:/Users/person/skills"), api)
    relative = ("autogenesis", "SKILL.md")
    assert transaction.preflight(relative, SKILL_BYTES["autogenesis"]) == "pending"
    transaction.create(relative, SKILL_BYTES["autogenesis"])
    handle = api.created_files[0]
    transaction.rollback()
    assert (handle, False) in api.deleted
    assert handle not in api.files


def test_windows_conflict_after_preflight_is_not_overwritten():
    api = FakeWindowsAPI(directories={"C:\\Users", "C:\\Users\\person", "C:\\Users\\person\\skills"})
    transaction = cli._WindowsTransaction(PureWindowsPath("C:/Users/person/skills"), api)
    relative = ("autogenesis", "SKILL.md")
    assert transaction.preflight(relative, SKILL_BYTES["autogenesis"]) == "pending"
    parent = "C:\\Users\\person\\skills\\autogenesis"
    api.directories.add(parent)
    target = parent + "\\SKILL.md"
    api.files[target] = b"concurrent\n"
    with pytest.raises(cli.InstallError, match="SKILL_CONFLICT"):
        transaction.create(relative, SKILL_BYTES["autogenesis"])
    transaction.rollback()
    assert api.files[target] == b"concurrent\n"


def test_appium_skills_metadata_has_digest_inventory_without_mutable_root(monkeypatch, capsys):
    bundle = Bundle()
    monkeypatch.setattr(cli, "_verified_contract", lambda: object())
    monkeypatch.setattr(cli, "load_appium_skills", lambda _contract: bundle)
    assert cli.main(["appium-skills", "--json"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert "root" not in result
    assert result["assets"] == bundle.assets
    assert result["asset_count"] == len(bundle.assets)

def test_appium_workflow_loads_exact_supported_workflow(monkeypatch, capsys):
    bundle = Bundle()
    monkeypatch.setattr(cli, "_verified_contract", lambda: object())
    monkeypatch.setattr(cli, "load_appium_skills", lambda _contract: bundle)
    assert cli.main(["appium-workflow", "setup-mac2", "--json"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["workflow_id"] == "setup-mac2"
    assert result["entrypoint"] == "skills/setup-mac2/SKILL.md"
    assert result["content"] == "official workflow\n"
    assert result["required_contexts"] == ["contexts/platform/macos/profile.md"]
    assert result["tools"] == ["tools/appium/setup/scripts/check-mac2-env.mjs"]


def test_appium_workflow_rejects_unsupported_id(monkeypatch, capsys):
    monkeypatch.setattr(cli, "_verified_contract", lambda: object())
    monkeypatch.setattr(cli, "load_appium_skills", lambda _contract: Bundle())
    assert cli.main(["appium-workflow", "setup-espresso", "--json"]) == 1
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "error"


def test_appium_asset_writes_exact_held_binary_bytes(monkeypatch, capsysbinary):
    path = "skills/setup-mac2/SKILL.md"
    raw = b"\x00\xffheld\r\nbytes\x80"
    bundle = Bundle({path: raw})
    monkeypatch.setattr(cli, "_verified_contract", lambda: object())
    monkeypatch.setattr(cli, "load_appium_skills", lambda _contract: bundle)
    assert cli.main(["appium-asset", "setup-mac2", path]) == 0
    assert capsysbinary.readouterr() == (raw, b"")


@pytest.mark.parametrize("path", ["../SKILL.md", "/absolute/SKILL.md", "skills\\setup-mac2\\SKILL.md", "unknown"])
def test_appium_asset_rejects_non_inventory_and_traversal_paths(path, monkeypatch, capsysbinary):
    monkeypatch.setattr(cli, "_verified_contract", lambda: object())
    monkeypatch.setattr(cli, "load_appium_skills", lambda _contract: Bundle())
    assert cli.main(["appium-asset", "setup-mac2", path]) == 1
    stdout, stderr = capsysbinary.readouterr()
    assert stdout == b""
    assert stderr == b"AUTOGENESIS_CONTRACT_INTEGRITY_ERROR\n"



@pytest.mark.parametrize("arguments", [
    ["appium-skills", "--json"],
    ["appium-workflow", "setup-mac2", "--json"],
    ["appium-asset", "setup-mac2", "skills/setup-mac2/SKILL.md"],
])
def test_appium_commands_reject_unpinned_contract(arguments, monkeypatch):
    contract = Contract()
    contract.identity = type("Identity", (), {
        "contract_version": cli.EXPECTED["autogenesis-agent-contract"],
        "manifest_sha256": "0" * 64,
    })()
    monkeypatch.setattr(cli, "load_contract", lambda: contract)
    monkeypatch.setattr(
        cli,
        "load_appium_skills",
        lambda _contract: pytest.fail("Appium snapshot loaded before Contract pin check"),
    )
    assert cli.main(arguments) == 1


def test_cli_emits_structured_error_without_payload(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli.sys, "platform", "linux")
    assert cli.main(["install", "--skills-dir", str(tmp_path / "skills"), "--json"]) == 1
    assert json.loads(capsys.readouterr().out) == {
        "error": "AUTOGENESIS_PLATFORM_UNSUPPORTED: native macOS or Windows is required",
        "status": "error",
    }


def test_cli_version_is_available_without_a_subcommand(capsys):
    with pytest.raises(SystemExit) as caught:
        cli.main(["--version"])
    assert caught.value.code == 0
    assert capsys.readouterr() == ("autogenesis 0.2.0\n", "")
