# AutoGenesis Windows MCP package

Issue #30 carries **autogenesis-windows-mcp** version 0.5.0 forward with the
Agent Contract 2.1.0 identity. It remains importable as
**autogenesis_windows_mcp** with command **autogenesis-windows-mcp**. Python
3.10+ and Windows are required; Linux CI checks metadata/imports only.

<!-- mcp-name: io.github.FSQ-lab/autogenesis-windows -->

## Install in a business project

Build artifacts must contain both the Windows Runtime 0.5.0 wheel and Agent
Contract 2.1.0 wheel. From any Windows business directory, without a
checkout of AutoGenesis:

```powershell
python -m venv .venv
.venv/Scripts/python -m pip install C:/artifacts/autogenesis_agent_contract-2.1.0-py3-none-any.whl C:/artifacts/autogenesis_windows_mcp-0.5.0-py3-none-any.whl
.venv/Scripts/autogenesis-windows-mcp --config ./apps.json --app notepad --project-root .
```

The installed command defaults to **stdio**. MCP clients must own stdin/stdout;
stdout contains JSON-RPC only. Diagnostics contain metadata on stderr; startup
does not create log files or write into the installed package. Close client
stdin or send SIGINT (Ctrl+C) to stop the server. Disconnecting does not invoke
the app_close automation tool or terminate the user's application.

With uv installed, isolated execution from local artifacts is also supported:

```powershell
uvx --with C:/artifacts/autogenesis_agent_contract-2.1.0-py3-none-any.whl --from C:/artifacts/autogenesis_windows_mcp-0.5.0-py3-none-any.whl autogenesis-windows-mcp --config ./apps.json --app notepad --project-root .
```

After these versions are published to the configured package index:

```powershell
uvx --from autogenesis-windows-mcp==0.5.0 autogenesis-windows-mcp --config ./apps.json --app notepad --project-root .
```

The runtime depends exactly on autogenesis-agent-contract==2.1.0 and requires
manifest SHA-256
ec097a569aa4d62da8211f3ad23fb00eccb95d9d9cee871e360af6ac05ca1dd6.
Missing, corrupt or incompatible contract assets fail startup.

Standard MCP Registry metadata is `pywinauto-mcp-server/server.json`. From a
source checkout, render the equivalent shell-free generic descriptor with:

```powershell
python tools/render_mcp_descriptor.py --server windows --config C:/business/apps.json --app notepad --project-root C:/business
```

## Application profiles

The schema is **PYWINAUTO_CONFIG.apps_config**, a nonempty object mapping
profile names to application configurations:

```json
{
  "PYWINAUTO_CONFIG": {
    "apps_config": {
      "notepad": {
        "app_name": "Notepad",
        "exe": "%WINDIR%/System32/notepad.exe",
        "window_title_re": ".*Notepad.*",
        "launch_args": [],
        "launch_timeout_seconds": 15
      },
      "business-app": {
        "app_name": "Business application",
        "exe": "$AUTOGENESIS_APP_EXE",
        "window_title_re": ".*Business Application.*",
        "launch_args": ["--token", "$AUTOGENESIS_APP_TOKEN"]
      }
    }
  }
}
```

The packaged Notepad template is used when --config is omitted. A public
example is also in conf/pywinauto_conf.example.json. Copy it to a private business
configuration and select a profile with --app. Without --app, the first profile
in JSON insertion order is selected. Unknown profile names fail clearly.

Each profile requires nonempty string exe and window_title_re fields.
window_title_re must compile as a regular expression. Optional app_name is a
string; launch_args is an array of strings and defaults to an empty array.
launch_timeout_seconds is an integer from 1 through 120 and defaults to 15.
Existing additional project/profile fields remain supported. All profiles are
schema-validated before startup; only the selected profile has environment
variables expanded. Unused profiles may reference unset variables.

Expansion supports $NAME, dollar-braced NAME, and Windows %NAME% recursively
through values in dictionaries and lists. Unset variables or empty required
values fail startup. Environment variables take precedence over a private .env
file in the current business directory. Keep credentials in environment
variables or that untracked file; configurations should contain references.
Profile values, launch arguments, entered text, keystrokes, tool results and
exception bodies are excluded from diagnostic logs. No MCP config readback tool
is exposed. Schema and argument errors do not echo supplied values.

Executable paths and launch arguments are quoted with Windows command-line
rules and passed to Windows `CreateProcess` without a shell. The retained
launcher process handle authenticates title-matched windows to the original
process incarnation or its transferred child, including after launcher exit.

Process creation, trusted top-level window discovery, connection, visibility,
enabled state and initial binding share one monotonic launch budget. The runtime
polls readiness at an internal 500 ms interval and uses cancellable asynchronous
waits; it does not add a probe or sleep after the configured deadline. Multiple
title-matched windows belonging to the same launch are rejected as ambiguous
rather than selecting one arbitrarily.

`app_launch` failures have a fixed, secret-safe response contract. Alongside
`status: "error"` and an empty `data` object, responses include `error_code`,
`stage`, `retryable`, and a fixed `error` description. Exception text, process
arguments, paths, titles, control content, and snapshot content are never copied
into these fields. Unknown failures use `INTERNAL_ERROR` and are not retryable.

| `error_code` | `stage` | `retryable` | Condition |
| --- | --- | --- | --- |
| `PROCESS_START_FAILED` | `process_start` | false | Process creation failed |
| `ELEVATION_REQUIRED` | `process_start` | false | Windows returned elevation-required error 740 |
| `WINDOW_NOT_FOUND` | `window_discovery` | true | No trusted matching window appeared before the deadline |
| `WINDOW_AMBIGUOUS` | `window_discovery` | false | Multiple trusted matching windows appeared |
| `WINDOW_NOT_VISIBLE` | `window_readiness` | true | The trusted window did not become visible |
| `WINDOW_NOT_ENABLED` | `window_readiness` | true | The trusted window did not become enabled |
| `WINDOW_BIND_FAILED` | `window_binding` | true | Connection or verified identity binding did not complete |
| `WINDOW_CONNECTION_LOST` | `window_connection` | true | The verified binding disappeared or changed identity |
| `SNAPSHOT_FAILED` | `snapshot` | true | Launch succeeded but initial snapshot extraction failed |
| `INTERNAL_ERROR` | `internal` | false | An unclassified internal failure occurred |

Callers may retry only when `retryable` is true, within the Agent Contract's
operation attempt limit. Increase `launch_timeout_seconds` for an application
that is known to need more than the 15-second default; do not retry nonretryable
configuration, elevation, or ambiguity failures unchanged.
After `app_launch` verifies that a matching top-level window exists, is visible
and is enabled, the runtime pins that window's native handle, owning process ID,
UI Automation runtime ID and original UIA element within the current session
generation. The title expression is discovery-only: later operations resolve
through the pinned UIA identity even if the title changes. A missing or
reincarnated element, identity mismatch, or invalid generation invalidates the
session and fails the operation; ordinary tools do not reconnect by title or
restart the application. A subsequent explicit `app_launch` may establish a new
session.

## Source execution

From the pywinauto-mcp-server directory, with the contract wheel in C:/artifacts:

```powershell
uv sync --find-links C:/artifacts
uv run --no-sync python simple_server.py --transport stdio --config C:/business/apps.json --app notepad
```

simple_server.py is a thin launcher for the same synchronous stdio main and
prefers a local conf/pywinauto_conf.json when present. When absent, it uses the
packaged template. The ignored local configuration is never copied into the
wheel. Remote HTTP/SSE transport is intentionally not exposed by this runtime.

## MCP client example

A client can launch the installed command with an argument array:

```json
{
  "mcpServers": {
    "autogenesis-windows": {
      "command": "C:/business/.venv/Scripts/autogenesis-windows-mcp.exe",
      "args": ["--config", "C:/business/apps.json", "--app", "notepad", "--project-root", "C:/business"]
    }
  }
}
```

The client initializes with the canonical Core Policy instructions. The merged
Agent Contract adapter publishes these official prompts:

- execute_scenario(scenario_text, feature_file_path?)
- generate_scenario_test(scenario_text, feature_file_path)
- execute_natural_language_task(task_text)

The read-only resource autogenesis://agent-contract/identity reports contract
identity and appendix metadata. The startup-only `--project-root` fixes the
business-project write scope; generated destinations cannot escape it. The
canonical adapter currently registers an empty project appendix.

The **22 existing Windows tool names and complete input schemas** are frozen in
tests/fixtures/legacy_tool_schemas.json, including their required fields,
defaults, array items and types:

- app_launch, app_close, app_screenshot, app_wait
- element_click, right_click, enter_text, send_keystrokes, select_item, open_folder
- mouse_drag_drop, mouse_hover, mouse_scroll
- verify_element_exists, verify_element_not_exist, verify_checkbox_state,
  verify_element_value, verify_elements_order, verify_visual_task
- before_gen_code, preview_code_changes, confirm_code_changes

For modern UIA `Document` controls, `enter_text` uses a writable ValuePattern
and confirms the resulting value before reporting success. `verify_element_value`
reads the wrapper value when available, then falls back to UIA ValuePattern and
TextPattern without changing the existing tool schema or containment assertion.

Generated replay continues to use Behave and the business project's
features.environment helpers. Default generation paths are relative to the
business working directory under features/steps, never inside site-packages.
Preview returns the complete payload, identity, and digest. Confirmation must
echo that identity and digest with `approved=true`; the runtime rejects stale
base files, escaping paths and symlinks, then atomically replaces the target.
Prefer explicit feature_file or step_file paths inside the project root.
Visual verification retains the Azure OpenAI and local provider paths;
AZURE_OPENAI_API_KEY and AZURE_OPENAI_ENDPOINT are read from the environment.
No provider implementation needs credential edits.

## Clean wheel verification

From the repository root, build both artifacts and verify them in a clean
Windows temporary business project:

```powershell
python -m pip install 'build>=1.2,<2'
python -m build --wheel --outdir C:/artifacts agent-contract
python -m build --wheel --outdir C:/artifacts pywinauto-mcp-server
python pywinauto-mcp-server/scripts/verify_wheel.py --wheel-dir C:/artifacts --mcp-version 1.23.0 --evidence-dir C:/evidence/windows-mcp-1.23
python pywinauto-mcp-server/scripts/verify_wheel.py --wheel-dir C:/artifacts --mcp-version 1.29.1 --evidence-dir C:/evidence/windows-mcp-1.29
```

Use a new artifacts directory with exactly one wheel per distribution. The
verifier creates a new venv and business directory, installs both local wheels,
copies only the acceptance harness and thin source launcher, and runs from that
business directory with isolated Python imports. It records wheel hashes,
runner image/version, installed module locations, install log, test report,
full protocol responses, the 22-tool snapshot, canonical prompts/identity,
EOF shutdown, SIGINT shutdown, and secret-canary results. Canary-bearing output
is rejected before protocol evidence is written. On Linux, only metadata,
package-data and import tests are selected; this is not Windows acceptance.
Pytest entry-point autoload is disabled, inherited PYTEST_PLUGINS/ADDOPTS are
cleared, and AnyIO is explicitly loaded. A synthetic installed plugin verifies
that third-party entry points cannot affect acceptance.

The SHA-pinned windows-package workflow covers Windows Server 2022 and Ubuntu
24.04, Python 3.10/3.12 and MCP SDK 1.23.0/1.29.1. Windows UI interaction still
requires an interactive desktop and a configured real application; hosted CI
proves installation and protocol behavior without launching user applications.
Independent code/security review and clean Windows acceptance remain required.

## Compatibility limits and rollback

The transport uses one private FastMCP server handle to supply cancellable
stdin and sanitized wire errors; both supported SDK versions have explicit
protocol coverage. Windows pipes use readiness polling and read only reported
available bytes, so SIGINT/EOF cancellation leaves no blocked reader worker.

Credential configuration must use `${NAME}`, `$NAME`, or `%NAME%` references;
plaintext credential fields are rejected. Coding Agents may pass
`{"$secret":"env:NAME"}` to secret-aware text tools. Recording, preview,
confirmation, and generated files retain that reference and resolve it only at
execution. Plaintext secure-control input becomes an unbound requirement, and
preview fails until the Coding Agent supplies an explicit SecretRef binding.
Generated code contains literals and references only—never plaintext credentials
or executable `[REDACTED]` placeholders.

Uninstall the runtime from the business venv to roll back:

```powershell
.venv/Scripts/python -m pip uninstall autogenesis-windows-mcp
```

Remove the client's server entry separately. Business configurations and
generated test files remain in the business project.
