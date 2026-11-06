# Native Windows readiness

Require native Windows and route through Windows MCP, never Appium. Linux, WSL, remote non-interactive sessions, or incompatible elevation contexts remain blocked rather than silently substituted.

Observe the installed `autogenesis-windows-mcp` package and Contract identity, current interactive desktop, elevation compatibility, selected application profile, resolved executable, launch arguments, SecretRefs, timeout, and window selector. A profile requires nonempty `exe` and valid `window_title_re`; `launch_args` is a string array and `launch_timeout_seconds` is 1 through 120. Validate every profile before startup but resolve secrets only for the selected profile.

Creating or changing a profile is a protected project/configuration write. Present the exact profile, destination, application identity, launch effects, secret references, risks, rollback, and recheck. Never invent executable paths, window expressions, launch arguments, or secret values. An environment reference must remain a SecretRef where required and plaintext secret values must not enter prompts or evidence.

Choose one explicit or uniquely observed application target. Before `Live Ready`, require matching Windows MCP identity and one verified visible, enabled, UIA-ready top-level window bound to the selected process/instance. Multiple matching windows or processes are `Action Required` or `Blocked` until the selector or target is disambiguated; never choose the first arbitrary match. Elevation, invalid configuration, and ambiguity failures are not retried unchanged.

`Target Prepared` requires a valid selected profile, resolvable executable/reference inputs, compatible desktop/elevation state, and available Runtime. `Live Ready` additionally requires MCP initialize/discovery, one verified application binding, and observed UI. Runtime EOF/cancellation releases binding and in-memory state without closing a user-owned application. Only explicit `app_close` may close the selected instance; never close unrelated processes sharing an executable path.
