# AutoGenesis CLI

`autogenesis-cli==0.2.0` is the installation entry for AutoGenesis-owned Python
Runtimes and canonical Agent Skills. Python 3.10+ and native macOS or Windows
are required; Linux and WSL are unsupported.

Authenticate the immutable Release manifest and `autogenesis-release.lock`
before any AutoGenesis package executes. Use the selected index only under that
strict hash lock, then install offline from the verified wheelhouse:

```bash
python -m pip download --require-hashes --requirement autogenesis-release.lock --dest autogenesis-wheelhouse
python -m pip install --force-reinstall --no-deps --no-index --find-links autogenesis-wheelhouse --require-hashes --requirement autogenesis-release.lock
autogenesis install --scope user --project-root <absolute-business-project>
```

The repository README gives the immutable Release URLs. Never install the CLI
directly by version from an index.

`autogenesis --version` prints the installed CLI version without checking the
host, packages, Contract, or Skill destination.

The package manager, not `autogenesis install`, installs the host dependencies:

| Host | Exact AutoGenesis dependencies |
| --- | --- |
| macOS | `autogenesis-agent-contract==2.1.0`, `autogenesis-appium-mcp==0.5.0` |
| Windows | `autogenesis-agent-contract==2.1.0`, `autogenesis-appium-mcp==0.5.0`, `autogenesis-windows-mcp==0.5.0` |

`autogenesis install --scope user --project-root <absolute-business-project>`
verifies the authenticated package bundle, rejects other canonical or legacy
discovery copies, and atomically installs one `autogenesis` Skill. Use
`--scope project` for `<project>/.agents/skills`. An identical rerun reports
`unchanged`.

`autogenesis reference <id> --json` loads one Contract-authenticated internal
install, platform-readiness, or execution reference with the exact Contract
identity. Unknown and path-like IDs fail closed. The canonical Skill loads only
the references required by the current request and target.
`autogenesis appium-skills --json` verifies the internal supported Appium workflow
snapshot. `autogenesis appium-workflow <id> --json` loads one authenticated
workflow selected by the LLM with its Context/tool inventory and provenance.
`autogenesis appium-asset <workflow-id> <relative-path>` returns held verified
bytes only when the asset belongs to that exact selected workflow. The Coding
Agent follows official terminal diagnostics, while real automation runs through
the canonical installed platform MCP.

The selected scope and project root determine the only accepted discovery path.
Existing non-canonical bytes or a Skill in another discovery scope are preserved
and cause a conflict instead of being overwritten.

The command does not install Appium Server, Drivers, SDKs, register MCP, create
business configuration, or execute an application. Invoke `autogenesis` for
target preparation, diagnosis, direct execution, or BDD work.
