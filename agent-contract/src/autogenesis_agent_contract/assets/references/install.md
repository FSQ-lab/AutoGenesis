# Machine bootstrap and Coding Agent activation

Use only for installing, activating, repairing, or diagnosing AutoGenesis itself. Do not select a target platform, inspect devices or applications, install Appium dependencies, or create an automation session.

## Resolve the route

Establish the native host, absolute business project, Coding Agent (`omp`, `pi`, `codex`, or `copilot`), selected Python/isolation policy, safely disclosed package-source host and config-source class, and `user` or `project` Skill scope. Infer a unique answer from conversation and safe evidence. Ask once only when materially different clients or scopes remain; never ask the user to choose internal package or configuration mechanics.

Classify the request as `install` when packages or Skill are absent, `activate` when valid artifacts lack an active client MCP entry, `repair` when observed package/Skill/scope/configuration/identity drift prevents use, or `diagnose` when only read-only fault isolation is authorized. An explicit install, activate, or repair request authorizes its complete unchanged plan after disclosure. “Installed but unavailable” authorizes diagnosis, not configuration writes.

## Observe only bootstrap facts

Inspect the selected installed Python environment and first-party package versions, CLI entrypoint, canonical Skill in the selected discovery scope, conflicting user/project or legacy Skills, and the selected Agent's active MCP command/argv/cwd entry. Preserve every unrelated MCP entry byte-equivalently. Do not expand a solved launcher/configuration fault into target, SDK, Driver, device, application, or whole-environment discovery.

Before the CLI exists, follow the immutable Agent Install Prompt. Authenticate the exact reviewed Actions artifact or immutable GitHub Release identity before relying on its complete `SHA256SUMS`; checksums cover every final asset including the prompt and exclude only themselves, but never replace the external anchor. The prompt path always creates one explicitly approved, previously absent disposable virtual environment dedicated to the exact Candidate or public Release. It never uses or modifies an active, ambient, global, user-site, project, cached, or other pre-existing environment.

## Apply one canonical plan

Use the package manager only for the authenticated wheel set and `autogenesis install` as the sole Skill installer:

```text
autogenesis install --scope <user|project> --project-root <absolute-project> --json
```

Disclose packages and exact authenticated artifact identities; the new absolute disposable environment path; selected base Python; sanitized package-source host and config-source class; package policy; Skill scope/destination; MCP configuration destination and exact entry; every write/process; persistence; consequences; rollback; and verification once. Require the path to be absent and obtain explicit approval before creating it or making any other change. After creation, use only that environment's absolute Python and entrypoints for package, AutoGenesis, Runtime, CLI, and verification operations. Do not install by copying repository files or composing a second installer. Linux and WSL stop before mutation.

Package-source metadata may come only from managed policy, the user, or another trusted interface that guarantees host-only and config-source-class output without reading secret-bearing values. Never inspect, parse, print, log, serialize, echo, or derive metadata from full index URLs, URL userinfo, credentials, percent-encoded credentials, tokens, queries, fragments, authorization data, credential-bearing environment values, raw pip/uv configuration, errors, command output, or evidence payloads. Redaction after reading is not a safety boundary. Do not dump package-manager configuration or environment variables. If safe sanitized metadata is unavailable, report the source as `undisclosed` and stop before installation.

Treat the installer result as evidence only for layers it reports. Do not rerun an identical install for reassurance; reuse `unchanged`. On a stable error inspect only its failing layer instead of discovering flags through repeated mutations. Configure or repair the selected Agent through its native MCP mechanism with the disposable environment's absolute Runtime command and argv, never a shell-interpolated launch string. Retain all existing configuration.

On installation or verification failure, cancellation, denial, identity/digest mismatch, supersession, or rollback, stop dependent processes started from the prompt-created environment. Delete that environment and only the Candidate/public-install downloaded, extracted, staged, selected-scope Skill/MCP, and cache state created by the prompt. Never delete or repurpose a pre-existing path, restore a cached Skill/Runtime schema or write-capable generated-code inventory, or alter unrelated environments, files, configuration, or credentials. Reload the Agent and prove the exact removed or newly accepted inventory before use.

## Prove Machine Ready

Reload through the current Agent when available, then prove through that Agent: the canonical Skill resolves to the approved scope and exact bytes with no shadow/legacy copy; the Runtime completes MCP initialize; required prompts/tools/resources are discoverable; and `autogenesis://agent-contract/identity` matches the installed Contract requirement.

A package command, `--version`, destination file, standalone SDK client, or config write alone is not Machine Ready. If automatic reload is unavailable, stop at configured/reload-required with exactly that user action and preserve the original request in resume context. Never create an application session to prove installation.

Return Outcome, project/client/scope, observed and selected installation, drift classification, changes/approval, actual Agent discovery evidence, one Required action if any, and Resume context. Keep raw paths and diagnostics out of durable evidence.
