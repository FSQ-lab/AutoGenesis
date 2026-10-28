---
name: autoGenesis-win
description: Run Windows scenarios or request test generation using official AutoGenesis MCP prompts. Use for pywinauto Windows application automation.
---

# AutoGenesis Win

Use the connected Windows runtime's official MCP prompts. Discover them with
prompts/list; if unavailable, stop and report the missing contract integration.

- Execution: request execute_scenario with scenario_text and optional feature_file_path.
- Explicit test generation: request generate_scenario_test with scenario_text and required feature_file_path.
- A natural language action request: request execute_natural_language_task with task_text.

For a named scenario, read the user's selected feature file and supply applicable
Background plus the selected Scenario in source order as scenario_text. Resolve
ambiguous selections with the user. Follow the returned canonical policy and
workflow. Generation requests do not approve writes; follow its preview and
explicit approval flow. Do not recreate policy or use a legacy prompt fallback.

Canonical sources: autogenesis-agent-contract 1.2.0, assets/workflows/; identity:
autogenesis://agent-contract/identity. Regenerate this projection with
agent-contract/tools/sync_skills.py; do not edit the projection.
