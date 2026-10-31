import hashlib
import json
import os
import sys
from pathlib import Path, PureWindowsPath

import pytest

from autogenesis_cli import cli


SKILL_BYTES = {
    "autogenesis-setup": b"---\nname: autogenesis-setup\n---\nheld setup\n",
    "autogenesis-run": b"---\nname: autogenesis-run\n---\nheld run\n",
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
        package_bytes["autogenesis-setup"] = b"modified package bytes\n"
        package_bytes["autogenesis-run"] = b"modified package bytes\n"
        return contract

    monkeypatch.setattr(cli, "load_contract", load_once)
    root = tmp_path / "skills"
    cli.install(root)
    assert (root / "autogenesis-setup" / "SKILL.md").read_bytes() == SKILL_BYTES["autogenesis-setup"]
    assert (root / "autogenesis-run" / "SKILL.md").read_bytes() == SKILL_BYTES["autogenesis-run"]


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
    assert result["skills"]["autogenesis-setup"]["path"] == str(root / "autogenesis-setup" / "SKILL.md")


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


def test_conflict_in_second_skill_prevents_first_skill_write(tmp_path, monkeypatch):
    ready(monkeypatch)
    root = tmp_path / "skills"
    target = root / "autogenesis-run" / "SKILL.md"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"user content\n")
    with pytest.raises(cli.InstallError, match="SKILL_CONFLICT"):
        cli.install(root)
    assert target.read_bytes() == b"user content\n"
    assert not (root / "autogenesis-setup").exists()


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
    assert (root / "autogenesis-setup" / "SKILL.md").read_bytes() == b"concurrent owner\n"
    assert not (root / "autogenesis-run").exists()


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
    assert not (moved / "autogenesis-setup").exists()
    assert not (moved / "autogenesis-run").exists()


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX descriptor rollback")
def test_failure_after_file_commit_rolls_back_current_file(tmp_path, monkeypatch):
    ready(monkeypatch)
    root = tmp_path / "skills"

    def fail_verification(self, record, raw):
        raise cli.InstallError(cli._INTEGRITY)

    monkeypatch.setattr(cli._PosixTransaction, "_verify_record", fail_verification)
    with pytest.raises(cli.InstallError, match="INTEGRITY_ERROR"):
        cli.install(root)
    assert not (root / "autogenesis-setup").exists()
    assert not (root / "autogenesis-run").exists()


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX descriptor rollback")
def test_concurrent_replacement_during_rollback_is_preserved(tmp_path, monkeypatch):
    ready(monkeypatch)
    root = tmp_path / "skills"
    original = cli._PosixTransaction.create
    calls = 0

    def create(transaction, relative, raw):
        nonlocal calls
        calls += 1
        if calls == 2:
            replacement = root / "replacement"
            replacement.write_bytes(b"concurrent replacement\n")
            os.replace(replacement, root / "autogenesis-setup" / "SKILL.md")
            raise OSError("synthetic second write failure")
        return original(transaction, relative, raw)

    monkeypatch.setattr(cli._PosixTransaction, "create", create)
    with pytest.raises(OSError, match="synthetic second write failure"):
        cli.install(root)
    assert (root / "autogenesis-setup" / "SKILL.md").read_bytes() == b"concurrent replacement\n"
    assert not (root / "autogenesis-run").exists()


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX descriptor rollback")
def test_two_skill_transaction_rolls_back_first_on_second_failure(tmp_path, monkeypatch):
    ready(monkeypatch)
    root = tmp_path / "skills"
    original = cli._PosixTransaction.create
    calls = 0

    def create(transaction, relative, raw):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("synthetic second write failure")
        return original(transaction, relative, raw)

    monkeypatch.setattr(cli._PosixTransaction, "create", create)
    with pytest.raises(OSError, match="synthetic second write failure"):
        cli.install(root)
    assert not (root / "autogenesis-setup").exists()
    assert not (root / "autogenesis-run").exists()


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
        transaction.preflight(("autogenesis-setup", "SKILL.md"), SKILL_BYTES["autogenesis-setup"])
    transaction.rollback()
    assert not api.created_files
    assert not api.created_directories

def test_windows_reparse_final_file_is_rejected_and_closed():
    parent = "C:\\Users\\person\\skills\\autogenesis-setup"
    target = parent + "\\SKILL.md"
    api = FakeWindowsAPI(
        directories={"C:\\Users", "C:\\Users\\person", "C:\\Users\\person\\skills", parent},
        files={target: SKILL_BYTES["autogenesis-setup"]},
        reparses={target},
    )
    transaction = cli._WindowsTransaction(PureWindowsPath("C:/Users/person/skills"), api)
    with pytest.raises(cli.InstallError, match="DESTINATION_UNSAFE"):
        transaction.preflight(("autogenesis-setup", "SKILL.md"), SKILL_BYTES["autogenesis-setup"])
    transaction.rollback()
    assert target in api.closed



def test_windows_uses_handle_exact_rollback_for_committed_file():
    api = FakeWindowsAPI(directories={"C:\\Users", "C:\\Users\\person", "C:\\Users\\person\\skills"})
    transaction = cli._WindowsTransaction(PureWindowsPath("C:/Users/person/skills"), api)
    relative = ("autogenesis-setup", "SKILL.md")
    assert transaction.preflight(relative, SKILL_BYTES["autogenesis-setup"]) == "pending"
    transaction.create(relative, SKILL_BYTES["autogenesis-setup"])
    handle = api.created_files[0]
    transaction.rollback()
    assert (handle, False) in api.deleted
    assert handle not in api.files


def test_windows_conflict_after_preflight_is_not_overwritten():
    api = FakeWindowsAPI(directories={"C:\\Users", "C:\\Users\\person", "C:\\Users\\person\\skills"})
    transaction = cli._WindowsTransaction(PureWindowsPath("C:/Users/person/skills"), api)
    relative = ("autogenesis-setup", "SKILL.md")
    assert transaction.preflight(relative, SKILL_BYTES["autogenesis-setup"]) == "pending"
    parent = "C:\\Users\\person\\skills\\autogenesis-setup"
    api.directories.add(parent)
    target = parent + "\\SKILL.md"
    api.files[target] = b"concurrent\n"
    with pytest.raises(cli.InstallError, match="SKILL_CONFLICT"):
        transaction.create(relative, SKILL_BYTES["autogenesis-setup"])
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


def test_appium_asset_writes_exact_held_binary_bytes(monkeypatch, capsysbinary):
    path = "skills/setup-mac2/SKILL.md"
    raw = b"\x00\xffheld\r\nbytes\x80"
    bundle = Bundle({path: raw})
    monkeypatch.setattr(cli, "_verified_contract", lambda: object())
    monkeypatch.setattr(cli, "load_appium_skills", lambda _contract: bundle)
    assert cli.main(["appium-asset", path]) == 0
    assert capsysbinary.readouterr() == (raw, b"")


@pytest.mark.parametrize("path", ["../SKILL.md", "/absolute/SKILL.md", "skills\\setup-mac2\\SKILL.md", "unknown"])
def test_appium_asset_rejects_non_inventory_and_traversal_paths(path, monkeypatch, capsysbinary):
    monkeypatch.setattr(cli, "_verified_contract", lambda: object())
    monkeypatch.setattr(cli, "load_appium_skills", lambda _contract: Bundle())
    assert cli.main(["appium-asset", path]) == 1
    stdout, stderr = capsysbinary.readouterr()
    assert stdout == b""
    assert stderr == b"AUTOGENESIS_CONTRACT_INTEGRITY_ERROR\n"

def test_appium_tool_binds_node_and_helper_bytes_without_shell_or_inherited_environment(monkeypatch):
    script = "tools/appium/setup/scripts/check-mac2-env.mjs"
    helper = "tools/appium/setup/scripts/reporting.mjs"
    bundle = Bundle({script: b"import './reporting.mjs';\n", helper: b"export {};\n"})
    monkeypatch.setattr(cli, "_verified_contract", lambda: object())
    monkeypatch.setattr(cli, "load_appium_skills", lambda _contract: bundle)
    digest = "a" * 64
    approved_path = "/approved/bin:/usr/bin"
    path_digest = hashlib.sha256(approved_path.encode()).hexdigest()
    monkeypatch.setenv("PATH", approved_path)
    monkeypatch.setenv("NODE_OPTIONS", "--require=/untrusted/project/pwn.js")
    monkeypatch.setattr(cli, "_hold_node", lambda node, sha256, cwd: cli._HeldNode(node, sha256))
    def materialize(_held, root):
        target = root / "node"
        target.write_bytes(b"native node")
        return str(target)
    monkeypatch.setattr(cli, "_materialize_held_node", materialize)
    roots = []

    def run(command, **options):
        if command[1:] == ["--version"]:
            assert options == {
                "cwd": Path.cwd(), "check": False, "capture_output": True, "text": True, "env": {},
            }
            return type("Completed", (), {"returncode": 0, "stdout": "v24.22.1\n", "stderr": ""})()
        root = Path(command[3]).parents[4]
        roots.append(root)
        assert command[0] == str(root / "node")
        assert command[1] == str(root / "autogenesis-node-bootstrap.mjs")
        assert json.loads(cli.base64.urlsafe_b64decode(command[2])) == [["PATH", approved_path]]
        assert command[3:] == [str(root / script), "--format", "summary"]
        assert (root / "autogenesis-node-bootstrap.mjs").read_bytes() == cli._NODE_BOOTSTRAP
        assert (root / script).read_bytes() == bundle.read_asset(script)
        assert (root / helper).read_bytes() == bundle.read_asset(helper)
        assert options == {"cwd": Path.cwd(), "check": False, "env": {}}
        return type("Completed", (), {"returncode": 7})()

    monkeypatch.setattr(cli.subprocess, "run", run)
    assert cli.main([
        "appium-tool", "--node", "/verified/path/node",
        "--node-sha256", digest, "--node-version", "v24.22.1",
        "--allow-env", f"PATH={path_digest}", script, "--", "--format", "summary",
    ]) == 7
    assert len(roots) == 1 and not roots[0].exists()

def test_appium_tool_rejects_unsupported_host_before_loading_assets(monkeypatch, capsys):
    monkeypatch.setattr(cli.sys, "platform", "linux")
    monkeypatch.setattr(
        cli, "load_appium_skills", lambda _contract: pytest.fail("assets loaded before host gate"),
    )
    assert cli.main([
        "appium-tool", "--node", "/verified/path/node", "--node-sha256", "a" * 64,
        "--node-version", "v24.22.1", "tools/appium/setup/scripts/check-mac2-env.mjs",
    ]) == 1
    assert "AUTOGENESIS_PLATFORM_UNSUPPORTED" in capsys.readouterr().err



def test_appium_tool_rejects_non_helper_asset_before_execution(monkeypatch):
    bundle = Bundle()
    monkeypatch.setattr(cli, "_verified_contract", lambda: object())
    monkeypatch.setattr(cli, "load_appium_skills", lambda _contract: bundle)
    monkeypatch.setattr(
        cli.subprocess, "run", lambda *_args, **_kwargs: pytest.fail("unauthorized process execution"),
    )
    assert cli.main([
        "appium-tool", "--node", "/verified/path/node", "--node-sha256", "a" * 64,
        "--node-version", "v24.22.1", "skills/setup-mac2/SKILL.md",
    ]) == 1

def test_node_identity_rejects_project_local_symlink_and_writable_paths(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    project_node = project / "node"
    project_node.write_bytes(b"\x7fELFnode")
    project_node.chmod(0o755)
    with pytest.raises(cli.InstallError, match="NODE_UNSAFE"):
        cli._hold_node(str(project_node), hashlib.sha256(project_node.read_bytes()).hexdigest(), project)

    outside = tmp_path / "outside-node"
    outside.write_bytes(b"node")
    outside.chmod(0o755)
    linked = tmp_path / "node-link"
    linked.symlink_to(outside)
    with pytest.raises(cli.InstallError, match="NODE_UNSAFE"):
        cli._hold_node(str(linked), hashlib.sha256(outside.read_bytes()).hexdigest(), project)
    if sys.platform != "win32":
        unsafe = tmp_path / "unsafe"
        unsafe.mkdir(mode=0o777)
        unsafe.chmod(0o777)
        unsafe_node = unsafe / "node"
        unsafe_node.write_bytes(b"\x7fELFnode")
        unsafe_node.chmod(0o755)
        with pytest.raises(cli.InstallError, match="NODE_UNSAFE"):
            cli._hold_node(
                str(unsafe_node), hashlib.sha256(unsafe_node.read_bytes()).hexdigest(), project,
            )


def test_node_identity_materializes_held_bytes_after_path_swap_and_rejects_env_shebang(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    approved = tmp_path / "approved-node"
    original = b"MZapproved" if sys.platform == "win32" else b"\x7fELFapproved"
    approved.write_bytes(original)
    approved.chmod(0o755)
    held = cli._hold_node(str(approved), hashlib.sha256(original).hexdigest(), project)
    try:
        replacement = tmp_path / "replacement"
        replacement.write_bytes(b"MZreplacement" if sys.platform == "win32" else b"\x7fELFreplacement")
        replacement.chmod(0o755)
        if sys.platform == "win32":
            with pytest.raises(OSError):
                replacement.replace(approved)
        else:
            replacement.replace(approved)
        root = tmp_path / "private"
        root.mkdir()
        materialized = Path(cli._materialize_held_node(held, root))
        assert materialized.read_bytes() == original
    finally:
        held.close()

    wrapper = tmp_path / "node-wrapper"
    wrapper.write_bytes(b"#!/usr/bin/env node\n")
    wrapper.chmod(0o755)
    with pytest.raises(cli.InstallError, match="NODE_IDENTITY_MISMATCH"):
        cli._hold_node(str(wrapper), hashlib.sha256(wrapper.read_bytes()).hexdigest(), project)


@pytest.mark.parametrize("arguments", [
    ["appium-skills", "--json"],
    ["appium-asset", "skills/setup-mac2/SKILL.md"],
    [
        "appium-tool", "--node", "/verified/path/node", "--node-sha256", "a" * 64,
        "--node-version", "v24.22.1", "tools/appium/setup/scripts/check-mac2-env.mjs",
    ],
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
    assert capsys.readouterr() == ("autogenesis 0.3.0\n", "")
