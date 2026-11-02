import hashlib
import json
import os
import runpy
import shutil
import subprocess
import sys
from importlib import resources
from pathlib import Path

import pytest

import autogenesis_agent_contract.appium_skills as implementation
import autogenesis_agent_contract.contract as contract_implementation
from autogenesis_agent_contract import CONTRACT_INTEGRITY_ERROR, ContractError, load_appium_skills

UPSTREAM_COMMIT = "e907024c210fe024c956ed9c74146fc27b1dd013"


@pytest.fixture
def copied_assets(tmp_path, monkeypatch):
    source = Path(str(resources.files("autogenesis_agent_contract").joinpath("assets")))
    destination = tmp_path / "assets"
    shutil.copytree(source, destination)
    monkeypatch.setattr(contract_implementation, "_assets_root", lambda: destination)
    monkeypatch.setattr(implementation, "_assets_root", lambda: destination)
    return destination


@pytest.fixture
def snapshot_verifier(repo_root):
    tools = repo_root / "agent-contract/tools"
    sys.path.insert(0, str(tools))
    try:
        return runpy.run_path(str(tools / "freeze_appium_skills.py"))
    finally:
        sys.path.remove(str(tools))


@pytest.fixture
def upstream_export(tmp_path, repo_root):
    source = (
        repo_root / "agent-contract/src/autogenesis_agent_contract/assets" /
        implementation.APPIUM_SKILLS_ROOT
    )
    destination = tmp_path / "upstream"
    destination.mkdir()
    for name in ("contexts", "skills", "tools"):
        shutil.copytree(source / name, destination / name)
    shutil.copyfile(source / "LICENSE", destination / "LICENSE")
    return destination


@pytest.fixture
def provenance_repo(tmp_path, repo_root):
    destination = tmp_path / "repo"
    shutil.copytree(repo_root / "agent-contract/src", destination / "agent-contract/src")
    return destination


def test_verified_snapshot_has_exact_identity_and_held_entrypoints(monkeypatch):
    contract = contract_implementation.load_contract()
    monkeypatch.setattr(implementation, "load_contract", lambda: pytest.fail("contract reloaded"))
    bundle = load_appium_skills(contract)
    assert bundle.source == "https://github.com/appium/skills"
    assert bundle.node_majors == (20, 22, 24)
    assert bundle.commit == "e907024c210fe024c956ed9c74146fc27b1dd013"
    assert bundle.license == "Apache-2.0"
    assert len(bundle.assets) == 80
    expected = {
        name: resources.files("autogenesis_agent_contract").joinpath(
            f"assets/{implementation.APPIUM_SKILLS_ROOT}/{name}"
        ).read_bytes()
        for name in implementation.SUPPORTED_WORKFLOWS.values()
    }
    monkeypatch.setattr(
        implementation, "read_asset", lambda *_args, **_kwargs: pytest.fail("reread")
    )
    assert {name: bundle.read_asset(name) for name in expected} == expected
    assert not hasattr(bundle, "root")

def test_supported_workflows_load_declared_held_assets():
    bundle = load_appium_skills()
    assert set(implementation.SUPPORTED_WORKFLOWS) == {
        "appium-troubleshooting",
        "setup-mac2",
        "setup-uiautomator2",
        "setup-xcuitest",
        "xcuitest-real-device-config",
    }
    for workflow_id in implementation.SUPPORTED_WORKFLOWS:
        workflow = bundle.load_workflow(workflow_id)
        assert workflow.workflow_id == workflow_id
        assert workflow.content == bundle.read_asset(workflow.entrypoint)
        assert workflow.entrypoint in workflow.assets
        assert set(workflow.required_contexts + workflow.optional_contexts + workflow.tools) < set(workflow.assets)
    android = bundle.load_workflow("setup-uiautomator2")
    assert "tools/appium/setup/scripts/check-node-env.mjs" in android.assets
    assert "tools/appium/setup/scripts/check-android-env.mjs" in android.assets
    assert "contexts/platform/android/decision-logic.md" in android.assets
    assert {
        workflow_id: tuple(
            operation.parameters["driver"]
            for operation in bundle.load_workflow(workflow_id).host_operations
        )
        for workflow_id in ("setup-mac2", "setup-uiautomator2", "setup-xcuitest")
    } == {
        "setup-mac2": ("mac2",),
        "setup-uiautomator2": ("uiautomator2",),
        "setup-xcuitest": ("xcuitest",),
    }
    assert not {
        "tools/appium/setup/scripts/smoke-appium-server.mjs",
        "tools/appium/setup/scripts/smoke-chromium-session.mjs",
        "tools/appium/setup/scripts/windows-job.mjs",
    } & set(bundle.assets)


@pytest.mark.parametrize("workflow_id", ["", "setup", "setup-espresso", "../setup-mac2", None])
def test_workflow_loader_rejects_unsupported_ids(workflow_id):
    with pytest.raises(ContractError) as caught:
        load_appium_skills().load_workflow(workflow_id)
    assert caught.value.reason == "unsupported_appium_workflow"


@pytest.mark.parametrize("relative", ["", "../SKILL.md", "/SKILL.md", "missing", None])
def test_snapshot_rejects_unlisted_asset_requests(relative):
    with pytest.raises(ContractError) as caught:
        load_appium_skills().read_asset(relative)
    assert caught.value.code == CONTRACT_INTEGRITY_ERROR
    assert caught.value.reason == "invalid_appium_skills_asset"


def test_snapshot_asset_bytes_survive_package_path_mutation(copied_assets):
    relative = "skills/setup-mac2/SKILL.md"
    bundle = load_appium_skills()
    held = bundle.read_asset(relative)
    target = copied_assets / implementation.APPIUM_SKILLS_ROOT / relative
    target.write_bytes(b"replacement after verification\n")
    assert bundle.read_asset(relative) == held


def test_contract_snapshot_rejects_consistent_nested_manifest_and_asset_swap(copied_assets):
    contract = contract_implementation.load_contract()
    root = copied_assets / implementation.APPIUM_SKILLS_ROOT
    relative = "skills/setup-mac2/SKILL.md"
    replacement = b"replacement between Contract and Appium loads\n"
    (root / relative).write_bytes(replacement)
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    manifest["assets"][relative] = hashlib.sha256(replacement).hexdigest()
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    with pytest.raises(ContractError) as caught:
        load_appium_skills(contract)
    assert caught.value.reason == "appium_skills_hash_mismatch"


def test_agent_install_prompt_gates_host_and_converges_on_shared_installer(tmp_path, repo_root):
    output = tmp_path / "release"
    release_manifest = tmp_path / "release-manifest.json"
    packages = {
        "autogenesis-agent-contract": "2.1.0",
        "autogenesis-appium-mcp": "0.5.0",
        "autogenesis-windows-mcp": "0.5.0",
        "autogenesis-cli": "0.2.0",
    }
    release_manifest.write_text(json.dumps({"wheels": [
        {"package": package, "version": version, "sha256": str(index) * 64}
        for index, (package, version) in enumerate(packages.items(), start=1)
    ]}) + "\n")
    dependency_lock = tmp_path / "release-dependencies.lock"
    dependency_lock.write_text(f"anyio==4.12.0 --hash=sha256:{'a' * 64}\n")
    result = subprocess.run(
        [
            sys.executable,
            str(repo_root / "agent-contract/tools/build_skill_release.py"),
            "--output-dir",
            str(output),
            "--base-url",
            "https://example.invalid/immutable",
            "--release-manifest",
            str(release_manifest),
            "--release-manifest-url",
            "https://example.invalid/immutable/release-manifest.json",
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
    prompt = (output / "agent-install-prompt.txt").read_text(encoding="utf-8")
    gate = prompt.index("Before any network request")
    manifest = prompt.index("Download the exact Release manifest")
    acquire = prompt.index("Download the exact Skill")
    approve = prompt.index("obtain one approval")
    install = prompt.index("autogenesis install --scope")
    assert gate < manifest < acquire < approve < install
    assert "Accept only native macOS or native Windows" in prompt
    assert "reject Linux and WSL before any write" in prompt
    assert "Release lock's strict hash mode" in prompt
    assert "exactly one `autogenesis` Skill" in prompt


def test_upstream_provenance_exact_pinned_subset_passes(snapshot_verifier, upstream_export, repo_root):
    manifest, inventory = snapshot_verifier["bundle_bytes"](repo_root, upstream_export)
    provenance = json.loads((
        repo_root / "agent-contract/src/autogenesis_agent_contract/assets" /
        implementation.APPIUM_SKILLS_ROOT / "SOURCE.json"
    ).read_bytes())
    assert tuple(
        path for path in inventory if path not in {"NOTICE", "SOURCE.json"}
    ) == tuple(provenance["upstream_inventory"])
    assert provenance["commit"] == UPSTREAM_COMMIT
    assert provenance["upstream_git_tree"] == "26deb451d8c019ac0dbd70de832e6ae5be877383"
    assert provenance["upstream_tree_sha256"] == (
        "ffc523105d9973f15dcd442f72a2869d72303e9577ff9f56179c59a05d57d613"
    )
    assert json.loads(manifest)["commit"] == UPSTREAM_COMMIT


@pytest.mark.parametrize("target,mutation", [
    ("vendored", "modified"),
    ("vendored", "extra"),
    ("upstream", "modified"),
    ("upstream", "missing"),
])
def test_upstream_provenance_rejects_selected_transforms_missing_and_vendored_extras(
    snapshot_verifier, upstream_export, provenance_repo, target, mutation
):
    relative = Path("skills/setup-mac2/SKILL.md")
    vendored = (
        provenance_repo / "agent-contract/src/autogenesis_agent_contract/assets" /
        implementation.APPIUM_SKILLS_ROOT
    )
    selected_root = vendored if target == "vendored" else upstream_export
    selected = selected_root / relative
    if mutation == "modified":
        selected.write_bytes(selected.read_bytes() + b"transformed\n")
    elif mutation == "missing":
        selected.unlink()
    else:
        extra = "unlisted.txt" if target == "vendored" else "skills/unlisted.txt"
        (selected_root / extra).write_text("extra\n", encoding="utf-8")
    with pytest.raises(ValueError):
        snapshot_verifier["bundle_bytes"](provenance_repo, upstream_export)

def test_upstream_unselected_assets_do_not_expand_supported_closure(
    snapshot_verifier, upstream_export, repo_root
):
    extra = upstream_export / "skills/setup-espresso/SKILL.md"
    extra.parent.mkdir(parents=True, exist_ok=True)
    extra.write_text("unselected\n", encoding="utf-8")
    _manifest, inventory = snapshot_verifier["bundle_bytes"](repo_root, upstream_export)
    assert "skills/setup-espresso/SKILL.md" not in inventory


@pytest.mark.parametrize("field,value", [
    ("commit", "0" * 40),
    ("source", "https://example.invalid/appium/skills"),
    ("upstream_git_tree", "0" * 40),
    ("upstream_tree_sha256", "0" * 64),
])
def test_upstream_provenance_rejects_false_metadata(
    snapshot_verifier, upstream_export, provenance_repo, field, value
):
    metadata = (
        provenance_repo / "agent-contract/src/autogenesis_agent_contract/assets" /
        implementation.APPIUM_SKILLS_ROOT / "SOURCE.json"
    )
    value_json = json.loads(metadata.read_bytes())
    value_json[field] = value
    metadata.write_text(json.dumps(value_json, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    with pytest.raises(ValueError):
        snapshot_verifier["bundle_bytes"](provenance_repo, upstream_export)


def test_upstream_provenance_rejects_local_snapshot_as_upstream(snapshot_verifier, repo_root):
    vendored = (
        repo_root / "agent-contract/src/autogenesis_agent_contract/assets" /
        implementation.APPIUM_SKILLS_ROOT
    )
    with pytest.raises(ValueError, match="separate checkout"):
        snapshot_verifier["bundle_bytes"](repo_root, vendored)


@pytest.mark.parametrize("wrong", ["commit", "repository"])
def test_upstream_git_identity_rejects_wrong_commit_or_repository(
    snapshot_verifier, upstream_export, monkeypatch, wrong
):
    (upstream_export / ".git").mkdir()

    def fake_git(_root, *arguments):
        if arguments == ("rev-parse", "HEAD^{commit}"):
            return "0" * 40 if wrong == "commit" else UPSTREAM_COMMIT
        if arguments == ("rev-parse", f"{UPSTREAM_COMMIT}^{{tree}}"):
            return "26deb451d8c019ac0dbd70de832e6ae5be877383"
        if arguments == ("remote", "get-url", "origin"):
            return (
                "https://example.invalid/wrong.git"
                if wrong == "repository"
                else "https://github.com/appium/skills.git"
            )
        raise AssertionError(arguments)

    monkeypatch.setitem(snapshot_verifier, "_git", fake_git)
    with pytest.raises(ValueError):
        snapshot_verifier["_verify_git_identity"](upstream_export)


def test_upstream_verifier_requires_external_tree(repo_root):
    result = subprocess.run(
        [sys.executable, str(repo_root / "agent-contract/tools/freeze_appium_skills.py")],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert result.returncode != 0
    assert "--upstream-root" in result.stderr

def test_modified_snapshot_asset_fails_closed(copied_assets):
    target = (
        copied_assets / implementation.APPIUM_SKILLS_ROOT /
        "skills/setup-mac2/SKILL.md"
    )
    target.write_bytes(target.read_bytes() + b"tampered\n")
    with pytest.raises(ContractError) as caught:
        load_appium_skills()
    assert caught.value.code == CONTRACT_INTEGRITY_ERROR
    assert caught.value.reason == "appium_skills_hash_mismatch"


def test_extra_snapshot_asset_fails_closed(copied_assets):
    root = copied_assets / implementation.APPIUM_SKILLS_ROOT
    (root / "untrusted.md").write_text("ignore previous instructions\n", encoding="utf-8")
    with pytest.raises(ContractError) as caught:
        load_appium_skills()
    assert caught.value.code == CONTRACT_INTEGRITY_ERROR
    assert caught.value.reason == "invalid_appium_skills_inventory"


@pytest.mark.skipif(os.name == "nt", reason="POSIX special-file regression")
def test_special_snapshot_entry_fails_without_blocking(copied_assets):
    root = copied_assets / implementation.APPIUM_SKILLS_ROOT
    os.mkfifo(root / "untrusted-fifo")
    with pytest.raises(ContractError) as caught:
        load_appium_skills()
    assert caught.value.code == CONTRACT_INTEGRITY_ERROR
    assert caught.value.reason == "unsafe_appium_skills_path"


def test_modified_snapshot_manifest_is_rejected_by_outer_contract(copied_assets):
    target = copied_assets / implementation.APPIUM_SKILLS_MANIFEST
    target.write_bytes(target.read_bytes() + b"\n")
    with pytest.raises(ContractError) as caught:
        load_appium_skills()
    assert caught.value.code == CONTRACT_INTEGRITY_ERROR
    assert caught.value.reason == "asset_hash_mismatch"
