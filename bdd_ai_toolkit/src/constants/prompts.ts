// Copyright (c) Microsoft Corporation.
// Licensed under the MIT license.

/**
 * Default prompts and templates used throughout the BDD AI Toolkit
 */

/**
 * Default COPILOT_PROMPT value used across the extension
 * This prompt is used when sending test cases to Copilot for execution
 */
export const DEFAULT_COPILOT_PROMPT = `Apply the authenticated canonical autogenesis Skill exactly.

# Explicit recording request for this exact BDD test case
\${scenario_text}

Feature context: '\${feature_file_path}'

Requirements:
1. Route this explicit recording request only through generate_scenario_test.
2. Before the first supplied step, call before_gen_code.
3. Execute and verify every supplied step exactly in order, then call preview_code_changes.
4. Stop after the read-only preview and report that generated-file writes are unavailable.
5. Never request write approval or copy, save, shell-write, or otherwise persist the proposed bytes.`;

/**
 * Default NATRUAL_LANGUAGE_TASK_PROMPT value used across the extension
 * This prompt is used when sending test cases to Copilot for execution
 */
export const DEFAULT_NATURAL_LANGUAGE_TASK_PROMPT = `**🤖 EXECUTE WITH MCP TOOLS ONLY**

Please use \`native-mcp-server\` MCP tools to **test** the following scenario:

**Task:** \${scenario_text}

**🔧 MANDATORY REQUIREMENTS:**
1. Operate in an interactive loop to complete the test
2. **ONLY USE MCP TOOLS** - Do not describe actions, actually execute them
3. For **EVERY action**, you **MUST call a native-mcp-server MCP tool**
4. Execute steps **in sequence** - consider previous results before next action

**⚠️ FORBIDDEN ACTIONS:**
- Do NOT call before_gen_code or preview_code_changes; direct execution never generates or writes files
- Do NOT describe what you would do - actually DO it using MCP tools
- Do NOT skip MCP tool calls

**START EXECUTION NOW** 🚀`;
