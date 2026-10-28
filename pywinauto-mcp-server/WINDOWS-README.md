# AutoGenesis Windows MCP package

Issue #5 packages the existing Windows runtime as **autogenesis-windows-mcp**
(version 0.1.0), importable as **autogenesis_windows_mcp**, with the console
command **autogenesis-windows-mcp**. Python 3.10+ and Windows are required for
serving automation tools. Linux CI checks package metadata/imports only.

## Install in a business project

Build artifacts must contain both the Windows runtime wheel and the merged
Agent Contract 1.0.0 wheel. From any Windows business directory, without a
checkout of AutoGenesis:

```powershell
python -m venv .venv
.venv/Scripts/python -m pip install C:/artifacts/autogenesis_agent_contract-1.0.0-py3-none-any.whl C:/artifacts/autogenesis_windows_mcp-0.1.0-py3-none-any.whl
.venv/Scripts/autogenesis-windows-mcp --config ./apps.json --app notepad
```

The installed command defaults to **stdio**. MCP clients must own stdin/stdout;
stdout contains JSON-RPC only. Diagnostics contain metadata on stderr; startup
does not create log files or write into the installed package. Close client
stdin or send SIGINT (Ctrl+C) to stop the server. Disconnecting does not invoke
the app_close automation tool or terminate the user's application.

With uv installed, isolated execution from local artifacts is also supported:

```powershell
uvx --with C:/artifacts/autogenesis_agent_contract-1.0.0-py3-none-any.whl --from C:/artifacts/autogenesis_windows_mcp-0.1.0-py3-none-any.whl autogenesis-windows-mcp --config ./apps.json --app notepad
```

After these versions are published to the configured package index:

```powershell
uvx --from autogenesis-windows-mcp==0.1.0 autogenesis-windows-mcp --config ./apps.json --app notepad
```

The runtime depends exactly on autogenesis-agent-contract==1.0.0 and requires
manifest SHA-256
302a8d779a3c30c26f8c5d801fcf06852f802eeaf18e677924a1d9a791b93412.
Missing, corrupt or incompatible contract assets fail startup.

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
        "launch_args": []
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
rules and passed to pywinauto's CreateProcess path without a shell.

## Source execution

From the pywinauto-mcp-server directory, with the contract wheel in C:/artifacts:

```powershell
uv sync --find-links C:/artifacts
uv run --no-sync python simple_server.py --transport stdio --config C:/business/apps.json --app notepad
```

simple_server.py is a thin launcher for the same synchronous main. It retains
the existing source default of SSE and prefers a local conf/pywinauto_conf.json
when present. When absent, it uses the packaged template. The ignored local
configuration is never copied into the wheel. Explicit --transport stdio and
--transport sse work from either entrypoint. SSE remains available at
http://localhost:8000/sse:

```powershell
uv run --no-sync python simple_server.py --transport sse --config C:/business/apps.json
```

## MCP client example

A client can launch the installed command with an argument array:

```json
{
  "mcpServers": {
    "autogenesis-windows": {
      "command": "C:/business/.venv/Scripts/autogenesis-windows-mcp.exe",
      "args": ["--config", "C:/business/apps.json", "--app", "notepad"]
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
identity and appendix metadata. This packaging issue supplies no project
appendix configuration interface; the canonical adapter is registered with an
empty appendix. Project-root/bootstrap integration belongs to its owning issue.

The **22 existing Windows tool names and complete input schemas** are frozen in
tests/fixtures/legacy_tool_schemas.json, including their required fields,
defaults, array items and types:

- app_launch, app_close, app_screenshot, app_wait
- element_click, right_click, enter_text, send_keystrokes, select_item, open_folder
- mouse_drag_drop, mouse_hover, mouse_scroll
- verify_element_exists, verify_element_not_exist, verify_checkbox_state,
  verify_element_value, verify_elements_order, verify_visual_task
- before_gen_code, preview_code_changes, confirm_code_changes

Generated replay continues to use Behave and the business project's
features.environment helpers. Default generation paths are relative to the
business working directory under behave_demo/features/steps, never inside
site-packages. Prefer explicit feature_file or step_file for your project.
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
stdin and sanitized wire errors; both SDK versions have explicit protocol
coverage. Input schemas and transport flags remain unchanged. Logs are now
stderr metadata only; MCP_LOG_FILE and AGENT_INDEX no longer create log files.
Windows pipe readiness and console keyboard readiness are polled asynchronously,
so SIGINT does not leave a worker blocked on open stdin. EOF also cancels pending
tool work. The Windows acceptance suite exercises both idle and pending-tool
SIGINT while the client's stdin pipe remains open.

Known credentials and password-control inputs are redacted from previews and
generated code with [REDACTED] placeholders. Those values require reviewed
replacement before replay. Ordinary non-sensitive recorded text retains its
replay value. Full preview/approval binding, scoped atomic generation writes and
secret-reference replay are owned by issue #8; this packaging work preserves
the current generation interfaces.

Uninstall the runtime from the business venv to roll back:

```powershell
.venv/Scripts/python -m pip uninstall autogenesis-windows-mcp
```

Remove the client's server entry separately. Business configurations and
generated test files remain in the business project.
