import hashlib
import json
import os
import re
import runpy
import shutil
import subprocess
import sys
from importlib import resources
import zipfile

import pytest

from autogenesis_agent_contract._asset_io import MAX_ASSET_BYTES, MAX_MANIFEST_BYTES

NAME = "autogenesis"

def _assert_hardened_install_prompt(prompt, channel):
    assert f"exact {channel} identity" in prompt
    assert "exact new absolute disposable virtual-environment path" in prompt
    assert "Require the environment path to be absent" in prompt
    assert "pre-existing environment" in prompt
    assert "explicit user approval" in prompt
    assert "before creating the environment" in prompt
    assert "environment's absolute Python or entrypoints only" in prompt
    assert "failure, cancellation, denial, digest or identity mismatch, supersession, or rollback" in prompt
    assert "delete only the prompt-created environment" in prompt
    assert "Preserve every pre-existing environment" in prompt
    assert "label the source `undisclosed` and stop before installation" in prompt
    assert "Redaction after reading is forbidden" in prompt
    assert all(forbidden not in prompt.lower() for forbidden in (
        "pip config", "uv config", "printenv", "authorization header:",
    ))


def _checksums(output):
    rows = {}
    for line in (output / "SHA256SUMS").read_text(encoding="ascii").splitlines():
        digest, filename = line.split("  ", 1)
        rows[filename] = digest
        assert hashlib.sha256((output / filename).read_bytes()).hexdigest() == digest
    return rows


def test_repository_has_one_exact_canonical_skill_projection(repo_root):
    source = resources.files("autogenesis_agent_contract").joinpath(f"assets/skills/{NAME}/SKILL.md").read_bytes()
    projection = repo_root / f".github/skills/{NAME}/SKILL.md"
    assert projection.read_bytes() == source
    assert source.startswith(b"---\nname: autogenesis\n")
    assert len(source) < 6144
    assert re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", NAME)
    assert {path.name for path in (repo_root / ".github/skills").iterdir()} == {NAME}
    assert b"autogenesis-setup" not in source and b"autogenesis-run" not in source


def test_single_skill_exposes_three_layer_routing_and_runtime_seams(repo_root):
    policy = (repo_root / f".github/skills/{NAME}/SKILL.md").read_text(encoding="utf-8")
    assert all(layer in policy for layer in (
        "Machine bootstrap", "Target readiness", "Runtime execution",
    ))
    assert "autogenesis install" in policy
    assert all(reference in policy for reference in (
        "install", "readiness-common", "appium-environment", "android-readiness",
        "ios-simulator-readiness", "ios-real-device-readiness", "macos-readiness",
        "windows-readiness", "execution-common", "android-execution",
        "apple-execution", "windows-execution",
    ))
    assert "autogenesis appium-workflow <id> --json" in policy
    assert all(workflow in policy for workflow in (
        "setup-uiautomator2", "setup-xcuitest", "xcuitest-real-device-config",
        "setup-mac2", "appium-troubleshooting",
    ))
    assert all(state in policy for state in (
        "Machine Ready", "Target Prepared", "Live Ready", "Task Passed",
        "Task Failed", "Action Required", "Blocked",
    ))
    assert "execute_natural_language_task" in policy
    assert "execute_scenario" in policy
    assert "generate_scenario_test" in policy
    assert "autogenesis://agent-contract/identity" in policy
    assert "Use Appium MCP" in policy and "Use Windows MCP" in policy
    assert "Coding Agent's normal terminal" in policy
    assert "resume" in policy.lower() and "original" in policy.lower()
    assert "recording/generation request" in policy and "generate_scenario_test" in policy


def test_guided_install_and_readiness_references_are_operational(repo_root):
    policy = (repo_root / f".github/skills/{NAME}/SKILL.md").read_text(encoding="utf-8")
    references = repo_root / "agent-contract/src/autogenesis_agent_contract/assets/references"
    install = (references / "install.md").read_text(encoding="utf-8")
    readiness = (references / "readiness-common.md").read_text(encoding="utf-8")
    appium = (references / "appium-environment.md").read_text(encoding="utf-8")
    android = (references / "android-readiness.md").read_text(encoding="utf-8")

    assert "install, activation, repair, or diagnosis" in policy
    assert "actual MCP initialize" not in policy  # detailed proof belongs to the reference
    assert all(value in install for value in (
        "`install`", "`activate`", "`repair`", "`diagnose`",
        "autogenesis install --scope <user|project>",
        "MCP initialize", "prompts/tools/resources",
        "configured/reload-required",
    ))
    assert all(value in install for value in (
        "previously absent disposable virtual environment",
        "explicit approval before creating it",
        "only that environment's absolute Python and entrypoints",
        "exact reviewed Actions artifact or immutable GitHub Release identity",
        "checksums cover every final asset including the prompt and exclude only themselves",
        "Redaction after reading is not a safety boundary",
        "source as `undisclosed` and stop before installation",
        "cancellation, denial, identity/digest mismatch, supersession, or rollback",
        "Never delete or repurpose a pre-existing path",
    ))
    assert all(value in readiness for value in (
        '"requestScope"', '"layers"', '"environment"', '"changes"',
        '"approval"', '"runtimeEvidence"', '"ownership"',
        '"requiredAction"', '"resumeContext"',
    ))
    assert "configured, detected, selected, and rejected" in appium
    assert "process.execPath" in appium and "one temporary task environment" in appium
    assert "Android Studio JBR" in android
    assert "incomplete configured root must not hide a complete conventional root" in android
    assert "physical route does not require emulator package" in android


def test_skill_release_assets_match_contract_and_bootstrap_prompt(tmp_path, repo_root):
    output = tmp_path / "release"
    base = "https://example.invalid/releases/agent-contract-v2.1.0"
    release_manifest = tmp_path / "release-manifest.json"
    packages = {
        "autogenesis-agent-contract": "2.1.0",
        "autogenesis-appium-mcp": "0.5.0",
        "autogenesis-windows-mcp": "0.5.0",
        "autogenesis-cli": "0.2.0",
    }
    release_manifest.write_text(json.dumps({
        "provenance": {"commit": "c" * 40},
        "wheels": [
            {"package": package, "version": version, "sha256": str(index) * 64}
            for index, (package, version) in enumerate(packages.items(), start=1)
        ],
    }) + "\n", encoding="utf-8")
    dependency_lock = tmp_path / "release-dependencies.lock"
    dependency_lock.write_text(f"anyio==4.12.0 --hash=sha256:{'a' * 64}\n", encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            str(repo_root / "agent-contract/tools/build_skill_release.py"),
            "--output-dir",
            str(output),
            "--base-url",
            base,
            "--release-manifest",
            str(release_manifest),
            "--release-manifest-url",
            f"{base}/release-manifest.json",
            "--dependency-lock",
            str(dependency_lock),
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    checksums = _checksums(output)
    assert set(checksums) == {
        "autogenesis-SKILL.md", "autogenesis-release.lock", "release-manifest.json",
        "agent-install-prompt.txt",
    }
    assert set(checksums) == {path.name for path in output.iterdir()} - {"SHA256SUMS"}
    prompt = (output / "agent-install-prompt.txt").read_text(encoding="utf-8")
    assert f"{base}/autogenesis-SKILL.md" in prompt
    assert checksums["autogenesis-SKILL.md"] in prompt
    assert checksums["release-manifest.json"] in prompt
    assert checksums["autogenesis-release.lock"] in prompt
    release_lock = (output / "autogenesis-release.lock").read_text(encoding="utf-8")
    assert "autogenesis-agent-contract==2.1.0" in release_lock
    assert "autogenesis-windows-mcp==0.5.0 ; sys_platform == 'win32'" in release_lock
    assert all(str(index) * 64 in release_lock for index in range(1, 5))
    assert "autogenesis install" in prompt
    assert "exactly one `autogenesis` Skill" in prompt
    assert "stop before running a business task" in prompt
    assert "force-reinstalled" in prompt
    _assert_hardened_install_prompt(prompt, "public Release")
    assert "published immutable GitHub Release" in prompt
    assert "observed positive Release ID" in prompt
    assert "Checksums are internal closure only" in prompt
    original_prompt_digest = checksums["agent-install-prompt.txt"]
    assert hashlib.sha256((prompt + "mutated").encode()).hexdigest() != original_prompt_digest
    extension_service = (
        repo_root / "bdd_ai_toolkit/src/bdd-feature-support/services/CopilotIntegrationService.ts"
    ).read_text(encoding="utf-8")
    assert checksums["autogenesis-SKILL.md"] in extension_service
    assert "getWorkspaceFolder(vscode.Uri.file(featureFilePath))" in extension_service
    assert "O_NOFOLLOW" in extension_service
    assert "process.platform === 'win32' ? 0" in extension_service
    command_handlers = (
        repo_root / "bdd_ai_toolkit/src/bdd-feature-support/utils/CommandHandlers.ts"
    ).read_text(encoding="utf-8")
    assert "skill.status !== 'ready'" in command_handlers
    assert "skill.status === 'invalid'" in command_handlers
    assert "differs from the authenticated release" in command_handlers
    assert "record-read-only-preview" in extension_service
    assert "stop after preview_code_changes" in extension_service
    assert "generated-file writes are unavailable" in extension_service
    assert "generateScenarioText" not in extension_service
    assert "generateBackgroundText" not in extension_service
    assert "canonical autogenesis Skill is not installed" in command_handlers
    assert "autogenesis install for one explicit scope" in command_handlers
    assert "generateScenarioText" not in command_handlers
    assert "generateBackgroundText" not in command_handlers

    package = json.loads((repo_root / "bdd_ai_toolkit/package.json").read_bytes())
    configuration = package["contributes"].get("configuration", {}).get("properties", {})
    assert "bddAiToolkit.cucumber.copilotPrompt" not in configuration
    assert not (repo_root / "bdd_ai_toolkit/src/bdd-feature-support/utils/ConfigManager.ts").exists()

    prompt_source = (repo_root / "bdd_ai_toolkit/src/constants/prompts.ts").read_text(encoding="utf-8")
    assert "DEFAULT_COPILOT_PROMPT" not in prompt_source
    assert "direct execution never generates or writes files" in prompt_source
    get_started = (repo_root / "docs/src/pages/GetStarted.tsx").read_text(encoding="utf-8")
    assert "before_gen_code" in get_started
    assert "preview_code_changes" in get_started
    assert "generated-file writes are unavailable" in get_started
    extension_readme = (repo_root / "bdd_ai_toolkit/README.md").read_text(encoding="utf-8")
    assert "bddAiToolkit.cucumber.copilotPrompt" not in extension_readme
    assert ".agents/skills/autogenesis/SKILL.md" in extension_readme
    assert "never sends a fallback" in extension_readme
    assert "recording preview does not create files" in extension_readme
    assert "Recording preview never writes generated files" in extension_readme
    assert "step definitions already exist" in extension_readme
    assert "no manual coding required" not in extension_readme
    assert "let AI generate automation code" not in extension_readme
    assert "Execute recorded scenarios" not in extension_readme
    for shipped in (prompt_source, get_started, extension_readme):
        assert all(name not in shipped for name in (
            "confirm_code_changes", "confirm_code_change", "clear_cache",
        ))

    for relative in ("appium-mcp-server/server.json", "pywinauto-mcp-server/server.json"):
        descriptor = json.loads((repo_root / relative).read_bytes())
        project_root = next(argument for argument in descriptor["packages"][0]["packageArguments"] if argument["name"] == "--project-root")
        assert "preview destinations" in project_root["description"]
        assert "no generated-file write occurs" in project_root["description"]

def _candidate_wheel(root, package, version):
    filename = f"{package.replace('-', '_')}-{version}-py3-none-any.whl"
    metadata_root = f"{package.replace('-', '_')}-{version}.dist-info"
    with zipfile.ZipFile(root / filename, "w") as archive:
        archive.writestr(f"{metadata_root}/METADATA", f"Name: {package}\nVersion: {version}\n\n")
        archive.writestr(f"{metadata_root}/WHEEL", "Wheel-Version: 1.0\nTag: py3-none-any\n")
    return filename


def test_candidate_channel_binds_exact_first_party_wheels_and_skill(tmp_path, repo_root):
    wheel_dir = tmp_path / "wheels"
    wheel_dir.mkdir()
    expected = {
        "autogenesis-agent-contract": "2.1.0",
        "autogenesis-appium-mcp": "0.5.0",
        "autogenesis-windows-mcp": "0.5.0",
        "autogenesis-cli": "0.2.0",
    }
    for package, version in expected.items():
        _candidate_wheel(wheel_dir, package, version)
    dependency_lock = tmp_path / "candidate-dependencies.lock"
    dependency_lock.write_text(
        f"anyio==4.12.0 --hash=sha256:{'b' * 64}\n", encoding="utf-8"
    )
    commit = subprocess.run(
        ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    output = tmp_path / "candidate"
    result = subprocess.run(
        [
            sys.executable,
            str(repo_root / "agent-contract/tools/build_candidate_release.py"),
            "--wheel-dir", str(wheel_dir),
            "--output-dir", str(output),
            "--base-url", "https://example.invalid/candidate/abc",
            "--commit", commit,
            "--dependency-lock", str(dependency_lock),
            "--workflow-run-id", "123456",
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    manifest_raw = (output / "candidate-manifest.json").read_bytes()
    manifest = json.loads(manifest_raw)
    assert manifest["schema_version"] == 2
    assert manifest["channel"] == "candidate" and manifest["commit"] == commit
    assert manifest["provenance"] == {
        "repository": "FSQ-lab/AutoGenesis",
        "workflow_run_id": "123456",
        "artifact": f"autogenesis-candidate-{commit}",
    }
    assert manifest["first_party_index_fallback"] is False
    assert manifest["third_party_policy"] == "sanitized-source-with-release-hash-lock"
    assert {wheel["package"]: wheel["version"] for wheel in manifest["wheels"]} == expected
    platforms = {wheel["package"]: wheel["platforms"] for wheel in manifest["wheels"]}
    assert platforms["autogenesis-windows-mcp"] == ["win32"]
    assert all("win32" in values for values in platforms.values())
    assert all("darwin" in values for package, values in platforms.items() if package != "autogenesis-windows-mcp")
    for wheel in manifest["wheels"]:
        raw = (output / wheel["filename"]).read_bytes()
        assert len(raw) == wheel["size"]
        assert hashlib.sha256(raw).hexdigest() == wheel["sha256"]
        assert wheel["url"].endswith("/" + wheel["filename"])
    skill = (output / "autogenesis-SKILL.md").read_bytes()
    assert hashlib.sha256(skill).hexdigest() == manifest["skill"]["sha256"]
    for lock in manifest["dependency_locks"].values():
        raw = (output / lock["filename"]).read_bytes()
        assert len(raw) == lock["size"]
        assert hashlib.sha256(raw).hexdigest() == lock["sha256"]
    prompt = (output / "candidate-install-prompt.txt").read_text(encoding="utf-8")
    assert hashlib.sha256(manifest_raw).hexdigest() in prompt
    install_lock = (output / "candidate-install.lock").read_text(encoding="utf-8")
    assert "autogenesis-windows-mcp==0.5.0 ; sys_platform == 'win32'" in install_lock
    assert "never resolve or replace a first-party candidate package from an index" in prompt.lower()
    assert "complete offline-install lock" in prompt

    assert "force-reinstalled" in prompt
    _assert_hardened_install_prompt(prompt, "Candidate")
    assert "exact Actions artifact" in prompt
    assert "workflow run `123456`" in prompt
    assert "superseded run 42843125727" in prompt
    candidate_checksums = _checksums(output)
    assert set(candidate_checksums) == {path.name for path in output.iterdir()} - {"SHA256SUMS"}
    assert "candidate-install-prompt.txt" in candidate_checksums
    (output / "candidate-install-prompt.txt").write_text(prompt + "mutated", encoding="utf-8")
    with pytest.raises(AssertionError):
        _checksums(output)

def test_candidate_channel_rejects_incomplete_wheel_set(tmp_path, repo_root):
    wheel_dir = tmp_path / "wheels"
    wheel_dir.mkdir()
    _candidate_wheel(wheel_dir, "autogenesis-agent-contract", "2.1.0")
    dependency_lock = tmp_path / "candidate-dependencies.lock"
    dependency_lock.write_text(
        f"anyio==4.12.0 --hash=sha256:{'b' * 64}\n", encoding="utf-8"
    )
    commit = subprocess.run(
        ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    result = subprocess.run(
        [
            sys.executable,
            str(repo_root / "agent-contract/tools/build_candidate_release.py"),
            "--wheel-dir", str(wheel_dir),
            "--output-dir", str(tmp_path / "candidate"),
            "--base-url", "https://example.invalid/candidate/abc",
            "--commit", commit,
            "--dependency-lock", str(dependency_lock),
            "--workflow-run-id", "123456",
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert result.returncode != 0
    assert "Candidate wheel set is incomplete" in result.stderr

def test_candidate_channel_rejects_unhashed_dependency_lock(tmp_path, repo_root):
    wheel_dir = tmp_path / "wheels"
    wheel_dir.mkdir()
    for package, version in {
        "autogenesis-agent-contract": "2.1.0",
        "autogenesis-appium-mcp": "0.5.0",
        "autogenesis-windows-mcp": "0.5.0",
        "autogenesis-cli": "0.2.0",
    }.items():
        _candidate_wheel(wheel_dir, package, version)
    dependency_lock = tmp_path / "candidate-dependencies.lock"
    dependency_lock.write_text("anyio==4.12.0\n", encoding="utf-8")
    commit = subprocess.run(
        ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    result = subprocess.run(
        [
            sys.executable,
            str(repo_root / "agent-contract/tools/build_candidate_release.py"),
            "--wheel-dir", str(wheel_dir),
            "--output-dir", str(tmp_path / "candidate"),
            "--base-url", "https://example.invalid/candidate/abc",
            "--commit", commit,
            "--dependency-lock", str(dependency_lock),
            "--workflow-run-id", "123456",
        ],
        cwd=repo_root, capture_output=True, text=True, check=False, timeout=10,
    )
    assert result.returncode != 0
    assert "dependency lock contains an unpinned or unsafe entry" in result.stderr

@pytest.mark.parametrize("unsafe", [
    "https://user:SYNTHETIC_URL_SECRET@example.invalid/release",
    "https://user:SYNTHETIC%2DENCODED%2DSECRET@example.invalid/release",
    "https://example.invalid/release?token=SYNTHETIC_QUERY_SECRET",
    "https://example.invalid/release#SYNTHETIC_FRAGMENT_SECRET",
])
@pytest.mark.parametrize("builder", ["candidate", "public"])
def test_release_generators_reject_secret_bearing_asset_locations_without_echo(
    tmp_path, repo_root, unsafe, builder,
):
    output = tmp_path / builder
    if builder == "candidate":
        commit = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
            check=True, capture_output=True, text=True,
        ).stdout.strip()
        command = [
            sys.executable,
            str(repo_root / "agent-contract/tools/build_candidate_release.py"),
            "--wheel-dir", str(tmp_path / "unused-wheels"),
            "--output-dir", str(output),
            "--base-url", unsafe,
            "--commit", commit,
            "--dependency-lock", str(tmp_path / "unused.lock"),
            "--workflow-run-id", "123456",
        ]
    else:
        command = [
            sys.executable,
            str(repo_root / "agent-contract/tools/build_skill_release.py"),
            "--output-dir", str(output),
            "--base-url", unsafe,
            "--release-manifest", str(tmp_path / "unused-manifest.json"),
            "--release-manifest-url", "https://example.invalid/release/release-manifest.json",
            "--dependency-lock", str(tmp_path / "unused.lock"),
        ]
    result = subprocess.run(
        command, cwd=repo_root, capture_output=True, text=True, check=False, timeout=10,
    )
    assert result.returncode != 0
    assert "asset location is unsafe" in result.stderr.lower()
    assert unsafe not in result.stdout + result.stderr
    assert not output.exists()



@pytest.fixture
def projection_repo(tmp_path, repo_root):
    shutil.copytree(repo_root / "agent-contract/tools", tmp_path / "agent-contract/tools", ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copytree(repo_root / "agent-contract/src", tmp_path / "agent-contract/src", ignore=shutil.ignore_patterns("__pycache__"))
    target = tmp_path / f".github/skills/{NAME}/SKILL.md"
    target.parent.mkdir(parents=True)
    shutil.copyfile(repo_root / f".github/skills/{NAME}/SKILL.md", target)
    return tmp_path


def invoke(root, *arguments):
    return subprocess.run(
        [sys.executable, str(root / "agent-contract/tools/sync_skills.py"), *arguments],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )


def test_projection_drift_fails_check_and_sync_is_deterministic_scoped_and_atomic(projection_repo):
    root = projection_repo
    target = root / f".github/skills/{NAME}/SKILL.md"
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
    source = root / f"agent-contract/src/autogenesis_agent_contract/assets/skills/{NAME}/SKILL.md"
    source.write_bytes(b"Tampered source\n")
    target = root / f".github/skills/{NAME}/SKILL.md"
    before = target.read_bytes()
    assert invoke(root).returncode != 0
    assert target.read_bytes() == before


@pytest.mark.parametrize("kind", ["directory", "oversized"])
def test_unsafe_manifest_inputs_fail_before_projection(projection_repo, kind):
    root = projection_repo
    manifest = root / "agent-contract/src/autogenesis_agent_contract/assets/manifest.json"
    target = root / f".github/skills/{NAME}/SKILL.md"
    original = target.read_bytes()
    manifest.unlink()
    if kind == "directory":
        manifest.mkdir()
    else:
        with manifest.open("wb") as stream:
            stream.truncate(MAX_MANIFEST_BYTES + 1)
    result = invoke(root)
    assert result.returncode != 0
    assert "Contract integrity error" in result.stderr
    assert target.read_bytes() == original


@pytest.mark.skipif(os.name == "nt", reason="POSIX FIFO regression")
def test_fifo_manifest_fails_without_blocking_or_writing(projection_repo):
    root = projection_repo
    manifest = root / "agent-contract/src/autogenesis_agent_contract/assets/manifest.json"
    target = root / f".github/skills/{NAME}/SKILL.md"
    before = target.read_bytes()
    manifest.unlink()
    os.mkfifo(manifest)
    result = invoke(root)
    assert result.returncode != 0
    assert "Contract integrity error" in result.stderr
    assert target.read_bytes() == before


def test_oversized_canonical_asset_is_never_projected(projection_repo):
    root = projection_repo
    source = root / f"agent-contract/src/autogenesis_agent_contract/assets/skills/{NAME}/SKILL.md"
    target = root / f".github/skills/{NAME}/SKILL.md"
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
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
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
