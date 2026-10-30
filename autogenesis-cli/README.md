# AutoGenesis CLI

`autogenesis-cli==0.2.0` is the installation entry for AutoGenesis-owned Python
Runtimes and canonical Agent Skills. Python 3.10+ and native macOS or Windows
are required; Linux and WSL are unsupported.

Install it through the Python environment and package index selected by the user:

```bash
python -m pip install autogenesis-cli==0.2.0
autogenesis install
```

`autogenesis --version` prints the installed CLI version without checking the
host, packages, Contract, or Skill destination.

The package manager, not `autogenesis install`, installs the host dependencies:

| Host | Exact AutoGenesis dependencies |
| --- | --- |
| macOS | `autogenesis-agent-contract==2.1.0`, `autogenesis-appium-mcp==0.5.0` |
| Windows | `autogenesis-agent-contract==2.1.0`, `autogenesis-appium-mcp==0.5.0`, `autogenesis-windows-mcp==0.5.0` |

`autogenesis install` verifies that the required package versions and Agent
Contract are available, then copies `autogenesis-setup` and `autogenesis-run`
to `~/.agents/skills`. It fails rather than invoking pip or uv when a package is
missing or incompatible. Re-running it with canonical files already present is
idempotent and reports `unchanged`.

`autogenesis appium-skills --json` verifies the bundled official Appium Skills
snapshot and returns its source, commit, license, supported Node majors, and
read-only asset digest inventory. `autogenesis appium-asset <relative-path>`
writes one verified asset to stdout for preview and use.
For approved setup helpers only, preview the absolute Node path, exact version,
lowercase SHA-256, helper/arguments, and each required non-secret environment
value/hash. Run `autogenesis appium-tool --help` and invoke it with those exact
values (`--allow-env NAME=SHA256` binds inherited values). The CLI rejects
scripts/wrappers and verifies native Node through a retained handle and exact
SHA-256. Windows executes a private copy of those held bytes. POSIX revalidates
the retained file identity and executes its trusted original path so native
loader-relative dependencies remain available. Both paths verify the reported
Node version with an empty process environment and start the held helper through
a private bootstrap that adds only approved environment values.
On POSIX, every path component must be owned by root or the current user,
non-symlink, and not world-writable. A group-writable component is accepted only
when its group is one of the current process's effective or supplementary
groups, which covers a standard local Homebrew installation. Root, the current
user, and those groups are therefore inside the local execution trust boundary.
The approved SHA-256 identifies the Node executable bytes; native dynamic
dependencies remain governed by that local OS/package-manager trust boundary.

Use `--skills-dir /absolute/path` to select another user-approved destination.
Existing non-canonical Skill bytes are preserved and cause a conflict instead
of being overwritten.

The command does not install Appium Server, Appium Drivers, platform SDKs,
register MCP, create project or business configuration, or execute an
application. Invoke `autogenesis-setup` afterward for target-specific readiness.
