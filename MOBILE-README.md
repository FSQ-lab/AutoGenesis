# AutoGenesis Appium MCP — iOS and Android

The distribution is `autogenesis-appium-mcp`, its import package is
`autogenesis_appium_mcp`, and its command is `autogenesis-appium-mcp`.
It retains the existing iOS/Android Appium tools, BrowserStack connections,
visual verification, and BDD generation. Python 3.10 or later is required.

## Install in a business project

No AutoGenesis checkout is needed. Until packages are published, obtain both
built wheels from the Integration Lead. In an activated Python virtual environment:

```bash
python -m pip install /absolute/wheels/autogenesis_agent_contract-2.0.0-py3-none-any.whl /absolute/wheels/autogenesis_appium_mcp-0.4.0-py3-none-any.whl
python -c "from importlib.resources import files; from pathlib import Path; Path('appium.json').write_bytes(files('autogenesis_appium_mcp').joinpath('conf/appium_conf.template.json').read_bytes())"
autogenesis-appium-mcp --platform android --config /absolute/business/appium.json --project-root /absolute/business
```

Use `--platform ios` for iOS. The default platform is iOS and transport is
**stdio**. Initialization and tool/workflow discovery need no Appium server or
device; automation tools create sessions when requested. stdout belongs to the
MCP client; diagnostics use stderr.

With uv/uvx, launch directly from the same local artifacts:

```bash
uvx --from /absolute/wheels/autogenesis_appium_mcp-0.4.0-py3-none-any.whl --with /absolute/wheels/autogenesis_agent_contract-2.0.0-py3-none-any.whl autogenesis-appium-mcp --platform android --config /absolute/business/appium.json --project-root /absolute/business
```

After both distributions are published to the configured index:

```bash
uvx --from autogenesis-appium-mcp==0.4.0 autogenesis-appium-mcp --platform ios --config /absolute/business/appium.json --project-root /absolute/business
```

The runtime pins Agent Contract **2.0.0**, manifest SHA-256
`4367a2e388d0d5cb41a415b25b6a58e25025f1da6749bfdffe87a37c60a0c9d3`.
Mismatched or corrupt contract assets prevent startup.

Standard MCP Registry metadata is `appium-mcp-server/server.json`. From a source
checkout, render the equivalent shell-free generic descriptor with:

```bash
python tools/render_mcp_descriptor.py --server appium --platform android --config /absolute/business/appium.json --project-root /absolute/business
```

## Configuration and devices

Selection order is `--config`, then business `conf/appium_conf.json`, then the
bundled local-server template. No config is written into the installed package.
Business config files reload after edits or atomic replacement; invalid edits
retain the last valid snapshot. Changes apply to the next driver session.
`reload_config` requests a reload and `get_current_config` returns a masked view,
including nested values and URLs. The bundled template does not need a watcher.

For local devices, install Appium and its `uiautomator2` or `xcuitest` driver,
then configure `server_url`, device capabilities, and app or bundle identifier.
Local iOS automation needs macOS/Xcode; Android needs its SDK and a device or
emulator. Keep `APPIUM_DRIVER_CONFIGS` as the top-level configuration key.

BrowserStack connections use the Appium client directly; its SDK is not required.
Upload the APK/IPA through App Automate, set `appium:app` to its returned URL, and
use environment references for credentials:

```json
{
  "APPIUM_DRIVER_CONFIGS": {
    "android": {
      "platformName": "Android",
      "automationName": "UiAutomator2",
      "deviceName": "Google Pixel 8",
      "platformVersion": "14.0",
      "server_url": "https://hub.browserstack.com/wd/hub",
      "appium:app": "bs://your-uploaded-app",
      "bstack:options": {
        "userName": "${BROWSERSTACK_USERNAME}",
        "accessKey": "${BROWSERSTACK_ACCESS_KEY}"
      }
    }
  }
}
```

Set those variables in the server environment through the client or secret
manager. Whole-string `${VARIABLE}` values remain references until execution;
missing values fail the selected operation without rejecting discovery. Keep
credentials out of tracked configuration and URLs. Optional Azure visual
verification resolves its API key only when constructing the provider client.

Credential capabilities must use `${NAME}` references in JSON configuration.
Coding Agents may pass `{"$secret":"env:NAME"}` to secret-aware text tools.
Generated steps retain that reference and resolve it only during execution;
plaintext credentials and `[REDACTED]` placeholders are never persisted.


## MCP client setup

For an installed command on PATH, `.vscode/mcp.json` can use:

```json
{
  "servers": {
    "auto-genesis-mcp-mobile": {
      "type": "stdio",
      "command": "autogenesis-appium-mcp",
      "args": ["--platform", "android", "--config", "/absolute/business/appium.json", "--project-root", "/absolute/business"]
    }
  }
}
```

Cursor uses the same command/arguments under `mcpServers`. An absolute command
path in a virtual environment also works. A uvx client uses `command: "uvx"`
with the artifact arguments above. stdin closure or process termination stops
watchers and releases drivers. The installed and source entrypoints expose stdio only.

The server publishes fixed instructions, prompts `execute_scenario`,
`generate_scenario_test`, and `execute_natural_language_task`, and the read-only
resource `autogenesis://agent-contract/identity`. Use the generation workflow for
the selected scenario. Preview returns the complete payload, identity, and digest;
confirmation must echo the identity and digest with `approved=true`. The runtime
rejects stale base files, escaping paths and symlinks, then atomically replaces
the target. Default generated output is business-local
`features/steps/common_steps.py`; explicit paths must remain inside the project.

## Run from source

From the AutoGenesis repository root, in an activated development environment:
```bash
python -m pip install /absolute/wheels/autogenesis_agent_contract-2.0.0-py3-none-any.whl -e ./appium-mcp-server
python appium-mcp-server/simple_server.py --platform android --config /absolute/business/appium.json --project-root /absolute/business
```

The source script calls the same synchronous main. With no `--config`, an
existing source-side `appium-mcp-server/conf/appium_conf.json` retains legacy
precedence. Copy the template there if needed. Package acceptance uses built
wheels in a clean project, separate from this editable development setup.

Existing Behave projects still use their `features/environment.py` MCP adapter.
Select the matching `auto-genesis` server name when several are configured, then
run `python -m behave --name "Scenario Name"` in the business project. The
repository's `behave-demo` remains a separate example.

For startup failures, check the selected config path, required environment
references, and exact contract package. For automation failures, check Appium,
device capabilities, and the device/cloud connection.

Uninstall with `python -m pip uninstall autogenesis-appium-mcp autogenesis-agent-contract`
inside its virtual environment, or remove that environment and its MCP client
entry. Business configuration and generated tests remain in the business project.
