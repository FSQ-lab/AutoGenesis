// Copyright (c) Microsoft Corporation.
// Licensed under the MIT license.

/**
 * Default natural-language task prompt used for direct execution.
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
