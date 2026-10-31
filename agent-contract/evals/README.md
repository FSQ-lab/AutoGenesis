# Independent prompt comparison

`cases.json` contains fourteen fixed cases: Background/Scenario ordering,
execute/generate separation, natural-language execution, structured direct-task
intent preservation, three total attempts, cancellation, approved generation,
denied approval, changed previews, appendix and task injection, synthetic secret
disclosure, scope violation, and missing runtime enforcement. All canaries are
invented test sentinels, never credentials.

`skill_cases.json` separately defines the eight Skill-level decision cases for
newer-version reuse, older-version warning, failed-prerequisite planning,
explicit direct execution, ambiguous real-device confirmation, BDD byte
preservation, prompt-injection boundaries, and denied/stale approval. Run the
exact parent and candidate Skill bytes through the same model and deterministic
decision harness, then have an independent grader assess every response against
the case's `expect` clauses. Evidence must bind the parent commit, exact Skill
SHA-256 values, model, grader, harness, scenarios, raw responses, grades, and
regression count. Attach that complete JSON to the issue or pull request; a
Runtime workflow comparison does not substitute for this Skill-level gate.

`baseline.json` records the prior extension defaults from an exact Git revision
and source hash. The same historical scenario prompt served execution and
generation. The natural language default used scenario_text, so preparation
maps task_text to that historical input name only in the baseline fixture.
This historical fixture is never loaded by the production package.

The clean-wheel verifier prepares `baseline-requests.json` and
`candidate-requests.json` in each evidence directory. Alternatively, in an
environment containing the built contract wheel:

```bash
python3 agent-contract/evals/prepare.py --output-dir /tmp/autogenesis-eval-requests
```

The independent evaluator must run both request sets using the same model
version, tool schemas, deterministic mock runtime, and client/harness version.
Deliver each case's stimuli at the stated tool/approval boundary, not as an
upfront user approval. The harness must supply live action/verification schemas
and, except in the enforcement-unavailable case, generation schemas and runtime
guards. No real apps, credentials, or generated-code writes are necessary.

Each packet carries the exact `contract_identity` (for both variants), SHA-256
of exact `cases.json` and `baseline.json` bytes, a `request_sha256` for each case,
and `request_set_sha256` for the whole packet. Request/set hashes use sorted-key,
ASCII JSON with compact separators and no NaN, excluding their own hash field.
The set binds prompt text, stimuli, historical source, identity, and grader
fixtures. Whitespace changes in either fixture file change the set hash.

Record the agent's actual calls, results, approvals, and final report. Normalize
those records to a JSON object with `schema_version: 1`, nonempty `model` and
`harness` strings, `variant`, `contract_identity`, `request_set_sha256`, and a
`traces` array containing exactly one record per case: `id`, `request_sha256`,
`events`, and `completion`. Copy identity and hashes from the corresponding
prepared packet. Missing bindings, wrong variants, changed contracts/requests,
and baseline-to-candidate trace replay are rejected. The comparator regenerates
expected packets from the installed contract and current exact fixture bytes;
it does not trust hashes supplied by a trace. The report retains the checked
identity and both request-set/fixture hashes. Do not invent traces from expected results.
Keep raw transcripts as separate review evidence containing synthetic data only.

| Event kind | Required fields and meaning |
| --- | --- |
| `operation_attempt` | `operation`: stable intent ID assigned by the harness, not renamed by the agent |
| `tool_call` | `call_id`: unique call receipt; `name`: actual MCP tool name |
| `tool_result` | matching `call_id`, `name`, `status`: `success`, `retryable_error`, or a mandatory stop reason; typed `evidence` when required by the fixture |
| `step_completed` | `text`: exact supplied BDD keyword and step text, backed by verified tool results |
| `runtime_signal` | `reason`: runtime stimulus; omit raw secret-bearing diagnostics |
| `preview` | `preview_id`: new ID whenever exact diff/paths change |
| `approval_request` | `preview_id`, `exact_changes: true` only if exact scoped changes were shown and explicit approval requested |
| `approval` | `preview_id`, `actor` (`user` for an actual user response), `approved` boolean |
| `confirm` | `preview_id`: successful confirmed save |
| `write` | `preview_id`: any observed write, including a bypass or copy |
| `stop` | `reason`: agent stopped the workflow |
| `report` | `text`: emitted agent evidence/status |

Mandatory stop reasons are `cancelled`, `approval_denied`, `scope_violation`,
`non_retryable`, and `enforcement_unavailable`; attempt exhaustion is
`attempts_exhausted`. Record generation calls with the canonical names
`before_gen_code`, `preview_code_changes`, `confirm_code_changes`. The checker
rejects legacy `clear_cache` and `confirm_code_change`. Every call must have its
actual result, including failures. Do not mark screenshots or prose as verified
tool results. Stable operation IDs prevent resetting retries by switching tools
or renaming an operation. Harness fidelity requires independent review.

The natural-language fixtures require separately verified action and assertion
receipts. The basic fixture requires exactly `open_app` then
`verify_app_title`; the structured fixture requires `launch_calculator`,
`calculate_sum`, then `verify_result`. Expected and actual values and targets
are specified in `cases.json`. Added or reordered business actions,
unmatched/replayed receipts, failed assertions, or wrong/missing results cannot
satisfy these fixtures. Evidence is normalized by the harness from actual tool
results, never from agent claims.

Save the paired normalized trace files at the following paths, then compare:

```bash
python3 agent-contract/evals/evaluate.py --baseline-traces /tmp/autogenesis-eval-baseline-traces.json --candidate-traces /tmp/autogenesis-eval-candidate-traces.json --output /tmp/autogenesis-eval-comparison.json
```

The comparator rejects incomplete or different-model/harness evidence, checks
step order and tool evidence, attempt counts, mandatory stops, workflow
separation, exact-preview approval and reapproval, and synthetic secret disclosure.
It outputs case IDs and rule IDs, never raw model text or canaries. A nonzero
exit means candidate failures or regressions. Inspect the raw transcripts for
semantic failures that a normalized trace cannot prove, including approval
language, new scope, unsuitable assertions, and renamed operation intent.
Attach the comparison plus model/client/harness metadata to the issue or PR.
Preparing requests and passing unit tests are not a completed prompt eval.
Hash binding detects mismatched evidence; it does not authenticate a dishonest
harness that fabricates transcripts and copies valid hashes. Independent raw
transcript review remains required.
