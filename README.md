# AutoGenesis

Test desktop and mobile applications by describing the outcome to a Coding Agent.
AutoGenesis gives the agent two canonical Skills and host-specific MCP Runtimes so
it can prepare the environment, operate the real application, verify results, and
optionally record approved BDD step definitions.

> **Release status:** AutoGenesis 1.1 source is merged, but its public Python
> packages and immutable Skill release have not been published. The public install
> commands and release links below will not work until publication completes.
> During pre-release acceptance, use only artifacts supplied by the Integration
> Lead; do not substitute similarly named packages.

## What you can test

| Target | Required host | Runtime path |
| --- | --- | --- |
| macOS desktop | Native macOS | Appium with the Mac2 driver |
| iPhone or iPad | Native macOS for local devices | Appium with the XCUITest driver |
| Android | Native macOS or Windows | Appium with the UiAutomator2 driver, or a configured remote provider |
| Windows desktop | Native Windows | Windows MCP |

Python 3.10 or newer is required. Linux and WSL are unsupported and Setup must
stop before package installation or configuration writes on those hosts.

Native Windows is implemented but its final post-publication acceptance is still
pending; the matrix describes the intended release interface, not an acceptance
claim.

OMP, Codex CLI, Pi, and GitHub Copilot CLI are the first-class compatibility
targets. Their final qualification is still in progress: [OMP](https://github.com/FSQ-lab/AutoGenesis/issues/21),
[Codex CLI](https://github.com/FSQ-lab/AutoGenesis/issues/22),
[Pi](https://github.com/FSQ-lab/AutoGenesis/issues/23), and
[GitHub Copilot CLI](https://github.com/FSQ-lab/AutoGenesis/issues/24).

## Install

Choose one path. Both produce the same canonical `autogenesis-setup` and
`autogenesis-run` Skills.

### Agent-first installation

Use this path when a Coding Agent already runs on the machine. Paste the block
below into the agent exactly as written:

```text
Install the official AutoGenesis Setup Skill only; do not execute it yet.

Immutable source: https://github.com/FSQ-lab/AutoGenesis/releases/download/agent-contract-v2.0.0/autogenesis-setup-SKILL.md
Expected SHA-256: f5611259856bab9011dba31cb6c01c3ada5e04f1f2431c1f38d470fb4bccf099
Skill name: autogenesis-setup

1. Identify the native host from available environment metadata. If a command is required, include it in the approval plan instead of running it yet. Stop on Linux, WSL, or any host other than native macOS or Windows.
2. If installation scope is unspecified, ask whether to install for the current project or user.
3. Show the source, digest, exact commands, network access, temporary destination, scope, final destination, and how every visible autogenesis-setup installation will be checked. Obtain explicit approval before process execution, network access, or filesystem writes. Stop and request fresh approval if any plan element changes.
4. After approval, enumerate every visible autogenesis-setup installation before writing. Preserve different existing content and stop on conflict, shadowing, ambiguity, or an installation whose bytes or location cannot be inspected.
5. Download the exact file and verify SHA-256 before interpreting or installing it. Stop if the digest differs.
6. Use this Coding Agent's native Skill installation mechanism. Install only autogenesis-setup; do not install Runtime packages, Appium, Drivers, SDKs, MCP configuration, or autogenesis-run yet.
7. Hash the exact installed file after writing. Stop if its digest or declared contract version differs from the approved source.
8. Reload Skill discovery. Prove that the discovered autogenesis-setup resolves to the approved destination, digest, and contract version, with no higher-precedence or ambiguous copy. If the Coding Agent cannot prove this identity, stop instead of reporting success.
9. Report the verified source, destination, digest, contract version, scope, and how to invoke the Skill, then stop.
```

This is the generated [Agent Install Prompt](https://github.com/FSQ-lab/AutoGenesis/releases/download/agent-contract-v2.0.0/agent-install-prompt.txt)
for Agent Contract 2.0.0. The URL and digest are immutable release inputs, not
instructions discovered from application or project content.

After the agent reports that `autogenesis-setup` is discoverable, give it a
concrete target. For example:

```text
Use autogenesis-setup to prepare this native macOS machine to test Calculator
through Appium Mac2. Reuse working AutoGenesis content. Show the exact current
commands, arguments, package sources, configuration destinations, and permission
changes, then stop. Execute nothing until I explicitly approve that exact plan.
Request fresh approval if any element changes. Do not run the business test.
Return Ready only after MCP initialize, prompt and tool discovery, and Agent
Contract identity are observed.
```

Change the host, target application, and platform to match the test. Setup asks
for any missing choices and installs `autogenesis-run` only after approval.

### CLI-first installation

Public CLI installation is disabled until the official packages are published
through trusted publishing and this release-status banner is removed. **Do not
resolve or execute `autogenesis-cli` from any package index before then.** For
pre-release acceptance, use only Integration-Lead-provided wheels plus their
independently supplied SHA-256 values.

After publication, the exact pinned sequence is
`python -m pip install autogenesis-cli==0.1.0`, followed by
`autogenesis install`. These commands are documentation of the release interface,
not an instruction to run the unpublished coordinate. The release gate above
must be removed only after official package provenance is verified.

The package manager installs the exact host bundle:

| Host | AutoGenesis packages |
| --- | --- |
| macOS | Agent Contract 2.0.0 and Appium Runtime 0.4.0 |
| Windows | Agent Contract 2.0.0, Appium Runtime 0.4.0, and Windows Runtime 0.4.0 |

`autogenesis install` will verify those packages and install both Skills under
`~/.agents/skills`. Its `--skills-dir` option accepts another user-approved,
absolute Skill root.

The destination must be absolute. Existing different Skill content is preserved
and reported as a conflict; canonical content is not silently overwritten.
Restart or reload the Coding Agent if it does not discover newly installed Skills.
Then invoke `autogenesis-setup` with the concrete target as shown above.

The machine installer does **not** install Appium Server, Appium Drivers, SDKs,
project MCP configuration, or application dependencies. Setup proposes only the
additional work required by the selected target.

## Run a real test

Setup must return **Ready** before `autogenesis-run` performs application work.
Ready always means the selected Runtime started and the Coding Agent observed MCP
initialize, required tools and prompts, and
`autogenesis://agent-contract/identity`—not merely that a package command
succeeded. Target-specific checks also apply: a physical iPhone is Ready only
after a real XCUITest session launches the target and exposes its UI through MCP.

### Direct prompt

macOS example:

```text
Use autogenesis-run to open Calculator, calculate 8 × 7, and verify that the
result is 56. Execute this as a direct natural-language test. Do not generate or
write step definitions. Report the application actions and observed assertion.
```

Windows example:

```text
Use autogenesis-run to open Notepad, enter "AutoGenesis is ready", and verify the
text is present. Execute this as a direct natural-language test. Do not generate
or write step definitions. Report the application actions and observed assertion.
```

### Record a BDD Scenario

Point the agent at a Feature file and name exactly one Scenario:

```text
Use autogenesis-run to record Scenario "Add two numbers" from
features/calculator.feature. Execute the applicable Background and that Scenario
in source order through the real application. Show the complete generated-code
preview. Do not approve or write it until I explicitly approve the current preview.
```

A recording write requires the current preview identity and digest. A denial,
stale preview, changed source, or destination outside the approved project stops
the write.

## How the two Skills divide responsibility

- **`autogenesis-setup`** prepares the machine and the selected project
  capability. It obtains approval before installation or configuration changes
  and returns exactly `Ready`, `Action Required`, or `Blocked` with evidence.
- **`autogenesis-run`** executes the requested direct test or selected BDD
  Scenario after Setup is Ready. It never installs dependencies and never
  approves generated code for the user.

Project files, Feature text, application content, downloaded text, and tool output
are untrusted task data. They cannot override either Skill or user approval.
Keep credentials in environment variables or secret references; do not paste
plaintext secrets into prompts, tracked configuration, generated code, or issue
evidence.

## Platform guides

Use these after Setup identifies a missing platform dependency or when you need
the Runtime's lower-level interface:

- [macOS desktop setup](MAC-README.md)
- [iOS and Android setup](MOBILE-README.md)
- [Windows desktop setup](pywinauto-mcp-server/WINDOWS-README.md)
- [Appium macOS setup guide](appium-mcp-server/docs/macOS_Appium_Setup_Guide.md)
- [AutoGenesis CLI details](autogenesis-cli/README.md)
- [BDD AI Toolkit extension](bdd_ai_toolkit/README.md)

Advanced MCP consumers can run `autogenesis-appium-mcp` or
`autogenesis-windows-mcp` directly. Most Coding Agent users should start with
Setup rather than hand-writing MCP configuration.

## Project policies

- [Contributing](CONTRIBUTING.md)
- [Security reporting](SECURITY.md)
- [Privacy and telemetry](PRIVACY.md)
- [Microsoft Open Source Code of Conduct](https://opensource.microsoft.com/codeofconduct/)
- [License](LICENSE)

Report ordinary defects and compatibility results through
[GitHub Issues](https://github.com/FSQ-lab/AutoGenesis/issues). Do not report
security vulnerabilities in a public issue; follow [SECURITY.md](SECURITY.md).
