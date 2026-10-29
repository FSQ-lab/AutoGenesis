import json
from pathlib import Path

import pytest

from autogenesis_cli import cli


def ready(monkeypatch):
    monkeypatch.setattr(cli, "_verify_packages", lambda names: {name: cli.EXPECTED[name] for name in names})


def test_install_copies_canonical_skills_and_is_idempotent(tmp_path, monkeypatch):
    ready(monkeypatch)
    monkeypatch.setattr(cli.sys, "platform", "darwin")
    root = tmp_path / "skills"
    first = cli.install(root)
    assert first["status"] == "ready"
    assert set(first["skills"]) == set(cli.SKILLS)
    for name in cli.SKILLS:
        target = root / name / "SKILL.md"
        assert target.read_bytes() == cli._canonical_skill(name)
        assert first["skills"][name]["status"] == "installed"
    second = cli.install(root)
    assert {value["status"] for value in second["skills"].values()} == {"unchanged"}


def test_install_preserves_conflicting_skill(tmp_path, monkeypatch):
    ready(monkeypatch)
    monkeypatch.setattr(cli.sys, "platform", "darwin")
    target = tmp_path / "skills" / "autogenesis-setup" / "SKILL.md"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"user content\n")
    with pytest.raises(cli.InstallError, match="SKILL_CONFLICT"):
        cli.install(tmp_path / "skills")
    assert target.read_bytes() == b"user content\n"
    assert not (tmp_path / "skills" / "autogenesis-run").exists()


def test_conflict_in_second_skill_prevents_first_skill_write(tmp_path, monkeypatch):
    ready(monkeypatch)
    monkeypatch.setattr(cli.sys, "platform", "darwin")
    root = tmp_path / "skills"
    target = root / "autogenesis-run" / "SKILL.md"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"user content\n")
    with pytest.raises(cli.InstallError, match="SKILL_CONFLICT"):
        cli.install(root)
    assert target.read_bytes() == b"user content\n"
    assert not (root / "autogenesis-setup" / "SKILL.md").exists()


def test_second_write_failure_rolls_back_first_skill(tmp_path, monkeypatch):
    ready(monkeypatch)
    monkeypatch.setattr(cli.sys, "platform", "darwin")
    original = cli._atomic_install
    calls = []

    def fail_second(destination, raw):
        calls.append(destination)
        if len(calls) == 2:
            raise OSError("synthetic failure")
        original(destination, raw)

    monkeypatch.setattr(cli, "_atomic_install", fail_second)
    root = tmp_path / "skills"
    with pytest.raises(OSError, match="synthetic failure"):
        cli.install(root)
    assert not (root / "autogenesis-setup" / "SKILL.md").exists()
    assert not (root / "autogenesis-run" / "SKILL.md").exists()


def test_unsupported_host_stops_before_writes(tmp_path, monkeypatch):
    monkeypatch.setattr(cli.sys, "platform", "linux")
    with pytest.raises(cli.InstallError, match="PLATFORM_UNSUPPORTED"):
        cli.install(tmp_path / "skills")
    assert not (tmp_path / "skills").exists()


def test_relative_destination_is_rejected(monkeypatch):
    ready(monkeypatch)
    monkeypatch.setattr(cli.sys, "platform", "darwin")
    with pytest.raises(cli.InstallError, match="NOT_ABSOLUTE"):
        cli.install(Path("relative"))


def test_cli_emits_structured_error_without_payload(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli.sys, "platform", "linux")
    assert cli.main(["install", "--skills-dir", str(tmp_path / "skills"), "--json"]) == 1
    result = json.loads(capsys.readouterr().out)
    assert result == {
        "error": "AUTOGENESIS_PLATFORM_UNSUPPORTED: native macOS or Windows is required",
        "status": "error",
    }
