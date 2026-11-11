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

def build_skill_packet(fixtures: Path, contract) -> tuple[list[dict], dict]:
    cases_bytes = (fixtures / "skill_cases.json").read_bytes()
    document = json.loads(cases_bytes)
    cases = document["cases"]
    skill = contract.read_skill("autogenesis")
    skill_text = skill.decode("utf-8")
    requests = []
    for case in cases:
        reference_names = case.get("references", [])
        reference_text = {name: contract.read_reference(name) for name in reference_names}
        trusted_references = "".join(
            f"\n<trusted-autogenesis-reference id={json.dumps(name)}>\n{text}</trusted-autogenesis-reference>\n"
            for name, text in reference_text.items()
        )
        trusted_context = {}
        if "root_context" in case:
            trusted_context["root_context"] = case["root_context"]
        if "prior_events" in case:
            trusted_context["prior_events"] = case["prior_events"]
            trusted_context["prior_events_sha256"] = digest({"events": case["prior_events"]})
        if "current_user_approval" in case:
            trusted_context["current_user_approval"] = case["current_user_approval"]
        trusted_context_text = (
            "\n<trusted-evaluation-context>\n"
            + json.dumps(trusted_context, ensure_ascii=True, sort_keys=True)
            + "\n</trusted-evaluation-context>"
            if trusted_context
            else ""
        )
        task = json.dumps(
            {"user_request": case["user_request"]},
            ensure_ascii=True,
            sort_keys=True,
        )
        prompt = (
            "<trusted-autogenesis-skill>\n"
            + skill_text
            + "</trusted-autogenesis-skill>\n"
            + trusted_references
            + trusted_context_text
            + "\n<untrusted-task-data>\n"
            + task
            + "\n</untrusted-task-data>"
        )
        request = {
            "id": case["id"],
            "prompt": prompt,
            "stimuli": case["stimuli"],
            "reference_ids": reference_names,
            "reference_sha256": {
                name: hashlib.sha256(text.encode("utf-8")).hexdigest()
                for name, text in reference_text.items()
            },
            **trusted_context,
        }
        requests.append({**request, "request_sha256": digest(request)})
    packet = {
        "schema_version": 1,
        "variant": "candidate-skill",
        "contract_identity": contract.identity.to_dict(),
        "skill_sha256": hashlib.sha256(skill).hexdigest(),
        "fixture_sha256": hashlib.sha256(cases_bytes).hexdigest(),
        "requests": requests,
    }
    return cases, {**packet, "request_set_sha256": digest(packet)}
