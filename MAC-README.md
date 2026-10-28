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
python -m pip install /absolute/wheels/autogenesis_agent_contract-1.0.0-py3-none-any.whl /absolute/wheels/autogenesis_appium_mcp-0.1.0-py3-none-any.whl
python -c "from importlib.resources import files; from pathlib import Path; Path('appium.json').write_bytes(files('autogenesis_appium_mcp').joinpath('conf/appium_conf.template.json').read_bytes())"
autogenesis-appium-mcp --platform mac --config /absolute/business/appium.json
```

The default transport is **stdio**. The default platform is iOS, so pass
`--platform mac` for Mac2. Initialize and discover tools/prompts/identity without
Appium or a live application; automation calls create sessions when requested.
stdout is reserved for MCP; diagnostics use stderr.

With uvx and local artifacts:

```bash
uvx --from /absolute/wheels/autogenesis_appium_mcp-0.1.0-py3-none-any.whl --with /absolute/wheels/autogenesis_agent_contract-1.0.0-py3-none-any.whl autogenesis-appium-mcp --platform mac --config /absolute/business/appium.json
```

Once both packages are published to the configured index:

```bash
uvx --from autogenesis-appium-mcp==0.1.0 autogenesis-appium-mcp --platform mac --config /absolute/business/appium.json
```

Agent Contract is pinned to **1.0.0**, manifest SHA-256
`302a8d779a3c30c26f8c5d801fcf06852f802eeaf18e677924a1d9a791b93412`.
A mismatched or corrupt contract prevents startup.

## Configure Mac2

Follow the [macOS Appium Setup Guide](appium-mcp-server/docs/macOS_Appium_Setup_Guide.md)
for Xcode/Appium setup. Grant Terminal and the MCP client's host application
Accessibility permission in System Settings → Privacy & Security. Grant Screen
Recording permission if needed for screenshots. Before executing automation:

```bash
appium driver install mac2
appium server --port 4723
```

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
file; `get_current_config` masks values recursively. Whole-string
`${VARIABLE}` references resolve environment variables; missing variables reject
the config. Keep secrets in the environment. Optional Azure visual verification
uses `AZURE_OPENAI_API_KEY` and `AZURE_OPENAI_ENDPOINT`.

Redaction retains at most 256 recent credential/password values and 64 KiB of
UTF-8 value bytes for later snapshots and generated previews. Least recently
used values are evicted; oversized values are not retained. Identified fields
and the current tool response remain protected, but an evicted value appearing
later in unrelated free text cannot be recognized. Free-text matches require
whole values or non-alphanumeric boundaries; controlled status values stay intact.
Recorded passwords are masked in replay previews and files. Replace masked
replay inputs with environment-variable references before running the replay.

## Configure an MCP client

For a command on PATH, `.vscode/mcp.json` can contain:

```json
{
  "servers": {
    "auto-genesis-mcp-mac": {
      "type": "stdio",
      "command": "autogenesis-appium-mcp",
      "args": ["--platform", "mac", "--config", "/absolute/business/appium.json"]
    }
  }
}
```

Cursor uses the same command/arguments under `mcpServers`. Use an absolute command
path for a virtual environment, or `uvx` with the artifact arguments above.
stdin closure or process termination stops watchers and releases driver resources.
Explicit `--transport sse` preserves the legacy local SSE option.

Canonical workflows are prompts `execute_scenario`, `generate_scenario_test`,
and `execute_natural_language_task`. Identity is available at
`autogenesis://agent-contract/identity`. Use the generation workflow for the
selected feature/scenario and its preview/confirmation steps. Default output is
business-local `behave_demo/features/steps/common_steps.py`; explicit feature and
step paths retain their existing behavior.

## Source development and existing Behave projects

From the AutoGenesis repository root, in an activated development environment:

```bash
python -m pip install /absolute/wheels/autogenesis_agent_contract-1.0.0-py3-none-any.whl -e ./appium-mcp-server
python appium-mcp-server/simple_server.py --platform mac --config /absolute/business/appium.json
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
