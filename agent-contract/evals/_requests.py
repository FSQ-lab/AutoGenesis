"""Deterministic request packets; hashes bind prompts, stimuli, and grader fixtures."""

import hashlib
import json
import tempfile
from pathlib import Path

from autogenesis_agent_contract import load_project_appendix


def digest(value: dict) -> str:
    raw = json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":"), allow_nan=False).encode("ascii")
    return hashlib.sha256(raw).hexdigest()


def build_packets(fixtures: Path, contract) -> tuple[list[dict], dict[str, dict]]:
    cases_bytes = (fixtures / "cases.json").read_bytes()
    baseline_bytes = (fixtures / "baseline.json").read_bytes()
    cases = json.loads(cases_bytes)["cases"]
    baseline = json.loads(baseline_bytes)
    requests = {"baseline": [], "candidate": []}
    marker = "$" + "{"
    for case in cases:
        with tempfile.TemporaryDirectory(prefix="autogenesis-eval-project-") as temporary:
            project = Path(temporary)
            (project / ".autogenesis").mkdir()
            (project / ".autogenesis/instructions.md").write_bytes(case["appendix"].encode("utf-8"))
            rendered = contract.render(case["workflow_id"], case["arguments"], load_project_appendix(project))
        historical = baseline["workflows"][case["workflow_id"]]
        if case["workflow_id"] == "execute_natural_language_task":
            historical = historical.replace(marker + "scenario_text}", case["arguments"]["task_text"])
        for key, value in case["arguments"].items():
            historical = historical.replace(marker + key + "}", value)
        historical = historical.replace(marker + "feature_file_path}", "")
        historical += "\n\nProject instructions:\n" + case["appendix"]
        for variant, prompt in (("baseline", historical), ("candidate", rendered)):
            request = {
                "id": case["id"], "workflow_id": case["workflow_id"],
                "prompt": prompt, "stimuli": case["stimuli"],
            }
            requests[variant].append({**request, "request_sha256": digest(request)})
    packets = {}
    for variant, items in requests.items():
        packet = {
            "schema_version": 1,
            "variant": variant,
            "contract_identity": contract.identity.to_dict(),
            "fixture_sha256": hashlib.sha256(cases_bytes).hexdigest(),
            "baseline_sha256": hashlib.sha256(baseline_bytes).hexdigest(),
            "source": contract.identity.to_dict() if variant == "candidate" else baseline["source"],
            "requests": items,
        }
        packets[variant] = {**packet, "request_set_sha256": digest(packet)}
    return cases, packets
