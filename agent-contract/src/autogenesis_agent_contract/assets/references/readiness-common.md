# Target readiness and repair contract

Preserve the request and classify its scope before checking prerequisites: `prepare` establishes applicable static prerequisites without a disposable session; `validate` creates one real disposable session or binding and cleans task-owned resources; `execute` or `record` establishes Live Ready then resumes; `diagnose` inspects the smallest failing layer; `continue` reuses verified live context.

Follow `Resolve → Observe → Select → Evaluate → Reuse or Recommend → Approve → Apply → Recheck → Prove → Resume`. Keep moving while Agent-owned work remains.

## One result shape

Return these fields for every route:

```json
{
  "requestScope": "prepare|validate|execute|record|diagnose|continue",
  "outcome": "Target Prepared|Live Ready|Task Passed|Task Failed|Action Required|Blocked",
  "target": {"platform": "android|ios|macos|windows", "profile": "platform profile", "identity": "sanitized observed identity"},
  "layers": [{"id": "stable layer id", "applicability": "required|optional|not-applicable", "state": "ready|missing|incompatible|blocked|unknown|not-checked", "evidence": ["bounded observed fact"], "blockers": []}],
  "environment": {"configured": {}, "detected": [], "selected": {}, "rejected": [], "persistence": "temporary|existing|approved-persistent"},
  "changes": [{"action": "exact effect", "source": "identity", "destination": "scope", "persistence": "ephemeral|persistent", "reason": "observed gap", "consequences": [], "rollback": "exact rollback", "verification": "affected check"}],
  "approval": {"status": "not-required|pending|granted|declined", "planIdentity": "stable identity or null"},
  "runtimeEvidence": {"mcpIdentity": "matched|missing|mismatched|not-requested", "liveControl": "passed|failed|unknown|not-requested"},
  "ownership": {"runtime": "owned|external|not-applicable", "server": "owned|external|not-applicable", "sessionOrBinding": "owned|external|not-applicable", "application": "owned|user-owned|external|not-applicable", "cleanup": "confirmed|failed|unknown|preserved|not-applicable"},
  "requiredAction": null,
  "resumeContext": {"preservedRequest": true, "next": "next Agent-owned operation or wait for requiredAction"}
}
```

Evidence contains observations, never conclusions. A required layer that is missing, incompatible, blocked, unknown, or unchecked prevents readiness. Platform references may add stable layer ids but may not invent states or another result shape.

## Select one coherent environment

For each applicable dependency retain its configured value, every considered detected candidate and origin, selected candidate, and rejected candidates with bounded reasons. Execute capability probes; a PATH miss, variable, directory, import, version list, or one failed candidate is not final evidence. Prefer a verified existing candidate and temporary task environment over installation or persistence.

Classify dependencies as `satisfied-constraints`, `warning-only`, `unverified`, `observed-requirement-violation`, or `proven-incompatible`. Tested versions are evidence, not an allowlist. Reuse a compatible newer candidate with at most a warning after required checks pass. Use the selected environment consistently for authenticated official checks, server, MCP Runtime, and session.

## Authorize and repair once

Distinguish observation, ephemeral runtime effects, protected persistent changes, and human-only actions. Starting ADB, a simulator/emulator, Appium server, application, or session is a runtime effect. Before protected changes populate the complete immutable `changes` set and ask once. Carry a granted unchanged `planIdentity` across first-party and official workflow handoffs; ask again only when an effect field changes.

Exhaust applicable existing candidates before recommending installation. Recommend one smallest effect set, apply after approval, then rerun only affected checks. `Action Required` contains exactly one identity, physical confirmation, privacy, trust, signing, credential, license, or other native action only the user can perform. Commands, paths, environment selection, diagnosis, and subsequent resume remain Agent-owned.

## Prove and resume

`Target Prepared` requires every applicable static layer ready and creates no disposable business session. `Live Ready` requires the selected MCP, live prompt/tool/resource schemas, matching `autogenesis://agent-contract/identity`, one real target session or Windows binding, correct application/window, and observed UI. Doctor, `/status`, inventory, local session id, or narration is insufficient.

Track Runtime, Appium server, ADB, emulator/simulator, WDA, session/binding, and application ownership separately. Stop or delete only task-owned resources. After Live Ready resume the preserved explicit task without another request or plan confirmation. Report its result separately from readiness and never expose secrets, credential-bearing URLs, raw diagnostics, local paths, or raw device identifiers.
