# AutoGenesis CLI

Machine-level installer for AutoGenesis-owned runtimes and canonical Agent Skills.
Python 3.10+ and native macOS or Windows are required.

Install this distribution through the Python environment and index selected by the user, then run:

```bash
autogenesis install
```

The command verifies the host Runtime bundle installed as package dependencies and copies `autogenesis-setup` and `autogenesis-run` from the integrity-checked Agent Contract to `~/.agents/skills`. It does not install Appium Server, Drivers, SDKs, register MCP, create project configuration, or execute an application.

Use `--skills-dir /absolute/path` to select another user-approved destination. Existing non-canonical Skill bytes are preserved and cause a safe failure rather than being overwritten.
