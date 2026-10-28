import os
import runpy
import shutil
import subprocess
import sys
from importlib import resources

import pytest

from autogenesis_agent_contract._asset_io import MAX_ASSET_BYTES, MAX_MANIFEST_BYTES

NAMES = ("autoGenesis-run", "autoGenesis-win")


def test_repository_skills_are_exact_canonical_projections(repo_root):
    for name in NAMES:
        source = resources.files("autogenesis_agent_contract").joinpath(f"assets/skills/{name}/SKILL.md").read_bytes()
        assert (repo_root / f".github/skills/{name}/SKILL.md").read_bytes() == source
        assert f"name: {name}\n".encode() in source
        assert b"prompts/list" in source and b"autogenesis://agent-contract/identity" in source
        assert len(source) < 2048
        for obsolete in (b"before_gen_code", b"confirm_code_change", b"RETRY UNTIL SUCCESS", b"clear_cache"):
            assert obsolete not in source


@pytest.fixture
def projection_repo(tmp_path, repo_root):
    shutil.copytree(repo_root / "agent-contract/tools", tmp_path / "agent-contract/tools", ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copytree(repo_root / "agent-contract/src", tmp_path / "agent-contract/src", ignore=shutil.ignore_patterns("__pycache__"))
    for name in NAMES:
        target = tmp_path / f".github/skills/{name}/SKILL.md"
        target.parent.mkdir(parents=True)
        shutil.copyfile(repo_root / f".github/skills/{name}/SKILL.md", target)
    return tmp_path


def invoke(root, *arguments):
    return subprocess.run(
        [sys.executable, str(root / "agent-contract/tools/sync_skills.py"), *arguments],
        cwd=root, capture_output=True, text=True, check=False, timeout=10,
    )


def test_projection_drift_fails_check_and_sync_is_deterministic_scoped_and_atomic(projection_repo):
    root = projection_repo
    target = root / ".github/skills/autoGenesis-run/SKILL.md"
    official = target.read_bytes()
    unrelated = root / "unrelated.txt"
    unrelated.write_bytes(b"Preserve user work")
    target.write_bytes(b"drift\n")
    assert invoke(root, "--check").returncode != 0
    assert target.read_bytes() == b"drift\n"
    assert invoke(root).returncode == 0
    assert target.read_bytes() == official
    before = target.stat().st_mtime_ns
    assert invoke(root).returncode == 0
    assert target.stat().st_mtime_ns == before
    assert invoke(root, "--check").returncode == 0
    assert unrelated.read_bytes() == b"Preserve user work"
    assert not list(root.rglob(".autogenesis-*"))


def test_source_tampering_is_not_silently_projected(projection_repo):
    root = projection_repo
    source = root / "agent-contract/src/autogenesis_agent_contract/assets/skills/autoGenesis-run/SKILL.md"
    source.write_bytes(b"Tampered source\n")
    target = root / ".github/skills/autoGenesis-run/SKILL.md"
    before = target.read_bytes()
    assert invoke(root).returncode != 0
    assert target.read_bytes() == before


@pytest.mark.parametrize("kind", ["directory", "oversized"])
def test_unsafe_manifest_inputs_fail_before_projection(projection_repo, kind):
    root = projection_repo
    manifest = root / "agent-contract/src/autogenesis_agent_contract/assets/manifest.json"
    originals = {name: (root / f".github/skills/{name}/SKILL.md").read_bytes() for name in NAMES}
    manifest.unlink()
    if kind == "directory":
        manifest.mkdir()
    else:
        with manifest.open("wb") as stream:
            stream.truncate(MAX_MANIFEST_BYTES + 1)
    result = invoke(root)
    assert result.returncode != 0
    assert "Contract integrity error" in result.stderr
    assert all((root / f".github/skills/{name}/SKILL.md").read_bytes() == raw for name, raw in originals.items())


@pytest.mark.skipif(os.name == "nt", reason="POSIX FIFO regression")
def test_fifo_manifest_fails_without_blocking_or_writing(projection_repo):
    root = projection_repo
    manifest = root / "agent-contract/src/autogenesis_agent_contract/assets/manifest.json"
    before = (root / ".github/skills/autoGenesis-run/SKILL.md").read_bytes()
    manifest.unlink()
    os.mkfifo(manifest)
    result = invoke(root)
    assert result.returncode != 0
    assert "Contract integrity error" in result.stderr
    assert (root / ".github/skills/autoGenesis-run/SKILL.md").read_bytes() == before


def test_oversized_canonical_asset_is_never_projected(projection_repo):
    root = projection_repo
    source = root / "agent-contract/src/autogenesis_agent_contract/assets/skills/autoGenesis-run/SKILL.md"
    target = root / ".github/skills/autoGenesis-run/SKILL.md"
    before = target.read_bytes()
    with source.open("wb") as stream:
        stream.truncate(MAX_ASSET_BYTES + 1)
    assert invoke(root).returncode != 0
    assert target.read_bytes() == before


FREEZE_OUTPUTS = (
    "agent-contract/src/autogenesis_agent_contract/assets/manifest.json",
    "agent-contract/src/autogenesis_agent_contract/_release.py",
)


def invoke_freeze(root):
    return subprocess.run(
        [sys.executable, str(root / "agent-contract/tools/freeze_assets.py")],
        cwd=root, capture_output=True, text=True, check=False, timeout=10,
    )


def test_freeze_compares_ordinary_outputs_without_writing(projection_repo):
    before = {path: (projection_repo / path).read_bytes() for path in FREEZE_OUTPUTS}
    assert invoke_freeze(projection_repo).returncode == 0
    assert all((projection_repo / path).read_bytes() == raw for path, raw in before.items())


@pytest.mark.parametrize("output", FREEZE_OUTPUTS)
@pytest.mark.parametrize("kind", ["directory", "oversized"])
def test_freeze_rejects_unsafe_comparison_outputs(projection_repo, output, kind):
    target = projection_repo / output
    other = next(path for path in FREEZE_OUTPUTS if path != output)
    unchanged = (projection_repo / other).read_bytes()
    target.unlink()
    if kind == "directory":
        target.mkdir()
    else:
        with target.open("wb") as stream:
            stream.truncate(MAX_MANIFEST_BYTES + 1)
    result = invoke_freeze(projection_repo)
    assert result.returncode != 0
    assert "Release integrity error" in result.stderr
    assert (projection_repo / other).read_bytes() == unchanged


@pytest.mark.skipif(os.name == "nt", reason="POSIX FIFO comparison regression")
@pytest.mark.parametrize("output", FREEZE_OUTPUTS)
def test_freeze_rejects_fifo_comparison_outputs_without_blocking(projection_repo, output):
    target = projection_repo / output
    target.unlink()
    os.mkfifo(target)
    result = invoke_freeze(projection_repo)
    assert result.returncode != 0
    assert "Release integrity error" in result.stderr


@pytest.mark.parametrize("output", FREEZE_OUTPUTS)
def test_freeze_rejects_output_replaced_between_stat_and_open(projection_repo, output, monkeypatch):
    script = projection_repo / "agent-contract/tools/freeze_assets.py"
    monkeypatch.syspath_prepend(str(script.parent))
    tool = runpy.run_path(str(script))
    asset_io = tool["load_asset_io"](projection_repo)
    target = projection_repo / output
    original_bytes = target.read_bytes()
    original_open = os.open
    replacements = []

    def replace_before_open(path, flags, *args, **kwargs):
        if path == target:
            # Identical bytes must not conceal a changed file identity.
            target.rename(target.with_name(target.name + ".previous"))
            target.write_bytes(original_bytes)
            replacements.append(path)
        return original_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", replace_before_open)
    monkeypatch.setitem(tool["main"].__globals__, "load_asset_io", lambda repo: asset_io)
    monkeypatch.setattr(sys, "argv", [str(script)])
    with pytest.raises(SystemExit, match="Release integrity error"):
        tool["main"]()
    assert replacements == [target]
