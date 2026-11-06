# Runtime execution

Enter only for a `Live Ready` target or a verified reusable live context. Direct requests use `execute_natural_language_task`. Exact BDD execution uses `execute_scenario`. Only explicit recording or generation uses `generate_scenario_test`.

For direct execution, preserve original intent and confirmed constraints in structured task text: target/application, starting state, ordered actions, expected observations/assertions, allowed recovery, stop conditions, required evidence, and side-effect limits. An explicit low-risk task needs no extra plan confirmation. For an ambiguous business goal, inspect safe context and propose one harmless concrete example, assertion, and side effects for at most one confirmation.

BDD Background and selected Scenario text, keywords, and source order are immutable. Added execution context cannot add, merge, remove, or authorize business steps. Execution mode never invokes generation or writes files. Recording writes only after the current exact preview identity/digest and enforced approval; denial, drift, cancellation, scope failure, or non-retryable failure stops.

Use `Observe → Act → Verify`. Establish only current facts needed for the next action and reuse them while valid. Prefer semantic/control evidence and direct state queries. Use bounded visual evidence only when the target is unexposed/custom-drawn, the assertion is visual, the user requests it, or structured evidence cannot resolve the question. Never emit full page trees, raw logs, encoded images, secrets, or unrelated environment data.

A failed or missing response does not prove the action failed, the Runtime died, or the session is reusable. Before retry, perform one discriminating observation appropriate to the failure. Do not repeat an identical operation in unchanged state, replay an irreversible action with unknown outcome, or exceed three total attempts. Stop immediately on cancellation, denied approval, scope violation, non-retryable failure, or exhausted attempts.
When the user limits an irreversible action to once, a lost response consumes
that attempt: reconcile state, but never issue the action again.

Preserve the requested final state. Restore only incidental task-owned reversible effects when safe and before closing the live context. Report the observed assertion result separately from readiness and report each owned resource's cleanup truthfully.
