# BDD AI Toolkit

[![Version](https://img.shields.io/badge/version-1.2.43-blue.svg)](https://marketplace.visualstudio.com/)
[![VS Code](https://img.shields.io/badge/VS%20Code-1.95.0+-007ACC.svg)](https://code.visualstudio.com/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

AI-powered VS Code extension for BDD test automation. **Record** test scenarios with AI assistance and **Replay** them instantly - no manual coding required!

## ✨ Features

- 🎥 **AI-Powered Recording** - Write Gherkin scenarios, let AI generate automation code
- ▶️ **One-Click Replay** - Execute recorded scenarios directly from feature files
- 🔧 **Multi-Platform Support** - Windows (browser), Appium (macOS & Mobile)
- 🤖 **MCP Integration** - Seamless GitHub Copilot connection via Model Context Protocol
- 🎯 **Interactive CodeLens** - Record and replay buttons above each scenario
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

### Step 3: Record & Replay

Now you're ready to use AI-powered test automation!

**Recording** (AI generates code):
1. Create/open a `.feature` file
2. Write your scenario in Gherkin
3. Click **"Send to Copilot"** above the scenario
4. AI generates automation code automatically

> If `.github/skills/autogenesis/SKILL.md` exists, the extension sends `/autogenesis <Scenario Name>` to Copilot instead of the fallback prompt.

**Replaying** (Execute tests):
1. Open a `.feature` file with recorded scenarios
2. Click **"Run"** above any scenario
3. Watch the automation execute!

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

### Custom Copilot Prompt

Customize how AI generates code:

```json
{
  "bddAiToolkit.cucumber.copilotPrompt": "Generate step definitions for:\n\n${scenario_text}\n\nFile: ${feature_file_path}\n\nUse Behave framework and follow PEP 8 style."
}
```

**Available placeholders**:
- `${scenario_text}` - Full scenario content
- `${feature_file_path}` - Path to feature file

> **Note**: This prompt is used as fallback when the `autogenesis` Skill is not present in the workspace.

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
