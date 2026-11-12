import base64
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import re
import runpy
import shutil
import secrets
import subprocess
import sys
import threading
from importlib import resources
import zipfile

import pytest

from autogenesis_agent_contract._asset_io import MAX_ASSET_BYTES, MAX_MANIFEST_BYTES

NAME = "autogenesis"

def _assert_hardened_install_prompt(prompt, channel):
    assert f"exact {channel} identity" in prompt
    assert "local private per-user parent" in prompt
    assert "current-user ownership" in prompt
    assert "deny every other OS identity write, create, delete, or delete-child control" in prompt
    assert "shared, untrusted, unsafe, or network-backed parents" in prompt
    assert "reject every symlink or reparse component without following it" in prompt
    assert "at least 128 bits of entropy for this exact installation" in prompt
    assert "immutable plan naming that exact path" in prompt
    assert "explicit user approval" in prompt
    assert "before creating the leaf" in prompt
    assert "pre-existing state" in prompt
    assert "environment's absolute Python or entrypoints only" in prompt
    assert "atomically create the exact approved leaf with fail-if-exists and no-follow semantics" in prompt
    assert "newly generated random path, a fresh immutable plan, and fresh approval" in prompt
    assert "exclusive transaction lock for the complete create, install, verify, rollback, and cleanup lifecycle" in prompt
    assert "reject a second installer while it is held" in prompt
    assert "stable parent and leaf identities" in prompt and "private unpredictable ownership marker" in prompt
    assert "Before and after every reservation, venv, staging, download, extraction, install" in prompt
    assert "lock, parent identity/ownership/permissions, exact leaf identity, and marker still match" in prompt
    assert "standard pathname-based stdlib `venv`, `pip`, and installed AutoGenesis or Runtime CLI" in prompt
    assert "trusts processes already running as the same OS user identity" in prompt
    assert "does not claim to prevent a malicious same-user process" in prompt
    assert "do not propose a privileged or sandboxed native Bootstrap" in prompt
    assert "failure, cancellation, denial, digest or identity mismatch, supersession, or rollback" in prompt
    assert "marker mismatch" in prompt and "forbids entering or deleting that state" in prompt
    assert "Preserve every pre-existing or mismatched environment" in prompt
    assert "treat it as `undisclosed` and stop before installation" in prompt
    assert "Redaction after reading" in prompt and "are forbidden" in prompt
    assert "platform-native atomic no-replace semantics" in prompt
    assert "no-follow semantics where supported" in prompt
    assert all(removed not in prompt for removed in (
        "handle-relative no-follow native primitives",
        "entire operation is constrained through those handles",
        "never fall back to pathname checks",
    ))
    assert "isolated mode (`-I`, `-E`, `-s`, plus `-S`" in prompt
    assert "all `PYTHON*` variables (including `PYTHONPATH`)" in prompt and "`sitecustomize`" in prompt
    assert "Remove every ambient `PIP_*` and `UV_*` variable by name without reading its value" in prompt
    assert "`PIP_CONFIG_FILE` to `/dev/null` on macOS and the exact lowercase pip sentinel `nul` on Windows" in prompt
    assert "`pip --isolated`" in prompt and "sole package manager" in prompt
    assert "never invoke uv or another package manager" in prompt and "`uv --no-config`" not in prompt
    assert "--no-index --no-cache-dir --find-links <transaction-stage> --require-hashes --no-deps" in prompt
    assert "After staging, every package operation is offline and no-index" in prompt
    assert "managed-policy`, `user-approved`, `default-public`, or `undisclosed" in prompt
    assert "canonical lowercase ASCII DNS hostname" in prompt
    assert "self-attestation by an untrusted interface" in prompt
    assert all(forbidden not in prompt.lower() for forbidden in (
        "pip config", "uv config", "printenv", "authorization header:",
    ))


def test_poisoned_venv_site_pip_config_cannot_escape_reserved_offline_install(tmp_path, repo_root):
    module = runpy.run_path(str(repo_root / "agent-contract/tools/install_prompt.py"))
    prompt = module["hardened_install_contract"](
        channel="Candidate",
        external_anchor="Verify the exact external anchor.",
        acquire="Acquire authenticated local assets.",
        install="Install authenticated wheels.",
        cleanup="prompt-created staging state",
    )
    assert "`PIP_CONFIG_FILE` to `/dev/null` on macOS and the exact lowercase pip sentinel `nul` on Windows" in prompt
    assert "`pip --isolated`" in prompt and "sole package manager" in prompt
    assert "never invoke uv or another package manager" in prompt and "`uv --no-config`" not in prompt

    private_parent = tmp_path / "private-user-installations"
    private_parent.mkdir(mode=0o700)
    random_leaf = f"autogenesis-{secrets.token_bytes(16).hex()}"
    assert len(bytes.fromhex(random_leaf.removeprefix("autogenesis-"))) * 8 == 128
    transaction = private_parent / random_leaf
    transaction.mkdir(mode=0o700)
    stage = transaction / "stage"
    stage.mkdir()
    control_environment = transaction / "control-venv"
    environment = transaction / "venv"

    outside = tmp_path / "outside-transaction"
    control_target = outside / "control-target"
    outside_target = outside / "target"
    outside_cache = outside / "cache"
    outside_prefix = outside / "prefix"
    poison_home = outside / "home"
    control_target.mkdir(parents=True)
    outside_target.mkdir()
    outside_cache.mkdir()
    poison_home.mkdir()

    requests = []

    class PoisonSource(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append(self.path)
            self.send_response(500)
            self.end_headers()

        def log_message(self, _format, *args):
            pass

    source = ThreadingHTTPServer(("127.0.0.1", 0), PoisonSource)
    source_thread = threading.Thread(target=source.serve_forever, daemon=True)
    source_thread.start()
    poison_url = f"http://127.0.0.1:{source.server_port}/simple"

    wheel = stage / "poisonproof-1.0-py3-none-any.whl"
    dist_info = "poisonproof-1.0.dist-info"
    wheel_members = {
        "poisonproof/__init__.py": b"VALUE = 'offline-ok'\n",
        f"{dist_info}/METADATA": b"Metadata-Version: 2.1\nName: poisonproof\nVersion: 1.0\n\n",
        f"{dist_info}/WHEEL": b"Wheel-Version: 1.0\nGenerator: autogenesis-test\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
    }
    record_rows = []
    for name, content in wheel_members.items():
        digest = base64.urlsafe_b64encode(hashlib.sha256(content).digest()).rstrip(b"=").decode("ascii")
        record_rows.append(f"{name},sha256={digest},{len(content)}")
    record_rows.append(f"{dist_info}/RECORD,,")
    with zipfile.ZipFile(wheel, "w") as archive:
        for name, content in wheel_members.items():
            archive.writestr(name, content)
        archive.writestr(f"{dist_info}/RECORD", "\n".join(record_rows) + "\n")
    requirements = transaction / "requirements.txt"
    requirements.write_text(
        f"poisonproof==1.0 --hash=sha256:{hashlib.sha256(wheel.read_bytes()).hexdigest()}\n",
        encoding="ascii",
    )

    exclusive = os.O_RDWR | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0)
    lock_descriptor = os.open(transaction / ".transaction.lock", exclusive, 0o600)
    try:
        with pytest.raises(FileExistsError):
            os.open(transaction / ".transaction.lock", exclusive, 0o600)
        marker_descriptor = os.open(transaction / ".ownership-marker", exclusive, 0o600)
        os.close(marker_descriptor)

        allowed = ("SYSTEMROOT", "WINDIR", "TEMP", "TMP", "TMPDIR")
        child_environment = {name: os.environ[name] for name in allowed if name in os.environ}
        child_environment["HOME"] = str(poison_home)
        child_environment["USERPROFILE"] = str(poison_home)
        child_environment["APPDATA"] = str(poison_home)
        assert not any(name.startswith(("PIP_", "UV_", "PYTHON")) for name in child_environment)
        for destination in (control_environment, environment):
            created = subprocess.run(
                [sys.executable, "-I", "-E", "-s", "-m", "venv", str(destination)],
                env=child_environment,
                capture_output=True,
                text=True,
                check=False,
                timeout=60,
            )
            assert created.returncode == 0, created.stderr

        executable = "Scripts/python.exe" if os.name == "nt" else "bin/python"
        config_name = "pip.ini" if os.name == "nt" else "pip.conf"
        control_python = control_environment / executable
        environment_python = environment / executable
        (control_environment / config_name).write_text(
            f"[global]\ntarget = {control_target}\n",
            encoding="utf-8",
        )
        (environment / config_name).write_text(
            "[global]\n"
            f"target = {outside_target}\n"
            f"prefix = {outside_prefix}\n"
            f"index-url = {poison_url}\n"
            f"cache-dir = {outside_cache}\n",
            encoding="utf-8",
        )

        def install_command(python):
            return [
                str(python), "-I", "-E", "-s", "-m", "pip",
                "--isolated", "--disable-pip-version-check", "install", "--no-input",
                "--no-index", "--no-cache-dir", "--find-links", str(stage),
                "--require-hashes", "--no-deps", "-r", str(requirements),
            ]

        control = subprocess.run(
            install_command(control_python),
            env=child_environment,
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
        assert control.returncode == 0, control.stderr
        assert (control_target / "poisonproof" / "__init__.py").is_file()
        control_import = subprocess.run(
            [str(control_python), "-I", "-E", "-s", "-c", "import poisonproof"],
            env=child_environment,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        assert control_import.returncode != 0

        pip_environment = dict(child_environment)
        pip_environment["PIP_CONFIG_FILE"] = "nul" if os.name == "nt" else "/dev/null"
        assert {name for name in pip_environment if name.startswith("PIP_")} == {"PIP_CONFIG_FILE"}
        assert not any(name.startswith("UV_") for name in pip_environment)
        installed = subprocess.run(
            install_command(environment_python),
            env=pip_environment,
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
        assert installed.returncode == 0, installed.stderr
        imported = subprocess.run(
            [
                str(environment_python), "-I", "-E", "-s", "-c",
                "import importlib.metadata, poisonproof; print(poisonproof.VALUE + '|' + importlib.metadata.version('poisonproof'))",
            ],
            env=child_environment,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        assert imported.returncode == 0, imported.stderr
        assert imported.stdout.strip() == "offline-ok|1.0"
        assert requests == []
        assert list(outside_target.iterdir()) == []
        assert list(outside_cache.iterdir()) == []
        assert not outside_prefix.exists()
        assert (transaction / ".ownership-marker").is_file()
    finally:
        os.close(lock_descriptor)
        source.shutdown()
        source.server_close()
        source_thread.join(timeout=5)


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
        "verified local private per-user parent",
        "at least 128 bits of cryptographic randomness",
        "includes that exact path in the immutable plan",
        "explicit approval before reservation",
        "fail-if-exists and no-follow semantics",
        "exclusive transaction lock",
        "reject a concurrent installer",
        "Standard pathname-based stdlib `venv`, `pip`",
        "same OS user identity",
        "does not claim to prevent malicious same-user replacement",
        "privileged or sandboxed native Bootstrap",
        "Use only the disposable environment's absolute Python and entrypoints",
        "exact positive Actions run and run attempt",
        "positive observed artifact ID",
        "checksums cover every final asset including the prompt and exclude only themselves",
        "Redaction after reading is not a safety boundary",
        "becomes `undisclosed`, and stops installation",
        "cancellation, denial, identity/digest mismatch, supersession, or rollback",
        "marker mismatch",
        "forbids entering or deleting that state",
        "Never delete or repurpose a pre-existing or mismatched object",
        "PYTHONPATH", "sitecustomize", "offline and no-index", "PIP_CONFIG_FILE",
        "`/dev/null` on macOS", "lowercase `nul` on Windows", "--isolated",
        "managed-policy`, `user-approved`, `default-public`, or `undisclosed",
        "private unpredictable ownership marker",
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
    base = "https://github.com/FSQ-lab/AutoGenesis/releases/download/agent-contract-v2.1.0"
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


@pytest.mark.parametrize("unsafe", [
    "https://user:SYNTHETIC_URL_SECRET@example.invalid/release",
    "https://user:SYNTHETIC%2DENCODED%2DSECRET@example.invalid/release",
    "https://github.com:443/FSQ-lab/AutoGenesis/releases/download/agent-contract-v2.1.0",
    "https://github.com/FSQ-lab/AutoGenesis/releases/download/../agent-contract-v2.1.0",
    "https://github.com/FSQ-lab\\AutoGenesis/releases/download/agent-contract-v2.1.0",
    "https://github.com/FSQ-lab/AutoGenesis/releases/download/agent-contract-v2.1.0 ",
    "https://github.com/FSQ-lab/AutoGenesis/releases/download/agent-contract-v2.1.0/SYNTHETIC_PATH_SECRET",
    "https://example.invalid/release?token=SYNTHETIC_QUERY_SECRET",
    "https://example.invalid/release#SYNTHETIC_FRAGMENT_SECRET",
    "https://example.invalid/release\rSYNTHETIC_CR_SECRET",
    "https://example.invalid/release\nSYNTHETIC_LF_SECRET",
    "https://example.invalid/release\tSYNTHETIC_TAB_SECRET",
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
            "--base-dir", str(tmp_path / "unused-base"),
            "--darwin-wheelhouse", str(tmp_path / "unused-darwin"),
            "--windows-wheelhouse", str(tmp_path / "unused-windows"),
            "--output-dir", str(output),
            "--base-url", unsafe,
            "--commit", commit,
            "--workflow-run-id", "123456",
            "--workflow-run-attempt", "2",
        ]
    else:
        command = [
            sys.executable,
            str(repo_root / "agent-contract/tools/build_skill_release.py"),
            "--output-dir", str(output),
            "--base-url", unsafe,
            "--release-manifest", str(tmp_path / "unused-manifest.json"),
            "--release-manifest-url", "https://github.com/FSQ-lab/AutoGenesis/releases/download/agent-contract-v2.1.0/release-manifest.json",
            "--dependency-lock", str(tmp_path / "unused.lock"),
        ]
    result = subprocess.run(
        command, cwd=repo_root, capture_output=True, text=True, check=False, timeout=10,
    )
    assert result.returncode != 0
    assert "asset location is unsafe" in result.stderr.lower()
    assert unsafe not in result.stdout + result.stderr
    assert not output.exists()
@pytest.mark.parametrize("unsafe_manifest", [
    "https://user:SYNTHETIC_USERINFO_SECRET@github.com/FSQ-lab/AutoGenesis/releases/download/agent-contract-v2.1.0/release-manifest.json",
    "https://github.com/FSQ-lab/AutoGenesis/releases/download/agent-contract-v2.1.0/SYNTHETIC_CREDENTIAL_PATH/release-manifest.json",
    "https://github.com/FSQ-lab/AutoGenesis/releases/download/agent-contract-v2.1.0/release-manifest.json%3fSYNTHETIC_PERCENT_SECRET",
    "https://github.com/FSQ-lab/AutoGenesis/releases/download/agent-contract-v2.1.0/release-manifest.json\rSYNTHETIC_CR_SECRET",
    "https://github.com/FSQ-lab/AutoGenesis/releases/download/agent-contract-v2.1.0/release-manifest.json\nSYNTHETIC_LF_SECRET",
    "https://github.com/FSQ-lab/AutoGenesis/releases/download/agent-contract-v2.1.0/release-manifest.json\tSYNTHETIC_TAB_SECRET",
])
def test_public_generator_rejects_manifest_url_injection_without_echo(tmp_path, repo_root, unsafe_manifest):
    output = tmp_path / "release"
    result = subprocess.run([
        sys.executable,
        str(repo_root / "agent-contract/tools/build_skill_release.py"),
        "--output-dir", str(output),
        "--base-url", "https://github.com/FSQ-lab/AutoGenesis/releases/download/agent-contract-v2.1.0",
        "--release-manifest", str(tmp_path / "unused-manifest.json"),
        "--release-manifest-url", unsafe_manifest,
        "--dependency-lock", str(tmp_path / "unused.lock"),
    ], cwd=repo_root, capture_output=True, text=True, check=False, timeout=10)
    assert result.returncode != 0
    assert "asset location is unsafe" in result.stderr.lower()
    assert unsafe_manifest not in result.stdout + result.stderr
    assert not output.exists()




@pytest.mark.parametrize(("host", "source"), [
    ("https://pypi.org", "default-public"),
    ("pypi.org:443", "default-public"),
    ("user@pypi.org", "user-approved"),
    ("pypi.org/SYNTHETIC_PATH_CANARY", "managed-policy"),
    ("pypi.org%2fSYNTHETIC_PERCENT_CANARY", "managed-policy"),
    ("pypi.org\nSYNTHETIC_CONTROL_CANARY", "default-public"),
    ("Pypi.org", "default-public"),
    ("pypi.org", "SYNTHETIC_SOURCE_CLASS_CANARY"),
])
def test_source_metadata_injection_becomes_undisclosed_before_echo(repo_root, host, source):
    module = runpy.run_path(str(repo_root / "agent-contract/tools/install_prompt.py"))
    assert module["validate_source_metadata"](host, source) == ("undisclosed", "undisclosed")


@pytest.mark.parametrize(("host", "source"), [
    ("pypi.org", "default-public"),
    ("packages.example", "managed-policy"),
    ("192.0.2.1", "user-approved"),
    ("[2001:db8::1]", "managed-policy"),
])
def test_source_metadata_accepts_only_canonical_host_and_finite_source_class(repo_root, host, source):
    module = runpy.run_path(str(repo_root / "agent-contract/tools/install_prompt.py"))
    assert module["validate_source_metadata"](host, source) == (host, source)





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
