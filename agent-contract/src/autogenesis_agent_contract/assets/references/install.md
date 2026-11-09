# Machine bootstrap and Coding Agent activation

Use only for installing, activating, repairing, or diagnosing AutoGenesis itself. Do not select a target platform, inspect devices or applications, install Appium dependencies, or create an automation session.

## Resolve the route

Establish the native host, absolute business project, Coding Agent (`omp`, `pi`, `codex`, or `copilot`), selected Python/package-index/isolation policy, and `user` or `project` Skill scope. Infer a unique answer from conversation and safe evidence. Ask once only when materially different clients or scopes remain; never ask the user to choose internal package or configuration mechanics.

Classify the request as `install` when packages or Skill are absent, `activate` when valid artifacts lack an active client MCP entry, `repair` when observed package/Skill/scope/configuration/identity drift prevents use, or `diagnose` when only read-only fault isolation is authorized. An explicit install, activate, or repair request authorizes its complete unchanged plan after disclosure. “Installed but unavailable” authorizes diagnosis, not configuration writes.

## Observe only bootstrap facts

Inspect the selected Python and first-party package versions, CLI entrypoint, canonical Skill in the selected discovery scope, conflicting user/project or legacy Skills, and the selected Agent's active MCP command/argv/cwd entry. Preserve every unrelated MCP entry byte-equivalently. Do not expand a solved launcher/configuration fault into target, SDK, Driver, device, application, or whole-environment discovery.

Before the CLI exists, follow the immutable Agent Install Prompt: authenticate the Release manifest and complete hash lock, install exact first-party wheels through the selected index without fallback, then use the installed CLI. Stable installation uses immutable Release identities; Candidate acceptance uses exact local or immutable wheel identities and never substitutes same-version index bytes.

## Apply one canonical plan

Use the package manager only for the authenticated wheel set and `autogenesis install` as the sole Skill installer:

```text
autogenesis install --scope <user|project> --project-root <absolute-project> --json
```

Disclose packages/source identities, Python environment, package policy, Skill scope/destination, MCP configuration destination and exact entry, persistence, consequences, rollback, and verification once. Do not install by copying repository files or composing a second installer. Linux and WSL stop before mutation.

Treat the installer result as evidence only for layers it reports. Do not rerun an identical install for reassurance; reuse `unchanged`. On a stable error inspect only its failing layer instead of discovering flags through repeated mutations. Configure or repair the selected Agent through its native MCP mechanism with absolute Runtime command and argv, never a shell-interpolated launch string. Retain all existing configuration.

## Prove Machine Ready

Reload through the current Agent when available, then prove through that Agent: the canonical Skill resolves to the approved scope and exact bytes with no shadow/legacy copy; the Runtime completes MCP initialize; required prompts/tools/resources are discoverable; and `autogenesis://agent-contract/identity` matches the installed Contract requirement.

A package command, `--version`, destination file, standalone SDK client, or config write alone is not Machine Ready. If automatic reload is unavailable, stop at configured/reload-required with exactly that user action and preserve the original request in resume context. Never create an application session to prove installation.

Return Outcome, project/client/scope, observed and selected installation, drift classification, changes/approval, actual Agent discovery evidence, one Required action if any, and Resume context. Keep raw paths and diagnostics out of durable evidence.
