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
`fbc589c142c20d15eca44afb264b6debb2c60e9e54e9e77b345ddcce4e8be67e`.
A mismatched or corrupt contract prevents startup.

Standard MCP Registry metadata is `appium-mcp-server/server.json`. From a source
checkout, render the equivalent shell-free generic descriptor with:

```bash
python tools/render_mcp_descriptor.py --server appium --platform mac --config /absolute/business/appium.json --project-root /absolute/business
```

## Configure Mac2

Invoke `autogenesis` for local Mac2 preparation or execution. It loads the pinned
internal official `setup-mac2` workflow, then the Coding Agent performs its
environment and doctor steps through the normal terminal. Doctor/server-smoke
completion is diagnostic evidence; Ready also requires matching MCP identity, a
real Mac2 session, and observed UI. Grant Accessibility or Screen Recording only
after reviewing the exact request.

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
selected feature/scenario. `before_gen_code` records successful operations and
returns only an opaque generation ID. `preview_code_changes` returns the complete
proposed payload, project-relative destination, identity, and digest without
writing it. Recording stops after this read-only preview: generated-file writes
are unavailable, and the stdio Runtime exposes no confirmation, commit, save, or
alternate copy route.

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

Rollback a Candidate by uninstalling `autogenesis-appium-mcp`,
`autogenesis-agent-contract`, and `autogenesis-cli` from its environment, then
remove that environment, the selected-scope `autogenesis` Skill, its MCP client
entry, downloaded/extracted Candidate channel, and the Agent's cached Skill/tool
schemas. Never restore a cached write-capable generation inventory; reload the
Agent and prove the removed or newly accepted inventory. Business configuration
and pre-existing generated tests remain intact.
