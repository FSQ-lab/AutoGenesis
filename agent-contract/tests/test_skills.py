import hashlib
import os
import re
import runpy
import shutil
import subprocess
import sys
from importlib import resources

import pytest

from autogenesis_agent_contract._asset_io import MAX_ASSET_BYTES, MAX_MANIFEST_BYTES

NAMES = ("autogenesis-setup", "autogenesis-run")


def test_repository_skills_are_exact_canonical_projections(repo_root):
    for name in NAMES:
        source = resources.files("autogenesis_agent_contract").joinpath(f"assets/skills/{name}/SKILL.md").read_bytes()
        assert (repo_root / f".github/skills/{name}/SKILL.md").read_bytes() == source
        assert f"name: {name}\n".encode() in source
        assert b"prompts/list" in source and b"autogenesis://agent-contract/identity" in source
        assert len(source) < 4096
        for obsolete in (b"before_gen_code", b"confirm_code_change", b"RETRY UNTIL SUCCESS", b"clear_cache"):
            assert obsolete not in source


def test_setup_skill_requires_authenticated_immutable_downloads(repo_root):
    canonical = repo_root / "agent-contract/src/autogenesis_agent_contract/assets/skills/autogenesis-setup/SKILL.md"
    projection = repo_root / ".github/skills/autogenesis-setup/SKILL.md"
    assert projection.read_bytes() == canonical.read_bytes()
    policy = " ".join(canonical.read_text(encoding="utf-8").split())

    assert "exact reviewed version plus published SHA-256, signature, or attestation" in policy
    assert "Approval is consent, not authentication" in policy
    assert "Missing proof means **Action Required**" in policy
    assert policy.index("Authenticate before unpacking/execution/persistence") < policy.index("install atomically")
    assert "Reject mutable URLs" in policy
    assert not re.search(r"\b(?:download|fetch)\s+(?:the\s+)?latest\b", policy, re.IGNORECASE)
    assert "releases/latest" not in policy
    assert "Preview every install" in policy


def test_setup_skill_uses_one_shot_verified_appium_assets(repo_root):
    source = repo_root / "agent-contract/src/autogenesis_agent_contract/assets/skills/autogenesis-setup/SKILL.md"
    policy = " ".join(source.read_text(encoding="utf-8").split())

    command = "autogenesis appium-asset <path>"
    assert policy.count(command) == 1
    assert policy.index("autogenesis appium-skills --json") < policy.index(command)
    assert "commit `e907024c210fe024c956ed9c74146fc27b1dd013`" in policy
    assert all(value in policy for value in (
        "verified documentation/helper evidence, not a decision-maker",
        "require exit 0/empty stderr and exact stdout",
        "Reject uninventoried/package paths",
        "Before `autogenesis appium-tool`",
        "every child executable's absolute path/version/SHA-256",
        "Never pass `--report`",
        "State-changing helpers need separate approval",
    ))
    assert "Use the returned root as the working directory" not in policy
    assert "node tools/" not in policy


def test_skills_follow_agent_skills_names_and_separate_responsibilities(repo_root):
    setup = (repo_root / ".github/skills/autogenesis-setup/SKILL.md").read_text(encoding="utf-8")
    run = (repo_root / ".github/skills/autogenesis-run/SKILL.md").read_text(encoding="utf-8")
    for name, content in zip(NAMES, (setup, run), strict=True):
        assert re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name)
        assert content.startswith("---\n")
        assert f"name: {name}\n" in content
        assert "contract-version: \"2.1.0\"" in content
        assert "Linux and WSL are unsupported" in content
    setup_policy = " ".join(setup.split())
    run_policy = " ".join(run.split())
    assert all(value in setup_policy for value in (
        "Observe → Consult → Evaluate → Reuse", "Automatically run relevant read-only",
        "explicit engine exclusion", "blocks reuse and Ready until resolved",
        "newer version is not incompatible", "older recommended environment",
        "PATH-selected child", "every child executable's absolute path/version/SHA-256",
        "Never pass `--report`", "verified documentation/helper evidence, not", "smallest plan",
        "Recommended action", "Approval", "Resume context",
        "setup-uiautomator2", "setup-xcuitest", "xcuitest-real-device-config", "setup-mac2",
        "e907024c210fe024c956ed9c74146fc27b1dd013", "Ready", "Action Required", "Blocked",
    ))
    assert "Node 26 requires Action Required" not in setup_policy
    assert all(value in run_policy for value in (
        "autogenesis-setup", "structured `task_text`", "Original user intent",
        "one concrete minimal example", "Resume context", "execute_natural_language_task",
        "execute_scenario", "generate_scenario_test", "current preview", "Windows MCP", "Appium MCP",
    ))
    assert "exact task text" not in run_policy
    assert "npm install" not in run_policy and "pip install" not in run_policy
    projected_names = {path.name for path in (repo_root / ".github/skills").iterdir()}
    assert not {"autoGenesis-run", "autoGenesis-win"} & projected_names


def test_direct_workflow_accepts_only_confirmed_structured_context(repo_root):
    workflow = " ".join((repo_root / "agent-contract/src/autogenesis_agent_contract/assets/workflows/execute_natural_language_task.md").read_text(encoding="utf-8").split())
    assert all(value in workflow for value in (
        "structured by the LLM", "preserve the original user intent",
        "only confirmed or observed", "invents a business action or expected result",
        "Use at most three total attempts", "Do not invoke generation",
    ))



def test_skill_release_assets_match_contract_and_install_prompt(tmp_path, repo_root):
    output = tmp_path / "release"
    base = "https://example.invalid/releases/agent-contract-v2.1.0"
    result = subprocess.run(
        [
            sys.executable,
            str(repo_root / "agent-contract/tools/build_skill_release.py"),
            "--output-dir",
            str(output),
            "--base-url",
            base,
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert result.returncode == 0
    checksums = {}
    for line in (output / "SHA256SUMS").read_text(encoding="ascii").splitlines():
        digest, filename = line.split("  ", 1)
        checksums[filename] = digest
        assert hashlib.sha256((output / filename).read_bytes()).hexdigest() == digest
    assert set(checksums) == {"autogenesis-setup-SKILL.md", "autogenesis-run-SKILL.md"}
    prompt = (output / "agent-install-prompt.txt").read_text(encoding="utf-8")
    assert f"{base}/autogenesis-setup-SKILL.md" in prompt
    assert checksums["autogenesis-setup-SKILL.md"] in prompt
    assert "do not execute it yet" in prompt


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
    target = root / ".github/skills/autogenesis-run/SKILL.md"
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
    source = root / "agent-contract/src/autogenesis_agent_contract/assets/skills/autogenesis-run/SKILL.md"
    source.write_bytes(b"Tampered source\n")
    target = root / ".github/skills/autogenesis-run/SKILL.md"
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
    before = (root / ".github/skills/autogenesis-run/SKILL.md").read_bytes()
    manifest.unlink()
    os.mkfifo(manifest)
    result = invoke(root)
    assert result.returncode != 0
    assert "Contract integrity error" in result.stderr
    assert (root / ".github/skills/autogenesis-run/SKILL.md").read_bytes() == before


def test_oversized_canonical_asset_is_never_projected(projection_repo):
    root = projection_repo
    source = root / "agent-contract/src/autogenesis_agent_contract/assets/skills/autogenesis-run/SKILL.md"
    target = root / ".github/skills/autogenesis-run/SKILL.md"
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
