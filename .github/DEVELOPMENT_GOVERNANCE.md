# AutoGenesis Development Governance

GitHub Issues and the **AutoGenesis Agent Integration** GitHub Project are the single source of truth for requirements, progress, review state, acceptance, and evidence.

## Roles

- **Human Product Owner:** owns product outcomes, priority, scope changes, irreversible decisions, final acceptance, and release approval.
- **Integration Lead:** decomposes accepted requirements, defines cross-issue contracts, assigns file ownership, manages dependencies, and integrates accepted changes.
- **Scout:** performs read-only investigation when impact is unknown.
- **Implementer:** changes one Ready issue in one isolated worktree and cannot approve its own work.
- **Reviewer:** reviews the issue, diff, and evidence from a fresh context. One independent reviewer is sufficient for ordinary changes.
- **Security Reviewer:** provides security coverage for secrets, configuration writes, process execution, downloads, filesystem scope, approvals, and prompt-injection surfaces. A qualified independent reviewer may cover correctness and security in one review; use a separate specialist only when the risk requires it.
- **Acceptor:** performs black-box verification from a clean environment when the issue or release gate requires installation/compatibility acceptance, clean-environment acceptance, or release acceptance. The acceptor cannot reuse the implementer's local state.

The author and reviewer must be separate sessions or people. When an acceptor is required, it must also be independent; reviewer and security reviewer may be the same qualified session.

## Workflow

`Inbox → Refining → Ready → In Progress → In Review → [In Acceptance when required] → Done`

Use `Blocked` for externally blocked work and `Cancelled` for intentionally abandoned work. Blocked work is not in progress.

## Definition of Ready

An issue is Ready only when:

- the problem and user outcome are unambiguous;
- scope and non-goals are explicit;
- observable Given/When/Then acceptance scenarios exist;
- public interface decisions are resolved or explicitly out of scope;
- dependencies and file ownership are known;
- verification environments are available;
- security-sensitive surfaces are identified; and
- an implementer does not need to invent product decisions.

If a requirement gap appears during implementation, stop and move the issue back to Refining.

## Work in Progress

- At most two implementation issues may be active concurrently during the agent-integration work.
- At most one public interface change may be active.
- A file has one implementation owner at a time.
- Shared schemas, manifests, Agent Contract sources, and package versions are serialized through the Integration Lead.
- Review does not count as implementation WIP. Acceptance does not count as implementation WIP when required.

## Quality gates

1. **Ready:** requirement and acceptance contract approved.
2. **Implementation:** targeted tests, build/type checks, affected documentation, and evidence complete.
3. **Review:** one independent reviewer resolves all blocking correctness, compatibility, security, and maintainability findings; explicit security coverage is included when applicable.
4. **Acceptance when required:** an independent acceptor executes the applicable scenarios from a clean environment for installation/compatibility, clean-environment, or release gates. Ordinary changes skip this separate gate after review and required verification pass.
5. **Release:** the Human Product Owner approves the verified user experience and remaining risks.

## Definition of Done

An issue is Done only when:

- every acceptance scenario passes;
- verification used a clean environment where applicable;
- required platform and client checks pass;
- all required CI checks pass;
- blocking review findings are resolved;
- security coverage passed or is explicitly not applicable;
- prompt changes include an eval comparison;
- no plaintext secret appears in logs, configuration, generated code, or evidence;
- rollback or uninstall behavior is documented and tested when applicable; and
- evidence is linked from the issue or pull request.

Compilation alone is never acceptance evidence.

## Agent-team execution

- Create one isolated worktree per implementation issue.
- Give each agent a complete issue, fixed scope, file ownership, and observable acceptance criteria.
- Parallelize only work with frozen interfaces and non-overlapping files.
- Reviewers receive the issue, diff, and verification evidence—not the implementer's full reasoning transcript. Combine correctness and security review when one qualified reviewer can cover both.
- When acceptance is required, acceptors install and exercise built artifacts rather than editable source trees.
- Agents may investigate, implement, review, and accept; humans retain product decisions and final approval. Use the minimum independent roles required by the issue's risk and acceptance gate.

## Progress reporting

Progress is measured by accepted capabilities, not code volume, commits, agent count, or self-reported percentages. Report:

- accepted capabilities;
- work in acceptance, review, and implementation;
- blockers and their owners;
- failed or reopened acceptance;
- client/platform compatibility pass rate;
- prompt-eval regressions; and
- flaky quality gates.

## Branches

- `feature/agent-integration-v2` is the integration branch for post-2.0 capabilities.
- Each Ready capability uses a dedicated branch and worktree.
- Capability pull requests target the integration branch.
- Only reviewed and accepted changes enter the integration branch.
- Epic-level black-box acceptance is required before the integration branch targets `main`.
- Direct pushes to protected branches are prohibited.
