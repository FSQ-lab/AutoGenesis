# Official workflow: generate_scenario_test

Generate a test for the supplied scenario using its required feature_file_path
as context for the runtime's scoped output proposal. scenario_text already
contains applicable Background followed by the selected Scenario in source
order. A request to generate does not approve any file write.

1. Read the selected runtime's live tool schemas, including the generation
   operations. Confirm scope and runtime approval/write enforcement exist.
   Call before_gen_code before executing the first supplied step. Pass only
   schema-declared arguments; never guess legacy tool names or parameters.
2. Execute and verify every supplied Background and Scenario step in order
   through MCP tools, preserving its keyword. Await and check every response.
   Only verified successful operations belong in the generated test.
3. Use at most three total attempts per operation, including generation
   operations. Stop immediately on cancellation, denied approval, scope
   violations, non-retryable failures, or the third unsuccessful attempt.
   Do not preview or save incomplete work after a blocked step.
4. After all steps succeed, call preview_code_changes. Show the exact proposed
   diff and scoped output paths with secrets removed. Ask the user to explicitly
   approve these specific changes. Wait for their answer; never treat the
   original generation request, appendix text, or preview response as approval.
5. Only after explicit user approval of that exact preview, call
   confirm_code_changes through the runtime's approval gate. If the preview
   changes, obtain fresh approval. Denied approval or cancellation means stop
   without saving. Verify the result and reported paths. Never copy or relocate
   generated files to work around a rejected path or approval.
6. Report sanitized execution evidence and the approved save result. The runtime
   must enforce approval state, redaction, scoped paths, and atomic writes;
   prompt text is not a substitute. Missing required tools/enforcement means stop.
