"""Install local wheels and exercise only installed code in a clean business project."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import tempfile
import venv
import zipfile


def invoke(arguments, *, cwd, env):
    # Installation/test output may contain user-controlled configuration on failure.
    # Keep it in memory; evidence contains fixed status and sanitized protocol only.
    result = subprocess.run(arguments, cwd=cwd, env=env, capture_output=True, text=True, timeout=600)
    if result.returncode:
        raise RuntimeError("Clean-wheel verification command failed; no private diagnostic payload was exported")


def run_acceptance_tests(python, tests, *, cwd, env):
    # Enforce isolation at the subprocess boundary, even for an inherited pytest session.
    pytest_env = dict(env)
    for name in ("PYTEST_ADDOPTS", "PYTEST_PLUGINS"):
        pytest_env.pop(name, None)
    pytest_env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    invoke([
        str(python), "-I", "-m", "pytest", "-p", "anyio.pytest_plugin", "-q",
        "--import-mode=prepend", str(tests),
    ], cwd=cwd, env=pytest_env)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--wheel-dir", required=True, type=Path)
    parser.add_argument("--evidence-dir", required=True, type=Path)
    parser.add_argument("--mcp-version", choices=("1.23.0", "1.29.1"), default="1.29.1")
    args = parser.parse_args()
    wheel_dir = args.wheel_dir.resolve(strict=True)
    wheels = {}
    for name in ("autogenesis_agent_contract", "autogenesis_appium_mcp"):
        matches = list(wheel_dir.glob(name + "-*.whl"))
        if len(matches) != 1:
            raise RuntimeError("Exactly one local wheel per distribution is required")
        wheels[name] = matches[0]
    evidence = args.evidence_dir.resolve()
    evidence.mkdir(parents=True, exist_ok=True)
    source = Path(__file__).resolve().parents[1]
    # A caller's pre-existing evidence must not be mistaken for this run's result.
    if any(evidence.iterdir()):
        raise RuntimeError("Evidence directory must be empty")
    summary = {
        "os": platform.system(), "os_release": platform.release(),
        "python": platform.python_version(), "mcp": args.mcp_version,
        "runner_image": {key: os.environ.get(key) for key in ("ImageOS", "ImageVersion", "RUNNER_ARCH")},
        "local_wheel_sha256": {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in wheels.items()},
        "editable_install": False,
    }
    try:
        with tempfile.TemporaryDirectory(prefix="appium-business-") as temporary:
            root = Path(temporary)
            business = root / "business-project"
            business.mkdir()
            environment = root / "venv"
            venv.EnvBuilder(with_pip=True).create(environment)
            python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
            scripts = python.parent
            env = dict(os.environ)
            for name in ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV", "PYTEST_ADDOPTS", "MCP_LOG_FILE"):
                env.pop(name, None)
            env.update({
                "PATH": str(scripts) + os.pathsep + os.defpath,
                "PYTHONNOUSERSITE": "1",
                "APPIUM_WHEEL_PATH": str(wheels["autogenesis_appium_mcp"]),
                "APPIUM_SOURCE_ROOT": str(source.parent),
                "AUTOGENESIS_APPIUM_EVIDENCE_DIR": str(evidence),
            })
            invoke([
                str(python), "-I", "-m", "pip", "--disable-pip-version-check", "install",
                str(wheels["autogenesis_agent_contract"]), str(wheels["autogenesis_appium_mcp"]),
                "pytest>=8.3,<9", "mcp==" + args.mcp_version,
            ], cwd=business, env=env)
            summary["clean_install"] = {
                "exit_code": 0, "source": "local built wheels", "business_project_outside_checkout": True,
                "contract": "1.2.0", "runtime": "0.3.0",
            }
            # Copy tests and the source shim only; no runtime source or contract assets.
            checks = root / "checks"
            checks.mkdir()
            shutil.copytree(source / "tests", checks / "tests", ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"))
            shutil.copyfile(source / "simple_server.py", checks / "simple_server.py")
            shutil.copyfile(source / "conf/appium_conf.template.json", checks / "tests/fixtures/source_template.json")
            (checks / "scripts").mkdir()
            shutil.copyfile(Path(__file__), checks / "scripts/verify_wheels.py")
            run_acceptance_tests(python, checks / "tests", cwd=business, env=env)
            summary["pytest_isolation"] = {
                "entry_point_autoload": False, "explicit_plugins": ["anyio.pytest_plugin"],
                "inherited_plugin_settings_removed": True,
            }
            invoke([str(python), "-I", "-m", "pip", "check"], cwd=business, env=env)
            summary["dependency_check_exit_code"] = 0
        contents = {}
        for name, wheel in wheels.items():
            with zipfile.ZipFile(wheel) as archive:
                contents[name] = sorted(archive.namelist())
        temporary_contents = evidence / "wheel-contents.json.tmp"
        temporary_contents.write_text(json.dumps(contents, indent=2) + "\n", encoding="utf-8")
        temporary_contents.replace(evidence / "wheel-contents.json")
        summary["result"] = "passed"
        summary["evidence"] = ["ios.json", "android.json", "mac.json"]
    except Exception:
        summary["result"] = "failed"
        raise RuntimeError("Appium package verification failed; see sanitized verification.json status") from None
    finally:
        temporary_summary = evidence / "verification.json.tmp"
        temporary_summary.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        temporary_summary.replace(evidence / "verification.json")


if __name__ == "__main__":
    main()
