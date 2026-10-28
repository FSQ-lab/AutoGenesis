"""Prepare paired requests; an independent agent harness must execute them."""

import argparse
import json
import os
import runpy
import tempfile
from pathlib import Path

from autogenesis_agent_contract import load_contract


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    output = args.output_dir.resolve(strict=True)
    fixtures = Path(__file__).resolve().parent
    contract = load_contract()
    # run_path works under python -I without adding the checkout to sys.path.
    builder = runpy.run_path(str(fixtures / "_requests.py"))["build_packets"]
    _, packets = builder(fixtures, contract)
    for variant, value in packets.items():
        descriptor, temporary = tempfile.mkstemp(prefix=".eval-", dir=output)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
                json.dump(value, stream, indent=2, ensure_ascii=True)
                stream.write("\n")
            os.replace(temporary, output / f"{variant}-requests.json")
        finally:
            Path(temporary).unlink(missing_ok=True)
    print("Prepared paired eval requests. Agent behavior has not been evaluated.")


if __name__ == "__main__":
    main()
