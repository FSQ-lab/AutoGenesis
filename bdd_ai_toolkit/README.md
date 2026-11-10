# BDD AI Toolkit

[![Version](https://img.shields.io/badge/version-1.2.43-blue.svg)](https://marketplace.visualstudio.com/)
[![VS Code](https://img.shields.io/badge/VS%20Code-1.95.0+-007ACC.svg)](https://code.visualstudio.com/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

AI-powered VS Code extension for BDD test automation. Preview proposed step-definition code through the authenticated AutoGenesis Skill, and run tests whose step definitions already exist. Recording preview never writes generated files.

## ✨ Features

- **AI-Powered Recording Preview** - Execute exact Gherkin steps and inspect proposed automation code without writing it
- **One-Click Existing-Test Replay** - Run scenarios whose step definitions already exist
- 🔧 **Multi-Platform Support** - Windows (browser), Appium (macOS & Mobile)
- 🤖 **MCP Integration** - Seamless GitHub Copilot connection via Model Context Protocol
- **Interactive CodeLens** - Preview a Scenario or Background recording, or run an existing test
- 📝 **Natural Language Tasks** - Execute automation from plain English descriptions

> 👨‍💻 **For Developers**: See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup and contribution guidelines.

---

## 🚀 Setup Guide

### Step 1: Install Extension

Open VS Code Extensions (`Ctrl+Shift+X` / `Cmd+Shift+X`) → Search "BDD AI Toolkit" → Install

### Step 2: Setup Environment

1. **Open Setup Panel**
   
   Click the BDD AI Toolkit icon in the Activity Bar (left sidebar)

2. **Auto-Resolve Environment**
   
   The setup panel will automatically detect and resolve environment issues:
   - Python installation
   - Node.js installation
   - Required dependencies
   
   Click **"Auto-Resolve"** if any issues are detected

3. **Configure the Canonical Runtime**

   Create `bdd_ai_conf.json` in the project root before running setup. Use the
   installed Runtime's documented schema:
   - Windows: `PYWINAUTO_CONFIG.apps_config.edge` or `.chrome`, matching the
     selected browser.
   - Appium: `APPIUM_DRIVER_CONFIGS.mac` on macOS or `.android` on Windows.

   Keep credentials as environment references. The Extension rejects a missing,
   unreadable, or unselected profile instead of writing an unusable MCP entry.

4. **Choose Platform & Click Setup**

   Select your target platform:
   - **Windows** - Browser automation
   - **Appium** - For macOS and mobile testing (iOS/Android)

   Click **"Setup"** to register the canonical installed Runtime through the
   Extension's MCP provider. If `bdd_ai_conf.json` changes, run setup again.

   > **Local Appium users**: invoke the canonical `autogenesis` Skill. It loads
   > the pinned supported official Appium workflow and guides the Coding Agent's
   > terminal diagnosis before the canonical installed Appium MCP starts.

5. **Inspect the Registered Server**

   Run **MCP: List Servers** from the Command Palette. The Extension supplies the
   canonical stdio definition directly; it does not create or modify
   `.vscode/mcp.json`.

6. **Verify Connection in GitHub Copilot**
   
   - Open GitHub Copilot Chat
   - Check MCP connections panel
   - Confirm "BDD AI Toolkit MCP" is connected

### Step 3: Preview Recording & Replay Existing Tests

**Recording preview** (no generated-file write):
1. Install the canonical Skill with `autogenesis install` for one explicit user
   or project scope. The extension authenticates the exact discovered
   `.agents/skills/autogenesis/SKILL.md` bytes at that scope.
2. Create or open a `.feature` file and write the Scenario in Gherkin.
3. Click **"Send to Copilot"** above the Scenario or Background.
4. The authenticated Skill executes the supplied steps, calls
   `before_gen_code` then `preview_code_changes`, returns the read-only proposed
   code, and stops with generated-file writes unavailable.

If the canonical Skill is absent or differs from the reviewed release, the
extension stops with the canonical install action. It never sends a fallback
full prompt, requests write approval, or copies/saves the proposed bytes.

**Replaying existing tests**:
1. Open a `.feature` file whose step definitions already exist.
2. Click **"Run"** above a Scenario.
3. The existing Behave test executes; recording preview does not create files.

---

## 🎯 Advanced Features

### Natural Language Tasks

Execute ad-hoc automation without writing scenarios:

**Command**: `BDD AI Toolkit: Execute Natural Language Task`

**Example**: 
```
"Open Chrome, go to google.com, search for 'AI testing', click first result"
```

AI converts your description to automation and executes immediately.


---



## 📚 Resources

- 🐛 [Report Issues](https://github.com/microsoft/vscode-extension-samples/issues)
- 💡 [Feature Requests](https://github.com/microsoft/vscode-extension-samples/discussions)
- 📖 [Gherkin Syntax Guide](https://cucumber.io/docs/gherkin/)
- 📖 [Behave Documentation](https://behave.readthedocs.io/)

---

## 📄 License

MIT License - See [LICENSE](LICENSE)

---

**Happy Testing! 🎉**
