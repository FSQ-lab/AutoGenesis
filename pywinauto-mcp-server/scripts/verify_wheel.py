"""Install local wheels and verify them outside the checkout in a fresh venv."""

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import venv
from pathlib import Path


def atomic_write(root, name, content):
    temporary = root / (name + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(root / name)


def sanitized(text, environment):
    secrets = set()
    for key, value in environment.items():
        if value and re.search(r"password|secret|token|credential|api[_-]?key|authorization", key, re.I):
            secrets.update((value, json.dumps(value, ensure_ascii=False)[1:-1], repr(value)[1:-1]))
    for secret in sorted(secrets, key=len, reverse=True):
        text = text.replace(secret, "[REDACTED]")
    return re.sub(r"(https?://)[^/@\s]+:[^/@\s]+@", r"\1[REDACTED]@", text)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheel-dir", required=True, type=Path)
    parser.add_argument("--mcp-version", required=True, choices=["1.23.0", "1.29.1"])
    parser.add_argument("--evidence-dir", required=True, type=Path)
    args = parser.parse_args()
    wheel_dir = args.wheel_dir.resolve(strict=True)
    wheels = []
    for pattern in ("autogenesis_agent_contract-1.0.0-*.whl", "autogenesis_windows_mcp-0.1.0-*.whl"):
        candidates = sorted(wheel_dir.glob(pattern))
        if len(candidates) != 1:
            raise SystemExit("Supply exactly one local contract 1.0.0 wheel and one Windows runtime 0.1.0 wheel.")
        wheels.append(candidates[0])
    args.evidence_dir.mkdir(parents=True, exist_ok=True)
    evidence = args.evidence_dir.resolve(strict=True)
    package_root = Path(__file__).resolve().parents[1]
    environment = os.environ.copy()
    for key in list(environment):
        if key in {"PYTHONPATH", "PYTHONHOME", "PYTEST_ADDOPTS", "PYTEST_PLUGINS"} or key.startswith("PIP_"):
            environment.pop(key, None)
    environment.update({
        "PIP_CONFIG_FILE": os.devnull,
        "PYTHONNOUSERSITE": "1",
        "PYTHONUTF8": "1",
        "AUTOGENESIS_WHEEL_DIR": str(wheel_dir),
        "AUTOGENESIS_WINDOWS_EVIDENCE": str(evidence),
    })

    def run(command, cwd, name):
        completed = subprocess.run(command, cwd=cwd, env=environment, capture_output=True, text=True, encoding="utf-8", errors="replace")
        output = sanitized(completed.stdout + completed.stderr, environment)
        atomic_write(evidence, name, output)
        if completed.returncode:
            raise SystemExit("Clean-wheel verification failed; consult the sanitized evidence log.")
        return completed.stdout

    with tempfile.TemporaryDirectory(prefix="autogenesis-windows-acceptance-") as temporary:
        root = Path(temporary)
        business = root / "business"
        business.mkdir()
        # Only acceptance code and the real thin source launcher are copied.
        # Runtime and canonical assets must resolve exclusively from wheels.
        shutil.copytree(package_root / "tests", business / "tests", ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"))
        source = root / "source-run"
        source.mkdir()
        shutil.copy2(package_root / "simple_server.py", source / "simple_server.py")
        environment["AUTOGENESIS_SOURCE_SCRIPT"] = str(source / "simple_server.py")
        venv.create(root / "venv", with_pip=True)
        python = root / "venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        run([
            str(python), "-I", "-m", "pip", "--disable-pip-version-check", "install",
            "--index-url", "https://pypi.org/simple", *map(str, wheels),
            "mcp==" + args.mcp_version, "pytest>=8.3,<9", "packaging>=24,<27",
        ], business, "install.log")
        identity_program = """
import json
import platform
from importlib.metadata import version
import autogenesis_windows_mcp
import autogenesis_agent_contract
from autogenesis_agent_contract import load_contract
print(json.dumps({
    "python": platform.python_version(), "platform": platform.platform(),
    "mcp": version("mcp"), "runtime": version("autogenesis-windows-mcp"),
    "runtime_module": autogenesis_windows_mcp.__file__,
    "contract_module": autogenesis_agent_contract.__file__,
    "identity": load_contract().identity.to_dict(),
}))
"""
        identity = json.loads(run([str(python), "-I", "-c", identity_program], business, "installed-identity.json"))
        for key in ("runtime_module", "contract_module"):
            if not Path(identity[key]).resolve().is_relative_to((root / "venv").resolve()):
                raise SystemExit("Installed packages resolved outside the clean virtual environment.")
        identity.update({
            "runner_image": os.environ.get("ImageOS"),
            "runner_image_version": os.environ.get("ImageVersion"),
            "verification_scope": "Windows package/protocol" if os.name == "nt" else "metadata/import only",
            "wheels": [{"name": wheel.name, "sha256": hashlib.sha256(wheel.read_bytes()).hexdigest()} for wheel in wheels],
        })
        atomic_write(evidence, "environment.json", sanitized(json.dumps(identity, indent=2) + chr(10), environment))
        selected = business / "tests" if os.name == "nt" else business / "tests/test_package.py"
        junit = root / "pytest.xml"
        try:
            run([
                str(python), "-I", "-m", "pytest", "--import-mode=importlib", str(selected),
                "-o", "addopts=--strict-markers",
                "-o", "markers=windows: requires the real Windows automation dependencies",
                "--junitxml", str(junit), "-ra",
            ], business, "verification.log")
        finally:
            if junit.exists():
                atomic_write(evidence, "pytest.xml", sanitized(junit.read_text(encoding="utf-8"), environment))
        # Test code performs canary checks before publishing protocol evidence.
        # Also remove inherited credential values from every textual artifact.
        for artifact in evidence.iterdir():
            if artifact.suffix in {".log", ".json", ".xml"}:
                original = artifact.read_text(encoding="utf-8")
                cleaned = sanitized(original, environment)
                if original != cleaned:
                    atomic_write(evidence, artifact.name, cleaned)
    print("Clean-wheel verification passed; sanitized evidence is ready for independent review.")


if __name__ == "__main__":
    main()
