import hashlib
import json
from pathlib import Path
import runpy
import shutil
import subprocess
import sys
import zipfile
from types import SimpleNamespace

import pytest


COMMIT_RUN = ("1" * 40, "123456", "2")
EXPECTED = {
    "autogenesis-agent-contract": "2.1.0",
    "autogenesis-appium-mcp": "0.5.0",
    "autogenesis-windows-mcp": "0.5.0",
    "autogenesis-cli": "0.2.0",
}


@pytest.fixture
def wheelhouse_module(repo_root):
    tools = str(repo_root / "agent-contract/tools")
    sys.path.insert(0, tools)
    try:
        yield runpy.run_path(str(Path(tools) / "candidate_wheelhouse.py"))
    finally:
        sys.path.remove(tools)


def _wheel(root, package, version, tag="py3-none-any", build=None):
    distribution = package.replace("-", "_").replace(".", "_")
    build_part = f"-{build}" if build else ""
    filename = f"{distribution}-{version}{build_part}-{tag}.whl"
    metadata_root = f"{distribution}-{version}.dist-info"
    with zipfile.ZipFile(root / filename, "w") as archive:
        archive.writestr(f"{metadata_root}/METADATA", f"Name: {package}\nVersion: {version}\n\n")
        archive.writestr(f"{metadata_root}/WHEEL", f"Wheel-Version: 1.0\nTag: {tag}\n")
    return root / filename


def _fixture(tmp_path, module):
    wheels = tmp_path / "first-party"
    wheels.mkdir()
    for package, version in EXPECTED.items():
        _wheel(wheels, package, version)
    third_party = tmp_path / "third-party"
    third_party.mkdir()
    dependency = _wheel(third_party, "Any.IO", "4.12.0")
    digest = hashlib.sha256(dependency.read_bytes()).hexdigest()
    lock = tmp_path / "candidate-dependencies.lock"
    lock.write_text(f"Any.IO==4.12.0 --hash=sha256:{digest}\n", encoding="utf-8")
    base_dir = tmp_path / "base"
    module["prepare_base"](wheels, lock, base_dir, *COMMIT_RUN)
    base, lock_raw = module["verify_base"](base_dir, *COMMIT_RUN)
    wheelhouses = {}
    for target in module["TARGETS"]:
        directory = tmp_path / target
        directory.mkdir()
        for row in base["wheels"]:
            if module["TARGETS"][target]["sys_platform"] in row["platforms"]:
                shutil.copyfile(base_dir / "wheels" / row["filename"], directory / row["filename"])
        shutil.copyfile(dependency, directory / dependency.name)
        document = module["wheelhouse_document"](
            directory, base, lock_raw, target, *COMMIT_RUN
        )
        (directory / module["WHEELHOUSE_MANIFEST"]).write_bytes(module["canonical_json"](document))
        wheelhouses[target] = directory
    return base_dir, wheelhouses


def _checksums(root):
    rows = {}
    for line in (root / "SHA256SUMS").read_text(encoding="ascii").splitlines():
        digest, relative = line.split("  ", 1)
        path = root / relative
        assert path.is_file()
        assert hashlib.sha256(path.read_bytes()).hexdigest() == digest
        rows[relative] = digest
    actual = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and path.name != "SHA256SUMS"
    }
    assert set(rows) == actual
    return rows


def test_exact_target_manifests_are_deterministic_and_complete(tmp_path, wheelhouse_module):
    module = wheelhouse_module
    base_dir, wheelhouses = _fixture(tmp_path, module)
    base, lock_raw = module["verify_base"](base_dir, *COMMIT_RUN)
    assert base["first_party_wheel_set_sha256"] == hashlib.sha256(
        module["canonical_json"](base["wheels"])
    ).hexdigest()
    for target, directory in wheelhouses.items():
        document, raw = module["verify_wheelhouse"](
            directory, base, lock_raw, target, *COMMIT_RUN
        )
        assert raw == module["canonical_json"](document)
        assert document["source"] == {"host": "pypi.org", "class": "default-public"}
        assert document["target"]["key"] == target
        assert {row["package"] for row in document["files"] if row["kind"] == "third-party"} == {"any-io"}
        required_first_party = {
            name for name, platforms in module["PLATFORMS"].items()
            if module["TARGETS"][target]["sys_platform"] in platforms
        }
        assert {row["package"] for row in document["files"] if row["kind"] == "first-party"} == required_first_party
        assert all(row["tags"] == ["py3-none-any"] for row in document["files"])


def test_universal_lock_projects_exact_marker_closure(wheelhouse_module):
    module = wheelhouse_module
    raw = (
        f"common==1 --hash=sha256:{'a' * 64}\n"
        f"mac-only==2 ; sys_platform == 'darwin' --hash=sha256:{'b' * 64}\n"
        f"win-only==3 ; sys_platform == 'win32' --hash=sha256:{'c' * 64}\n"
        f"old-python==4 ; python_version < '3.12' --hash=sha256:{'d' * 64}\n"
    ).encode()
    mac = module["target_lock"](raw, "darwin-arm64-py311")
    windows = module["target_lock"](raw, "win32-amd64-py312")
    assert set(mac) == {"common", "mac-only", "old-python"}
    assert set(windows) == {"common", "win-only"}
    rendered = module["render_target_lock"](mac)
    assert module["target_lock"](rendered, "darwin-arm64-py311").keys() == mac.keys()


def test_platform_qualified_root_keeps_unique_windows_transitive_out_of_mac(
    tmp_path, wheelhouse_module,
):
    wheels = tmp_path / "dist"
    wheels.mkdir()
    for package, version in EXPECTED.items():
        _wheel(wheels, package, version)
    requirements = wheelhouse_module["render_candidate_requirements"](wheels).decode().splitlines()
    windows_root = next(line for line in requirements if "autogenesis_windows_mcp" in line)
    assert windows_root.endswith(" ; sys_platform == 'win32'")
    assert all(" ; " not in line for line in requirements if line != windows_root)

    propagated = (
        f"common==1 --hash=sha256:{'b' * 64}\n"
        f"pympler==1.1 ; sys_platform == 'win32' --hash=sha256:{'a' * 64}\n"
    ).encode()
    assert "pympler" not in wheelhouse_module["target_lock"](propagated, "darwin-arm64-py311")
    assert "pympler" in wheelhouse_module["target_lock"](propagated, "win32-amd64-py312")


@pytest.mark.parametrize("mutation", [
    "missing", "extra", "renamed", "hash", "wrong-target", "wrong-run", "wrong-attempt",
    "wrong-commit", "self-consistent-substitution",
])
def test_wheelhouse_mutation_and_provenance_mixing_fail_closed(
    tmp_path, wheelhouse_module, mutation,
):
    module = wheelhouse_module
    base_dir, wheelhouses = _fixture(tmp_path, module)
    base, lock_raw = module["verify_base"](base_dir, *COMMIT_RUN)
    target = "darwin-arm64-py311"
    directory = wheelhouses[target]
    manifest_path = directory / module["WHEELHOUSE_MANIFEST"]
    document = json.loads(manifest_path.read_bytes())
    dependency = next(path for path in directory.glob("Any_IO-*.whl"))
    if mutation == "missing":
        dependency.unlink()
    elif mutation == "extra":
        _wheel(directory, "unexpected", "1.0")
    elif mutation == "renamed":
        dependency.rename(directory / "renamed-4.12.0-py3-none-any.whl")
    elif mutation == "hash":
        dependency.write_bytes(dependency.read_bytes() + b"changed")
    elif mutation == "wrong-target":
        document["target"]["key"] = "win32-amd64-py312"
        manifest_path.write_bytes(module["canonical_json"](document))
    elif mutation == "wrong-run":
        document["provenance"]["workflow_run_id"] = "654321"
        manifest_path.write_bytes(module["canonical_json"](document))
    elif mutation == "wrong-attempt":
        document["provenance"]["workflow_run_attempt"] = "3"
        manifest_path.write_bytes(module["canonical_json"](document))
    elif mutation == "wrong-commit":
        document["provenance"]["commit"] = "2" * 40
        manifest_path.write_bytes(module["canonical_json"](document))
    else:
        dependency.write_bytes(dependency.read_bytes() + b"substituted")
        row = next(row for row in document["files"] if row["package"] == "any-io")
        row["size"] = dependency.stat().st_size
        row["sha256"] = hashlib.sha256(dependency.read_bytes()).hexdigest()
        manifest_path.write_bytes(module["canonical_json"](document))
    with pytest.raises(module["WheelhouseError"]):
        module["verify_wheelhouse"](directory, base, lock_raw, target, *COMMIT_RUN)


def test_stale_cross_attempt_candidate_base_fails_closed(tmp_path, wheelhouse_module):
    module = wheelhouse_module
    base_dir, _wheelhouses = _fixture(tmp_path, module)
    manifest_path = base_dir / module["BASE_MANIFEST"]
    document = json.loads(manifest_path.read_bytes())
    document["provenance"]["workflow_run_attempt"] = "1"
    manifest_path.write_bytes(module["canonical_json"](document))
    with pytest.raises(module["WheelhouseError"], match="provenance"):
        module["verify_base"](base_dir, *COMMIT_RUN)


def test_incompatible_and_duplicate_wheels_fail_closed(tmp_path, wheelhouse_module):
    module = wheelhouse_module
    base_dir, wheelhouses = _fixture(tmp_path, module)
    base, _old_lock = module["verify_base"](base_dir, *COMMIT_RUN)
    target = "darwin-arm64-py311"
    directory = wheelhouses[target]
    dependency = next(path for path in directory.glob("Any_IO-*.whl"))
    dependency.unlink()
    incompatible = _wheel(directory, "Any.IO", "4.12.0", "cp311-cp311-manylinux_2_17_x86_64")
    digest = hashlib.sha256(incompatible.read_bytes()).hexdigest()
    lock_raw = f"Any.IO==4.12.0 --hash=sha256:{digest}\n".encode()
    with pytest.raises(module["WheelhouseError"], match="target-incompatible"):
        module["wheelhouse_document"](directory, base, lock_raw, target, *COMMIT_RUN)

    incompatible.unlink()
    first = _wheel(directory, "Any.IO", "4.12.0")
    second = _wheel(directory, "Any.IO", "4.12.0", build="1")
    hashes = " \\\n".join(
        f"    --hash=sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"
        for path in (first, second)
    )
    lock_raw = f"Any.IO==4.12.0 \\\n{hashes}\n".encode()
    with pytest.raises(module["WheelhouseError"], match="duplicate package identity"):
        module["wheelhouse_document"](directory, base, lock_raw, target, *COMMIT_RUN)

def test_target_tags_accept_abi3_and_reject_newer_macos_or_wrong_architecture(wheelhouse_module):
    compatible = wheelhouse_module["_tag_compatible"]
    assert compatible("cp310-abi3-macosx_11_0_arm64", "darwin-arm64-py311")
    assert compatible("cp310-abi3-macosx_11_0_universal2", "darwin-arm64-py311")
    assert compatible("cp310-abi3-win_amd64", "win32-amd64-py312")
    assert not compatible("cp310-abi3-macosx_12_0_arm64", "darwin-arm64-py311")
    assert not compatible("cp311-cp311-macosx_11_0_x86_64", "darwin-arm64-py311")
    assert not compatible("cp312-cp312-win32", "win32-amd64-py312")



@pytest.mark.parametrize("unsafe", [
    f"package @ https://example.invalid/a.whl --hash=sha256:{'a' * 64}\n",
    f"-e ./package --hash=sha256:{'a' * 64}\n",
    f"autogenesis-cli==0.2.0 --hash=sha256:{'a' * 64}\n",
    f"package==1 ; python_full_version >= '3.11.1' --hash=sha256:{'a' * 64}\n",
    f"package==1 ; implementation_version < '3.12.2' --hash=sha256:{'a' * 64}\n",
    "package==1\n",
])
def test_lock_rejects_vcs_editable_first_party_and_unhashed_inputs(wheelhouse_module, unsafe):
    with pytest.raises(wheelhouse_module["WheelhouseError"]):
        wheelhouse_module["target_lock"](unsafe.encode(), "darwin-arm64-py311")


def test_acquisition_uses_only_fixed_isolated_source_and_no_cache(
    tmp_path, wheelhouse_module, monkeypatch,
):
    module = wheelhouse_module
    base_dir, wheelhouses = _fixture(tmp_path, module)
    dependency = next(wheelhouses["darwin-arm64-py311"].glob("Any_IO-*.whl"))
    captured = {}

    def download(command, **kwargs):
        captured["command"] = command
        captured["environment"] = kwargs["env"]
        destination = Path(command[command.index("--dest") + 1])
        shutil.copyfile(dependency, destination / dependency.name)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(module["subprocess"], "run", download)
    poisoned_home = tmp_path / "poisoned-home"
    poisoned_home.mkdir()
    (poisoned_home / ".netrc").write_text("machine pypi.org login SYNTHETIC_USER password SYNTHETIC_SECRET\n")
    monkeypatch.setenv("HOME", str(poisoned_home))
    monkeypatch.setenv("USERPROFILE", str(poisoned_home))
    monkeypatch.setenv("NETRC", str(poisoned_home / ".netrc"))
    monkeypatch.setenv("PIP_KEYRING_PROVIDER", "import")
    for name in ("PIP_INDEX_URL", "PIP_EXTRA_INDEX_URL", "PIP_CACHE_DIR", "HTTPS_PROXY", "UV_INDEX"):
        monkeypatch.setenv(name, f"SYNTHETIC_{name}_SECRET")
    monkeypatch.setattr(module["platform"], "machine", lambda: "arm64")
    monkeypatch.setattr(module["sys"], "platform", "darwin")
    monkeypatch.setattr(module["sys"], "version_info", SimpleNamespace(major=3, minor=11))
    output = tmp_path / "acquired"
    module["acquire_wheelhouse"](base_dir, "darwin-arm64-py311", output, *COMMIT_RUN)
    command = captured["command"]
    assert command.count("--index-url") == 1
    assert command[command.index("--index-url") + 1] == "https://pypi.org/simple"
    assert "--extra-index-url" not in command
    assert all(flag in command for flag in (
        "--isolated", "--no-cache-dir", "--only-binary=:all:", "--require-hashes", "--no-deps",
    ))
    assert all(name not in captured["environment"] for name in (
        "PIP_INDEX_URL", "PIP_EXTRA_INDEX_URL", "PIP_CACHE_DIR", "HTTPS_PROXY", "UV_INDEX",
    ))
    assert captured["environment"]["HOME"] != str(poisoned_home)
    assert captured["environment"]["USERPROFILE"] == captured["environment"]["HOME"]
    assert captured["environment"]["NETRC"] == module["os"].devnull
    assert captured["environment"]["PIP_KEYRING_PROVIDER"] == "disabled"
    assert "SYNTHETIC_SECRET" not in repr(captured)
    assert module["verify_wheelhouse"](
        output, module["verify_base"](base_dir, *COMMIT_RUN)[0],
        (base_dir / module["LOCK_NAME"]).read_bytes(), "darwin-arm64-py311", *COMMIT_RUN,
    )[0]["source"] == {"host": "pypi.org", "class": "default-public"}


@pytest.mark.parametrize("target, machine, sys_platform, version", [
    ("darwin-arm64-py311", "x86_64", "darwin", (3, 11)),
    ("darwin-arm64-py311", "arm64", "darwin", (3, 12)),
    ("win32-amd64-py312", "arm64", "win32", (3, 12)),
    ("win32-amd64-py312", "AMD64", "darwin", (3, 12)),
])
def test_target_host_mismatch_fails_before_acquisition(
    wheelhouse_module, monkeypatch, target, machine, sys_platform, version,
):
    module = wheelhouse_module
    monkeypatch.setattr(module["platform"], "machine", lambda: machine)
    monkeypatch.setattr(module["sys"], "platform", sys_platform)
    monkeypatch.setattr(module["sys"], "version_info", SimpleNamespace(major=version[0], minor=version[1]))
    with pytest.raises(module["WheelhouseError"], match="does not match"):
        module["_assert_target_host"](target)


def test_offline_pip_subprocess_denies_network_before_download(tmp_path, repo_root):
    destination = tmp_path / "download"
    destination.mkdir()
    result = subprocess.run([
        sys.executable,
        str(repo_root / "agent-contract/tools/candidate_wheelhouse.py"),
        "_offline-pip", "download", "--retries", "0", "--timeout", "1", "--no-cache-dir",
        "--dest", str(destination), "--index-url", "https://example.invalid/simple",
        "autogenesis-network-denial-probe==0",
    ], capture_output=True, text=True, check=False, timeout=30)
    assert result.returncode != 0
    assert not list(destination.iterdir())



def test_candidate_builder_covers_nested_wheelhouses_and_offline_prompt(
    tmp_path, repo_root, wheelhouse_module,
):
    base_dir, wheelhouses = _fixture(tmp_path, wheelhouse_module)
    source = tmp_path / "source"
    source.mkdir()
    for relative in ("agent-contract", "appium-mcp-server", "pywinauto-mcp-server", "autogenesis-cli"):
        shutil.copytree(repo_root / relative, source / relative, ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache", ".venv"))
    subprocess.run(["git", "init", "-q", str(source)], check=True)
    subprocess.run(["git", "-C", str(source), "add", "."], check=True)
    subprocess.run([
        "git", "-C", str(source), "-c", "user.name=Candidate Contract Test",
        "-c", "user.email=candidate-contract@example.invalid", "commit", "-qm", "fixture",
    ], check=True)
    repo_root = source
    commit = subprocess.run(
        ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    # Bind fixtures to the actual clean checkout commit used by the builder.
    base_manifest = json.loads((base_dir / wheelhouse_module["BASE_MANIFEST"]).read_bytes())
    base_manifest["provenance"] = wheelhouse_module["provenance"](
        commit, "123456", "2", f"autogenesis-candidate-base-123456-2-{commit}"
    )
    (base_dir / wheelhouse_module["BASE_MANIFEST"]).write_bytes(
        wheelhouse_module["canonical_json"](base_manifest)
    )
    lock_raw = (base_dir / wheelhouse_module["LOCK_NAME"]).read_bytes()
    for target, directory in wheelhouses.items():
        document = wheelhouse_module["wheelhouse_document"](
            directory, base_manifest, lock_raw, target, commit, "123456", "2"
        )
        (directory / wheelhouse_module["WHEELHOUSE_MANIFEST"]).write_bytes(
            wheelhouse_module["canonical_json"](document)
        )
    output = tmp_path / "candidate"
    result = subprocess.run([
        sys.executable,
        str(repo_root / "agent-contract/tools/build_candidate_release.py"),
        "--base-dir", str(base_dir),
        "--darwin-wheelhouse", str(wheelhouses["darwin-arm64-py311"]),
        "--windows-wheelhouse", str(wheelhouses["win32-amd64-py312"]),
        "--output-dir", str(output),
        "--base-url", ".",
        "--commit", commit,
        "--workflow-run-id", "123456",
        "--workflow-run-attempt", "2",
    ], cwd=repo_root, capture_output=True, text=True, check=False, timeout=30)
    assert result.returncode == 0, result.stderr
    manifest_raw = (output / "candidate-manifest.json").read_bytes()
    manifest = json.loads(manifest_raw)
    assert manifest["schema_version"] == 3
    assert manifest["third_party_policy"] == "bundled-exact-target-wheelhouses-no-index"
    assert [row["target"]["key"] for row in manifest["wheelhouses"]] == list(wheelhouse_module["TARGETS"])
    for wheelhouse in manifest["wheelhouses"]:
        assert wheelhouse["manifest"]["path"].startswith(f"wheelhouse/{wheelhouse['target']['key']}/")
        assert all((output / row["path"]).is_file() for row in wheelhouse["files"])
    checksums = _checksums(output)
    assert "wheelhouse/darwin-arm64-py311/wheelhouse-manifest.json" in checksums
    assert "wheelhouse/win32-amd64-py312/wheelhouse-manifest.json" in checksums
    wheelhouse_module["verify_checksum_closure"](output)
    prompt = (output / "candidate-install-prompt.txt").read_text(encoding="utf-8")
    assert "No package-source disclosure or network acquisition is required or permitted" in prompt
    assert "select exactly one compatible target" in prompt
    assert "independently supplied positive GitHub artifact service digest" in prompt
    assert "verify the archive digest before extraction" in prompt
    assert "--find-links <verified-target-wheelhouse>" in prompt
    assert "package index, mirror, proxy, credential" in prompt
    assert hashlib.sha256(manifest_raw).hexdigest() in prompt


@pytest.mark.parametrize("mutation", ["extra", "missing", "changed", "self-entry"])
def test_candidate_checksum_closure_rejects_every_mutation(
    tmp_path, wheelhouse_module, mutation,
):
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    (candidate / "nested").mkdir()
    (candidate / "one").write_bytes(b"one")
    (candidate / "nested/two").write_bytes(b"two")
    rows = [
        f"{hashlib.sha256((candidate / relative).read_bytes()).hexdigest()}  {relative}\n"
        for relative in ("nested/two", "one")
    ]
    (candidate / "SHA256SUMS").write_text("".join(rows), encoding="ascii")
    if mutation == "extra":
        (candidate / "extra").write_bytes(b"extra")
    elif mutation == "missing":
        (candidate / "nested/two").unlink()
    elif mutation == "changed":
        (candidate / "one").write_bytes(b"changed")
    else:
        digest = hashlib.sha256((candidate / "SHA256SUMS").read_bytes()).hexdigest()
        with (candidate / "SHA256SUMS").open("a", encoding="ascii") as stream:
            stream.write(f"{digest}  SHA256SUMS\n")
    with pytest.raises(wheelhouse_module["WheelhouseError"]):
        wheelhouse_module["verify_checksum_closure"](candidate)
