# Target readiness

Preserve the original request and classify its scope before checking prerequisites:

- `prepare`: establish applicable static prerequisites; finish as `Target Prepared` without a disposable business session.
- `validate`: establish a disposable real session or binding, observe target UI, and clean up task-owned resources.
- `execute` or `record`: establish `Live Ready`, then resume the preserved task immediately.
- `diagnose`: reproduce or inspect the smallest failing layer; do not rerun broad setup.
- `continue`: reuse a verified live context; do not repeat setup or provenance checks.

Follow `Resolve → Observe → Select → Evaluate → Reuse or Recommend → Approve → Apply → Recheck → Prove → Resume`. Inspect only facts that can affect the selected target. Keep moving while Agent-owned work remains.

Classify each dependency as `satisfied-constraints`, `warning-only`, `unverified`, `observed-requirement-violation`, or `proven-incompatible`. Tested versions are evidence, not an allowlist. Prefer a verified existing candidate and temporary task environment over installation or persistent configuration. A failed candidate does not prove that no compatible candidate exists.
A newer-than-tested version with no declared upper bound or known incompatibility
is `warning-only` until required doctor and live checks pass; reuse it without an
upgrade or downgrade.

Distinguish pure observation, ephemeral runtime effects, protected persistent changes, and human-only actions. Starting ADB, a simulator or emulator, an Appium server, an application, or a session is a runtime effect, not a pure read. Before protected changes, disclose one complete immutable plan with exact action, source/identity, destination/scope, persistence, reason, effects, risks, rollback, and verification. Ask once; plan drift requires fresh approval.

Use `Action Required` only for one concrete action that only the user can perform. Use `Blocked` for unsupported or unavailable capability. `Target Prepared` proves applicable prerequisites but not live automation. `Live Ready` requires the installed platform MCP, `prompts/list`, live schemas, matching `autogenesis://agent-contract/identity`, one real target session or Windows binding, correct application/window identity, and observed UI. Doctor, `/status`, driver inventory, device inventory, a session ID, or narration alone is insufficient.

Track Runtime, Appium server, ADB, emulator/simulator, WDA, session/binding, and application ownership separately. Stop or delete only task-owned resources. Report cleanup as confirmed, failed, unknown, preserved, or not applicable; never infer cleanup from another resource ending.

Return Outcome, Target, Observed environment, Selected environment, Dependency evidence, Warnings, Changes, Approval, Runtime evidence, Resource ownership, one Required action if any, and Resume context. Do not expose plaintext secrets, credential-bearing URLs, raw sensitive diagnostics, home/project/temp paths, or raw device identifiers in durable evidence.
