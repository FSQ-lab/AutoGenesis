# AutoGenesis CLI

`autogenesis-cli==0.1.0` is the installation entry for AutoGenesis-owned Python
Runtimes and canonical Agent Skills. Python 3.10+ and native macOS or Windows
are required; Linux and WSL are unsupported.

Install it through the Python environment and package index selected by the user:

```bash
python -m pip install autogenesis-cli==0.1.0
autogenesis install
```

`autogenesis --version` prints the installed CLI version without checking the
host, packages, Contract, or Skill destination.

The package manager, not `autogenesis install`, installs the host dependencies:

| Host | Exact AutoGenesis dependencies |
| --- | --- |
| macOS | `autogenesis-agent-contract==2.0.0`, `autogenesis-appium-mcp==0.4.0` |
| Windows | `autogenesis-agent-contract==2.0.0`, `autogenesis-appium-mcp==0.4.0`, `autogenesis-windows-mcp==0.4.0` |

`autogenesis install` verifies that the required package versions and Agent
Contract are available, then copies `autogenesis-setup` and `autogenesis-run`
to `~/.agents/skills`. It fails rather than invoking pip or uv when a package is
missing or incompatible. Re-running it with canonical files already present is
idempotent and reports `unchanged`.

Use `--skills-dir /absolute/path` to select another user-approved destination.
Existing non-canonical Skill bytes are preserved and cause a conflict instead
of being overwritten.

The command does not install Appium Server, Appium Drivers, platform SDKs,
register MCP, create project or business configuration, or execute an
application. Invoke `autogenesis-setup` afterward for target-specific readiness.
