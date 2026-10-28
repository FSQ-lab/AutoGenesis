"""Exercise the acceptance launch against a real, installed pytest entry point."""

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import sysconfig
import venv


def load_verifier():
    path = Path(__file__).parents[1] / "scripts/verify_wheel.py"
    spec = importlib.util.spec_from_file_location("windows_wheel_verifier", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_acceptance_rejects_autoloaded_and_inherited_third_party_plugins(tmp_path):
    verifier = load_verifier()
    environment = tmp_path / "isolated-python"
    venv.EnvBuilder(with_pip=False).create(environment)
    python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    packages = environment / (
        "Lib/site-packages" if os.name == "nt"
        else f"lib/python{sys.version_info.major}.{sys.version_info.minor}/site-packages"
    )
    # Reuse installed test dependencies; keep the synthetic distribution private to this venv.
    paths = {sysconfig.get_path("purelib"), sysconfig.get_path("platlib")}
    (packages / "test-dependencies.pth").write_text("\n".join(sorted(paths)) + "\n", encoding="utf-8")
    (packages / "thirdparty_blocker.py").write_text(
        "import os\nfrom pathlib import Path\n"
        "Path(os.environ['WINDOWS_PLUGIN_MARKER']).write_text('imported')\n"
        "raise ModuleNotFoundError('filelock')\n", encoding="utf-8",
    )
    distribution = packages / "thirdparty_blocker-1.0.dist-info"
    distribution.mkdir()
    (distribution / "METADATA").write_text("Metadata-Version: 2.1\nName: thirdparty-blocker\nVersion: 1.0\n", encoding="utf-8")
    (distribution / "entry_points.txt").write_text("[pytest11]\nthirdparty_blocker = thirdparty_blocker\n", encoding="utf-8")
    suite = tmp_path / "business-project"
    suite.mkdir()
    (suite / "test_async_probe.py").write_text(
        "import os\nfrom pathlib import Path\nimport anyio\nimport pytest\n"
        "@pytest.fixture\ndef anyio_backend():\n    return 'asyncio'\n"
        "@pytest.mark.anyio\nasync def test_async_acceptance():\n"
        "    await anyio.sleep(0)\n"
        "    Path(os.environ['WINDOWS_ASYNC_PROOF']).write_text('passed')\n",
        encoding="utf-8",
    )
    imported = tmp_path / "plugin-imported"
    completed = tmp_path / "async-completed"
    baseline_env = dict(os.environ, WINDOWS_PLUGIN_MARKER=str(imported), WINDOWS_ASYNC_PROOF=str(completed))
    for key in ("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "PYTEST_ADDOPTS", "PYTEST_PLUGINS", "AUTOGENESIS_WINDOWS_EVIDENCE"):
        baseline_env.pop(key, None)
    # Demonstrate the original pre-collection failure with genuine pytest11 discovery.
    baseline = subprocess.run(
        [str(python), "-I", "-m", "pytest", "-q", str(suite)],
        cwd=suite, env=baseline_env, capture_output=True, text=True, timeout=30,
    )
    assert baseline.returncode != 0
    assert imported.read_text() == "imported"
    assert "ModuleNotFoundError: filelock" in baseline.stderr
    assert not completed.exists()
    imported.unlink()

    # Autoload disabling alone does not block explicit plugins inherited via these variables.
    hostile_env = dict(baseline_env, PYTEST_DISABLE_PLUGIN_AUTOLOAD="", PYTEST_PLUGINS="thirdparty_blocker", PYTEST_ADDOPTS="-p thirdparty_blocker")
    acceptance = verifier.run_acceptance_tests(python, suite, cwd=suite, env=hostile_env)
    assert acceptance.returncode == 0
    assert not imported.exists()
    assert completed.read_text() == "passed"
    assert hostile_env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] == ""
    assert hostile_env["PYTEST_PLUGINS"] == "thirdparty_blocker"
    destination = os.environ.get("AUTOGENESIS_WINDOWS_EVIDENCE")
    if destination:
        root = Path(destination).resolve(strict=True)
        temporary = root / "plugin-isolation.json.tmp"
        temporary.write_text(json.dumps({
            "unprotected_autoload_failed_before_collection": True,
            "failure_reproduced": "ModuleNotFoundError: filelock",
            "protected_launch_exit_code": 0,
            "third_party_plugin_imported_during_acceptance": False,
            "explicit_anyio_async_test_completed": True,
            "inherited_pytest_plugins_and_addopts_ignored": True,
        }, indent=2) + "\n", encoding="utf-8")
        temporary.replace(root / "plugin-isolation.json")
