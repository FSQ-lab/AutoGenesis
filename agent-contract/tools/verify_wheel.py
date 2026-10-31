"""Integration Lead entrypoint: test a built wheel in a clean business project."""

import argparse
import json
import os
import subprocess
import tempfile
import venv
from pathlib import Path

from _files import atomic_write


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheel-dir", type=Path, required=True)
    parser.add_argument("--mcp-version", choices=("1.23.0", "1.29.1"), required=True)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    args = parser.parse_args()
    wheels = sorted(args.wheel_dir.resolve(strict=True).glob("autogenesis_agent_contract-2.2.0-*.whl"))
    if len(wheels) != 1:
        raise SystemExit("Supply a directory containing exactly one built contract 2.2.0 wheel.")
    args.evidence_dir.mkdir(parents=True, exist_ok=True)
    evidence = args.evidence_dir.resolve(strict=True)
    package_root = Path(__file__).resolve().parents[1]
    environment = os.environ.copy()
    for key in ("PYTHONPATH", "PYTHONHOME", "PYTEST_ADDOPTS", "PYTEST_PLUGINS"):
        environment.pop(key, None)
    environment["PYTHONNOUSERSITE"] = "1"
    environment["AUTOGENESIS_EVIDENCE_DIR"] = str(evidence)
    with tempfile.TemporaryDirectory(prefix="autogenesis-contract-acceptance-") as temporary:
        root = Path(temporary)
        business = root / "business"
        business.mkdir()
        venv.create(root / "venv", with_pip=True)
        python = root / "venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        subprocess.run([
            str(python), "-I", "-m", "pip", "--disable-pip-version-check", "install",
            str(wheels[0]), f"mcp=={args.mcp_version}", "pytest>=8.3,<9",
        ], cwd=business, env=environment, check=True)
        identity_program = (
            "import json, platform; from importlib.metadata import version; "
            "from autogenesis_agent_contract import load_contract; "
            "print(json.dumps({'python': platform.python_version(), 'platform': platform.platform(), "
            "'mcp': version('mcp'), 'identity': load_contract().identity.to_dict()}))"
        )
        result = subprocess.run([str(python), "-I", "-c", identity_program], cwd=business, env=environment, text=True, capture_output=True, check=True)
        details = json.loads(result.stdout)
        details.update({"runner_image": os.environ.get("ImageOS"), "runner_image_version": os.environ.get("ImageVersion")})
        details["eval_requests"] = "prepared"
        atomic_write(evidence, "environment.json", (json.dumps(details, indent=2) + "\n").encode())
        subprocess.run([
            str(python), "-I", str(package_root / "evals/prepare.py"),
            "--output-dir", str(evidence / "eval-requests"),
        ], cwd=business, env=environment, check=True)
        subprocess.run([
            str(python), "-I", "-m", "pytest", "--import-mode=importlib",
            "-c", str(package_root / "pyproject.toml"), str(package_root / "tests"),
            "--junitxml", str(evidence / "pytest.xml"), "-ra",
        ], cwd=business, env=environment, check=True)


if __name__ == "__main__":
    main()
