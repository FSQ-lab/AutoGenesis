# Native Windows readiness

Require native Windows, use profile `windows-native`, and route through Windows MCP, never Appium. Linux, WSL, remote non-interactive sessions, or incompatible elevation contexts remain blocked rather than substituted.

Record configured, detected, selected, rejected, and unverified Runtime/application candidates. Observe installed `autogenesis-windows-mcp` and Contract identity, current interactive desktop, elevation compatibility, selected application profile, resolved executable identity, launch arguments, SecretRefs, timeout, and window selector. Execute the resolved Runtime/executable checks; a config path, process name, or title match alone is not proof.

A profile requires nonempty `exe`, valid `window_title_re`, string-array `launch_args`, and timeout 1 through 120. Validate all profiles before startup but resolve references only for the selected profile. Creating or changing a profile is one protected project write: disclose exact destination, application identity, effects, references, consequences, rollback, and verification. Never invent executable paths, selectors, arguments, or secret values; required sensitive inputs remain SecretRefs.

Configure the current Coding Agent with the absolute installed Runtime command and argv while preserving unrelated MCP entries. Reload it when possible and prove MCP initialize, prompt/tool/resource discovery, and matching `autogenesis://agent-contract/identity` through that Agent. A package, config write, shell launch, or standalone schema list is not Runtime readiness.

Choose one explicit or uniquely observed application target. Before Live Ready require one verified visible, enabled, UIA-ready top-level window bound to the selected process/instance. Multiple matches are `Action Required` or `Blocked` until a target or selector is disambiguated; never choose the first. Elevation, invalid configuration, ambiguity, and identity-drift failures are not retried unchanged.

`Target Prepared` requires a valid selected profile, resolvable executable/reference inputs, compatible desktop/elevation state, and available Runtime without launching a disposable application. `Live Ready` additionally requires actual MCP discovery, one verified binding, intended application identity, and observed UI. Runtime EOF/cancellation releases binding without closing a user-owned application. Only explicit `app_close` may close the selected instance; never close unrelated processes sharing an executable.
