# AutoGenesis Appium MCP — macOS

The distribution is `autogenesis-appium-mcp`, imported as
`autogenesis_appium_mcp`, with command `autogenesis-appium-mcp`. It retains
Mac2 automation and BDD generation. Python 3.10 or later is required. Actual
macOS automation needs Appium, its Mac2 driver, Xcode setup, and Accessibility
permissions for the application driving automation.

## Install from a business project

Obtain the built runtime and Agent Contract wheels from the Integration Lead.
No AutoGenesis checkout is needed. In an activated virtual environment:

```bash
python -m pip install /absolute/wheels/autogenesis_agent_contract-2.1.0-py3-none-any.whl /absolute/wheels/autogenesis_appium_mcp-0.5.0-py3-none-any.whl
python -c "from importlib.resources import files; from pathlib import Path; Path('appium.json').write_bytes(files('autogenesis_appium_mcp').joinpath('conf/appium_conf.template.json').read_bytes())"
autogenesis-appium-mcp --platform mac --config /absolute/business/appium.json --project-root /absolute/business
```

The default transport is **stdio**. The default platform is iOS, so pass
`--platform mac` for Mac2. Initialize and discover tools/prompts/identity without
Appium or a live application; automation calls create sessions when requested.
stdout is reserved for MCP; diagnostics use stderr.

With uvx and local artifacts:

```bash
uvx --from /absolute/wheels/autogenesis_appium_mcp-0.5.0-py3-none-any.whl --with /absolute/wheels/autogenesis_agent_contract-2.1.0-py3-none-any.whl autogenesis-appium-mcp --platform mac --config /absolute/business/appium.json --project-root /absolute/business
```

Once both packages are published to the configured index:

```bash
uvx --from autogenesis-appium-mcp==0.5.0 autogenesis-appium-mcp --platform mac --config /absolute/business/appium.json --project-root /absolute/business
```

Agent Contract is pinned to **2.1.0**, manifest SHA-256
`ec097a569aa4d62da8211f3ad23fb00eccb95d9d9cee871e360af6ac05ca1dd6`.
A mismatched or corrupt contract prevents startup.

Standard MCP Registry metadata is `appium-mcp-server/server.json`. From a source
checkout, render the equivalent shell-free generic descriptor with:

```bash
python tools/render_mcp_descriptor.py --server appium --platform mac --config /absolute/business/appium.json --project-root /absolute/business
```

## Configure Mac2

Invoke `autogenesis-setup` for local Mac2 preparation. It verifies the official
Appium Skills snapshot at commit `e907024c210fe024c956ed9c74146fc27b1dd013`
and uses `setup-mac2` as documentation and helper evidence. Setup automatically
runs relevant read-only checks and reuses a working environment; Appium, Driver,
Xcode, privacy, or filesystem changes are consolidated for explicit approval.
Doctor and owned-server smoke evidence are prerequisites; Ready additionally
requires MCP discovery and a real Mac2 target session. Grant Accessibility or
Screen Recording only when the selected target requires it and after reviewing
the exact request.

Set the Mac profile in the business config, for example:

```json
{
  "APPIUM_DRIVER_CONFIGS": {
    "mac": {
      "platformName": "Mac",
      "automationName": "Mac2",
      "bundleId": "com.example.yourapp",
      "server_url": "http://127.0.0.1:4723",
      "appium:fullReset": false,
      "appium:sessionTimeout": 6000,
      "appium:newCommandTimeout": 6000,
      "shouldUseSingletonTestManager": false,
      "waitForQuiescence": false
    }
  }
}
```

Selection order is `--config`, business `conf/appium_conf.json`, then the bundled
local-server template. Installed package files are never modified. Business config
files hot reload after edits or atomic replacement; invalid edits retain the last
valid snapshot. Settings apply to the next session. `reload_config` reloads the
file; `get_current_config` returns literals and SecretRefs without resolving them.
Whole-string `${VARIABLE}` references remain valid even when the variable is not
present at discovery time; the selected operation fails safely if resolution is
still unavailable at execution. Optional Azure visual verification reads its
credentials only when constructing the provider client.

Credential capabilities must use lossless references such as
`{"$secret":"env:BROWSERSTACK_ACCESS_KEY"}` in MCP tool arguments or
`${BROWSERSTACK_ACCESS_KEY}` in JSON configuration. Plaintext credential fields
are rejected. Generated steps retain the reference and resolve it only during
execution; they never persist plaintext or `[REDACTED]` placeholders.


## Configure an MCP client

For a command on PATH, `.vscode/mcp.json` can contain:

```json
{
  "servers": {
    "auto-genesis-mcp-mac": {
      "type": "stdio",
      "command": "autogenesis-appium-mcp",
      "args": ["--platform", "mac", "--config", "/absolute/business/appium.json", "--project-root", "/absolute/business"]
    }
  }
}
```

Cursor uses the same command/arguments under `mcpServers`. Use an absolute command
path for a virtual environment, or `uvx` with the artifact arguments above.
stdin closure or process termination stops watchers and releases driver resources.
The installed and source entrypoints expose stdio only.

Canonical workflows are prompts `execute_scenario`, `generate_scenario_test`,
and `execute_natural_language_task`. Identity is available at
`autogenesis://agent-contract/identity`. Use the generation workflow for the
selected feature/scenario. Preview returns the complete payload, identity, and
digest; confirmation must echo the identity and digest with `approved=true`.
The runtime rejects stale base files, escaping paths and symlinks, then atomically
replaces the target. Default output is business-local
`features/steps/common_steps.py`; explicit paths must remain inside the project.

## Source development and existing Behave projects

From the AutoGenesis repository root, in an activated development environment:
```bash
python -m pip install /absolute/wheels/autogenesis_agent_contract-2.1.0-py3-none-any.whl -e ./appium-mcp-server
python appium-mcp-server/simple_server.py --platform mac --config /absolute/business/appium.json --project-root /absolute/business
```

The source script calls the same synchronous main. With no `--config`, an existing
source-side `appium-mcp-server/conf/appium_conf.json` retains legacy precedence.
Copy the template there if needed. Acceptance uses built wheels in a clean
business project, separate from editable source development.

Existing Behave projects still use `features/environment.py` and their selected
`auto-genesis` MCP server name. Run `python -m behave --name "Scenario Name"`
from the business project. The repository's `behave-demo` remains an example.

For startup failures, check the explicit config path, environment references, and
exact contract package. For automation failures, check the Mac2 driver, bundle
identifier, application installation, and Accessibility permissions. Startup and
discovery alone do not require a running Appium server.

Uninstall with `python -m pip uninstall autogenesis-appium-mcp autogenesis-agent-contract`
inside the environment, or remove it and its MCP client entry. Business config
and generated tests remain intact.
