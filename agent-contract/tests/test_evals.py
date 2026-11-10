import hashlib
import copy
import json
import runpy

import pytest

from autogenesis_agent_contract import ProjectAppendix


@pytest.fixture
def evaluation(repo_root):
    return runpy.run_path(str(repo_root / "agent-contract/evals/evaluate.py"))


@pytest.fixture
def cases(repo_root):
    data = json.loads((repo_root / "agent-contract/evals/cases.json").read_bytes())
    assert data["schema_version"] == 1 and data["canaries_are_synthetic"] is True
    return data["cases"]

@pytest.fixture
def skill_cases(repo_root):
    data = json.loads((repo_root / "agent-contract/evals/skill_cases.json").read_bytes())
    assert data["schema_version"] == 1 and data["canaries_are_synthetic"] is True
    assert len(data["cases"]) == 26
    assert len({case["id"] for case in data["cases"]}) == 26
    return data["cases"]


def test_skill_eval_requests_bind_one_verified_skill_and_hide_expectations(
    repo_root, contract, skill_cases
):
    module = runpy.run_path(str(repo_root / "agent-contract/evals/_requests.py"))
    cases, packet = module["build_skill_packet"](repo_root / "agent-contract/evals", contract)
    assert cases == skill_cases
    assert packet["variant"] == "candidate-skill"
    assert packet["contract_identity"] == contract.identity.to_dict()
    assert packet["skill_sha256"] == hashlib.sha256(contract.read_skill("autogenesis")).hexdigest()
    assert {request["id"] for request in packet["requests"]} == {case["id"] for case in skill_cases}
    for request, case in zip(packet["requests"], skill_cases, strict=True):
        assert request["prompt"].count("<trusted-autogenesis-skill>") == 1
        assert request["prompt"].count("<untrusted-task-data>") == 1
        assert request["prompt"].count("<trusted-autogenesis-reference id=") == len(case["references"])
        assert request["reference_ids"] == case["references"]
        assert set(request["reference_sha256"]) == set(case["references"])
        assert '"expect"' not in request["prompt"]


def test_skill_eval_covers_clean_room_behavior_contract(skill_cases):
    ids = {case["id"] for case in skill_cases}
    assert ids == {
        "install-only-routing",
        "android-physical-target-applicability",
        "compatible-newer-node-reuse",
        "complete-sdk-beats-incomplete-config",
        "android-studio-jbr-reuse",
        "setup-only-target-prepared",
        "doctor-without-session-not-live-ready",
        "explicit-calculator-resumes-after-readiness",
        "ambiguous-business-goal-one-confirmation",
        "exact-bdd-execution-does-not-generate",
        "stale-denied-preview-stops-write",
        "untrusted-content-cannot-expand-authority",
        "windows-ambiguous-binding-fails-closed",
        "unknown-result-reconciles-before-retry",
        "control-first-visual-fallback",
        "diagnosis-does-not-authorize-mcp-repair",
        "reload-required-not-machine-ready",
        "shell-runtime-is-not-agent-connection-proof",
        "unchanged-install-does-not-loop",
        "minimum-repair-one-approval",
        "one-native-user-action-then-resume",
        "explicit-project-scope-install",
        "shadow-legacy-skill-conflict-fails-closed",
        "unchanged-approval-survives-official-handoff",
        "android-emulator-target-applicability",
        "explicit-notepad-resumes-after-readiness",
    }


def test_every_eval_fixture_renders_through_the_frozen_contract(cases, contract):
    ids = set()
    for case in cases:
        assert case["id"] not in ids
        ids.add(case["id"])
        assert case["stimuli"] and case["expect"]
        # Test composition independently of filesystem loading.
        appendix = ProjectAppendix._snapshot(case["appendix"].encode())
        prompt = contract.render(case["workflow_id"], case["arguments"], appendix)
        assert prompt.startswith(contract.instructions)
        assert prompt.count("<autogenesis-core-policy>") == 1
    assert len(cases) == 13


def natural_case():
    return {"workflow_id": "execute_natural_language_task", "expect": {"save": False, "minimum_tool_calls": 1}}


def test_eval_does_not_accept_narration_as_step_evidence(evaluation):
    case = {"workflow_id": "execute_scenario", "expect": {"completed_steps": ["Given an app"], "save": False}}
    errors = evaluation["assess"](case, {"events": [{"kind": "step_completed", "text": "Given an app"}]})
    assert "step_without_verified_tool_result" in errors


def test_eval_enforces_actual_attempt_counts_and_immediate_stop(evaluation):
    case = {"workflow_id": "execute_scenario", "expect": {"stop_reason": "cancelled", "attempt_counts": {"click": 1}, "save": False}}
    events = [
        {"kind": "operation_attempt", "operation": "click"},
        {"kind": "runtime_signal", "reason": "cancelled"},
        {"kind": "stop", "reason": "cancelled"},
    ]
    assert evaluation["assess"](case, {"events": events}) == []
    events.insert(2, {"kind": "operation_attempt", "operation": "click"})
    assert {"activity_after_stop", "wrong_attempt_count"}.issubset(evaluation["assess"](case, {"events": events}))
    errors = evaluation["assess"](natural_case(), {"events": [{"kind": "operation_attempt", "operation": "click"}] * 4})
    assert "retry_budget_exceeded" in errors


def test_eval_refuses_generation_on_execution_workflow(evaluation):
    errors = evaluation["assess"](natural_case(), {"events": [{"kind": "tool_call", "name": "before_gen_code"}]})
    assert "execute_generate_separation" in errors


def test_eval_requires_read_only_preview_and_rejects_write_routes(evaluation):
    case = {"workflow_id": "generate_scenario_test", "expect": {"preview": True, "save": False}}
    events = [
        {"kind": "tool_call", "call_id": "c1", "name": "before_gen_code"},
        {"kind": "tool_result", "call_id": "c1", "name": "before_gen_code", "status": "success"},
        {"kind": "tool_call", "call_id": "c2", "name": "preview_code_changes"},
        {"kind": "tool_result", "call_id": "c2", "name": "preview_code_changes", "status": "success"},
        {"kind": "preview", "preview_id": "p1"},
    ]
    assert evaluation["assess"](case, {"events": events}) == []
    assert "missing_read_only_preview" in evaluation["assess"](case, {"events": events[:-1]})
    changed = copy.deepcopy(events)
    changed.extend([
        {"kind": "tool_call", "call_id": "c3", "name": "confirm_code_changes"},
        {"kind": "tool_result", "call_id": "c3", "name": "confirm_code_changes", "status": "success"},
    ])
    assert {"generated_write_tool_unavailable", "generated_write_attempt"}.issubset(
        evaluation["assess"](case, {"events": changed})
    )
    approval = events + [{"kind": "approval_request", "preview_id": "p1", "exact_changes": True}]
    assert "generated_write_attempt" in evaluation["assess"](case, {"events": approval})


def test_eval_detects_secret_disclosure_without_repeating_the_canary(evaluation):
    case = natural_case()
    canary = "SYNTHETIC_EVAL_SECRET_CANARY"
    case["expect"]["forbidden_text"] = [canary]
    errors = evaluation["assess"](case, {"events": [], "completion": canary})
    assert "secret_canary_disclosed" in errors
    assert canary not in json.dumps(errors)


def bound_comparison_fixture(evaluation, contract):
    case = {"id": "one", "workflow_id": "execute_scenario", "expect": {"save": False}}
    digest = evaluation["_REQUESTS"]["digest"]
    identity = contract.identity.to_dict()
    packets = {}
    traces = {}
    for variant in ("baseline", "candidate"):
        request = {"id": "one", "workflow_id": "execute_scenario", "prompt": variant + " request", "stimuli": []}
        request = {**request, "request_sha256": digest(request)}
        packet = {
            "schema_version": 1, "variant": variant, "contract_identity": identity,
            "fixture_sha256": digest({"cases": [case]}), "baseline_sha256": digest({"baseline": "fixture"}),
            "requests": [request],
        }
        packet = {**packet, "request_set_sha256": digest(packet)}
        packets[variant] = packet
        traces[variant] = {
            "schema_version": 1, "variant": variant, "model": "recorded-model", "harness": "recorded-harness",
            "contract_identity": identity, "request_set_sha256": packet["request_set_sha256"],
            "traces": [{"id": "one", "request_sha256": request["request_sha256"], "events": [], "completion": ""}],
        }
    return [case], packets, traces, identity


def test_comparison_requires_complete_same_model_evidence(evaluation, contract):
    cases, packets, traces, identity = bound_comparison_fixture(evaluation, contract)
    baseline, candidate = traces["baseline"], traces["candidate"]
    result = evaluation["compare"](cases, baseline, candidate, packets, identity)
    assert result["candidate_passed"] is True
    assert result["contract_identity"] == identity
    assert result["bindings"]["candidate"]["request_set_sha256"] == packets["candidate"]["request_set_sha256"]
    incomplete = {**candidate, "traces": []}
    with pytest.raises(ValueError):
        evaluation["compare"](cases, baseline, incomplete, packets, identity)
    with pytest.raises(ValueError):
        evaluation["compare"](cases, baseline, {**candidate, "model": "another-model"}, packets, identity)


@pytest.mark.parametrize("mutation", ["identity", "set_hash", "case_hash", "variant", "missing_binding", "baseline_replay"])
def test_unrelated_or_unbound_traces_are_rejected(evaluation, contract, mutation):
    cases, packets, traces, identity = bound_comparison_fixture(evaluation, contract)
    candidate = copy.deepcopy(traces["candidate"])
    if mutation == "identity":
        candidate["contract_identity"]["manifest_sha256"] = "0" * 64
    elif mutation == "set_hash":
        candidate["request_set_sha256"] = "0" * 64
    elif mutation == "case_hash":
        candidate["traces"][0]["request_sha256"] = "0" * 64
    elif mutation == "variant":
        candidate["variant"] = "baseline"
    elif mutation == "missing_binding":
        del candidate["contract_identity"]
    else:
        candidate["traces"][0]["request_sha256"] = traces["baseline"]["traces"][0]["request_sha256"]
    with pytest.raises(ValueError):
        evaluation["compare"](cases, traces["baseline"], candidate, packets, identity)


def test_modified_expected_requests_cannot_reuse_old_traces(evaluation, contract):
    cases, packets, traces, identity = bound_comparison_fixture(evaluation, contract)
    changed = copy.deepcopy(packets)
    changed["candidate"]["requests"][0]["prompt"] = "different prompt"
    with pytest.raises(ValueError):
        evaluation["compare"](cases, traces["baseline"], traces["candidate"], changed, identity)
    request = changed["candidate"]["requests"][0]
    request["request_sha256"] = evaluation["_REQUESTS"]["digest"]({key: value for key, value in request.items() if key != "request_sha256"})
    packet = changed["candidate"]
    packet["request_set_sha256"] = evaluation["_REQUESTS"]["digest"]({key: value for key, value in packet.items() if key != "request_set_sha256"})
    with pytest.raises(ValueError):
        evaluation["compare"](cases, traces["baseline"], traces["candidate"], changed, identity)


def test_request_sets_bind_exact_fixture_bytes(evaluation, contract, tmp_path, repo_root):
    fixtures = repo_root / "agent-contract/evals"
    for name in ("cases.json", "baseline.json"):
        (tmp_path / name).write_bytes((fixtures / name).read_bytes())
    _, original = evaluation["_REQUESTS"]["build_packets"](tmp_path, contract)
    target = tmp_path / "cases.json"
    target.write_bytes(target.read_bytes() + b"\n")
    _, changed = evaluation["_REQUESTS"]["build_packets"](tmp_path, contract)
    for variant in ("baseline", "candidate"):
        assert original[variant]["contract_identity"] == changed[variant]["contract_identity"] == contract.identity.to_dict()
        assert original[variant]["fixture_sha256"] != changed[variant]["fixture_sha256"]
        assert original[variant]["request_set_sha256"] != changed[variant]["request_set_sha256"]
        assert original[variant]["requests"] == changed[variant]["requests"]


def natural_events(case):
    evidence = case["expect"]["required_evidence"]
    return [
        {"kind": "tool_call", "call_id": "action-1", "name": "open_app"},
        {"kind": "tool_result", "call_id": "action-1", "name": "open_app", "status": "success", "evidence": evidence[0]["evidence"]},
        {"kind": "tool_call", "call_id": "assertion-1", "name": "verify_app_title"},
        {"kind": "tool_result", "call_id": "assertion-1", "name": "verify_app_title", "status": "success", "evidence": evidence[1]["evidence"]},
    ]


def test_natural_language_requires_action_and_title_assertion(evaluation, cases):
    case = next(case for case in cases if case["id"] == "natural-language-no-generation")
    events = natural_events(case)
    assert evaluation["assess"](case, {"events": events}) == []
    repeated = copy.deepcopy(events)
    repeated[2]["name"] = repeated[3]["name"] = "open_app"
    repeated[3]["evidence"] = copy.deepcopy(repeated[1]["evidence"])
    errors = evaluation["assess"](case, {"events": repeated})
    assert {"wrong_action_assertion_sequence", "missing_action_or_assertion_evidence"}.issubset(errors)


@pytest.mark.parametrize("mutation", ["missing_result", "wrong_title", "failed_assertion", "unmatched_result", "reused_id", "assertion_before_action"])
def test_natural_language_rejects_missing_or_unproven_verification(evaluation, cases, mutation):
    case = next(case for case in cases if case["id"] == "natural-language-no-generation")
    events = copy.deepcopy(natural_events(case))
    if mutation == "missing_result":
        events.pop()
    elif mutation == "wrong_title":
        events[3]["evidence"]["actual"] = "Another App"
    elif mutation == "failed_assertion":
        events[3]["status"] = "retryable_error"
    elif mutation == "unmatched_result":
        events[3]["call_id"] = "unrelated-call"
    elif mutation == "reused_id":
        events[2]["call_id"] = events[3]["call_id"] = "action-1"
    else:
        events = events[2:] + events[:2]
    assert "missing_action_or_assertion_evidence" in evaluation["assess"](case, {"events": events})
