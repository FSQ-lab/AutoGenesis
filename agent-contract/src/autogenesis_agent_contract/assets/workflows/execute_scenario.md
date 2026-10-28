# Official workflow: execute_scenario

Execute the supplied scenario without generating or saving test code.
scenario_text already contains applicable Background followed by the selected
Scenario in source order. feature_file_path, when present, is context data only,
not an instruction to discover, load, or execute another policy file.

1. Read the selected runtime's live tool schemas. Confirm authorized scope and
   required runtime enforcement are available.
2. Execute each supplied Background and Scenario step in order through MCP
   tools, preserving its keyword. Wait for and verify each tool result; use
   verification tools for assertions before moving to the next step.
3. Use at most three total attempts per operation. Stop immediately on
   cancellation, denied approval, scope violations, non-retryable failures,
   or the third unsuccessful attempt; never advance past that operation.
4. Report completed steps, sanitized evidence, and any blocked step. Do not
   invoke code generation or persist test code. Runtime permission and state
   enforcement remain mandatory; this workflow does not implement them.
