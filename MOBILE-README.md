# AutoGenesis Appium MCP — iOS and Android

The distribution is `autogenesis-appium-mcp`, its import package is
`autogenesis_appium_mcp`, and its command is `autogenesis-appium-mcp`.
It retains the existing iOS/Android Appium tools, BrowserStack connections,
visual verification, and BDD generation. Python 3.10 or later is required.

## Install in a business project

No AutoGenesis checkout is needed. Until packages are published, obtain both
built wheels from the Integration Lead. In an activated Python virtual environment:

```bash
python -m pip install /absolute/wheels/autogenesis_agent_contract-1.0.0-py3-none-any.whl /absolute/wheels/autogenesis_appium_mcp-0.1.0-py3-none-any.whl
python -c "from importlib.resources import files; from pathlib import Path; Path('appium.json').write_bytes(files('autogenesis_appium_mcp').joinpath('conf/appium_conf.template.json').read_bytes())"
autogenesis-appium-mcp --platform android --config /absolute/business/appium.json
```

Use `--platform ios` for iOS. The default platform is iOS and transport is
**stdio**. Initialization and tool/workflow discovery need no Appium server or
device; automation tools create sessions when requested. stdout belongs to the
MCP client; diagnostics use stderr.

With uv/uvx, launch directly from the same local artifacts:

```bash
uvx --from /absolute/wheels/autogenesis_appium_mcp-0.1.0-py3-none-any.whl --with /absolute/wheels/autogenesis_agent_contract-1.0.0-py3-none-any.whl autogenesis-appium-mcp --platform android --config /absolute/business/appium.json
```

After both distributions are published to the configured index:

```bash
uvx --from autogenesis-appium-mcp==0.1.0 autogenesis-appium-mcp --platform ios --config /absolute/business/appium.json
```

The runtime pins Agent Contract **1.0.0**, manifest SHA-256
`302a8d779a3c30c26f8c5d801fcf06852f802eeaf18e677924a1d9a791b93412`.
Mismatched or corrupt contract assets prevent startup.

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

Set those variables in the server's environment through the client or secret
manager. Only a whole string `${VARIABLE}` resolves; missing variables reject
that config. Keep credentials out of tracked configuration and URLs. Optional
Azure visual verification reads `AZURE_OPENAI_API_KEY` and `AZURE_OPENAI_ENDPOINT`.

Redaction retains at most 256 recent credential/password values and 64 KiB of
UTF-8 value bytes for later snapshots and generated previews. Least recently
used values are evicted; oversized values are not retained. Identified fields
and the current tool response remain protected, but an evicted value appearing
later in unrelated free text cannot be recognized. Free-text matches require
whole values or non-alphanumeric boundaries; controlled status values stay intact.
Recorded passwords are masked in replay previews and files. Replace masked
replay inputs with environment-variable references before running the replay.

## MCP client setup

For an installed command on PATH, `.vscode/mcp.json` can use:

```json
{
  "servers": {
    "auto-genesis-mcp-mobile": {
      "type": "stdio",
      "command": "autogenesis-appium-mcp",
      "args": ["--platform", "android", "--config", "/absolute/business/appium.json"]
    }
  }
}
```

Cursor uses the same command/arguments under `mcpServers`. An absolute command
path in a virtual environment also works. A uvx client uses `command: "uvx"`
with the artifact arguments above. stdin closure or process termination stops
watchers and releases drivers. Explicit `--transport sse` retains legacy local SSE.

The server publishes fixed instructions, prompts `execute_scenario`,
`generate_scenario_test`, and `execute_natural_language_task`, and the read-only
resource `autogenesis://agent-contract/identity`. Use the generation workflow for
the selected scenario and its preview/confirmation steps. Default generated output
is business-local `behave_demo/features/steps/common_steps.py`. Existing explicit
feature/step paths retain their behavior.

## Run from source

From the AutoGenesis repository root, in an activated development environment:

```bash
python -m pip install /absolute/wheels/autogenesis_agent_contract-1.0.0-py3-none-any.whl -e ./appium-mcp-server
python appium-mcp-server/simple_server.py --platform android --config /absolute/business/appium.json
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
