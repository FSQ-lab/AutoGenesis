# iOS simulator readiness

Require native macOS. This route covers iOS or tvOS simulators only; do not enter physical-device trust, signing, provisioning, or WebDriverAgent deployment guidance.

Load authenticated `setup-xcuitest` only when shared XCUITest setup or prerequisite repair is required. Reuse its selected global Appium or explicitly requested local mode, Xcode prerequisites, Driver doctor, and server criteria. Use `appium-troubleshooting` for an existing XCUITest session, launch, source, alert, or locator failure after setup passes.

Observe the active and installed Xcode toolchains, `xcode-select`, license/first-launch state, installed simulator runtimes, booted simulators, compatible existing simulator definitions, XCUITest installation, and target application identity. Execute tools from the selected Xcode rather than trusting directory presence alone. Changing global Xcode selection, accepting a license, first-launch installation, downloading a runtime, creating a simulator, or installing an application is protected. Simulator boot is an ephemeral runtime effect; do not silently substitute a different model or OS version.

Choose the user's explicit target, then a unique compatible booted simulator, then a unique compatible existing simulator. Ask once when materially different usable targets remain. `Target Prepared` requires a selected compatible Xcode, XCUITest required doctor checks, and a resolvable simulator/application route. `Live Ready` additionally requires Appium server evidence, matching Appium MCP identity, a real XCUITest session on the selected simulator, the intended application, and observed UI. A simulator inventory or boot state alone is not live proof.
