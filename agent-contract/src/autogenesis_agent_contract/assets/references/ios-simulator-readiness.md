# iOS simulator readiness

Require native macOS and use the shared readiness result with profile `ios-simulator` or `tvos-simulator`. Do not enter physical-device trust, Developer Mode, signing, provisioning, or WDA deployment guidance; mark those layers not-applicable.

Load authenticated `setup-xcuitest` only when shared XCUITest setup or prerequisite repair is required. Reuse its selected Appium mode, Driver doctor, and server criteria. Use `appium-troubleshooting` for an existing XCUITest session, launch, source, alert, or locator failure after setup passes.

Record configured, detected, selected, rejected, and unverified Xcode/toolchain candidates. Execute `xcode-select`, `xcodebuild`, and `simctl` from each relevant candidate through one temporary `DEVELOPER_DIR`; a directory or application icon is not proof. Choose a candidate whose license/first-launch state, SDK, simulator runtime, and XCUITest requirements satisfy the requested profile. Changing global Xcode selection, accepting a license, first-launch installation, or runtime download is protected.

Observe installed simulator runtimes, booted simulators, compatible existing definitions, and application route using the selected Xcode. Choose the explicit target, then one unique compatible booted simulator, then one unique compatible existing simulator. Ask once only when materially different targets remain. Boot is an ephemeral effect; runtime download, simulator creation, erase/reset, and application install are distinct protected effects. A runtime is not a simulator definition, a definition is not boot-complete, and boot is not live control.

Use the same `DEVELOPER_DIR`, Node/Appium mode, `APPIUM_HOME`, and selected simulator across official checks, server, MCP, and session. Install only after existing candidates are exhausted; rerun only affected layers.

`Target Prepared` requires selected Xcode tooling, compatible runtime/target, XCUITest installation, required doctor checks, and a resolvable application route without a disposable session. `Live Ready` additionally requires Appium server evidence, matching Appium MCP identity, a real session on the selected simulator, intended application, and observed UI. Preserve pre-existing simulators/servers and clean only task-owned boot/session/server effects.
