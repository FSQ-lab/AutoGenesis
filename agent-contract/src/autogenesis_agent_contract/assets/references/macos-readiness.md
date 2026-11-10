# Native macOS readiness

Require native macOS, use profile `macos-native`, and route through Appium Mac2, never XCUITest. Load authenticated `setup-mac2` only for setup or prerequisite repair. Existing Mac2 runtime failures outside that workflow require targeted primary documentation, not unsupported troubleshooting guidance.

Record configured, detected, selected, rejected, and unverified Xcode candidates. Execute `xcode-select`, `xcodebuild`, and required tools under one temporary `DEVELOPER_DIR`; do not trust a directory or switch global Xcode automatically. Use the same Xcode, Node/Appium mode, `APPIUM_HOME`, target application, and actual launcher/process identity across official checks, server, MCP, and session.

Observe license/first-launch state, Mac2 installation and doctor evidence, target application path/bundle identity, Appium server ownership, and the actual process needing privacy authorization. Changing Xcode selection, accepting licenses, first-launch installation, Appium/Mac2 installation, or privacy settings is protected or human-only. Browser tasks use the browser bundle through macOS Accessibility and do not require ChromeDriver or EdgeDriver.

Accessibility and other TCC approvals are process-identity-specific. Terminal, Coding Agent, MCP client, Runtime, Node/Appium, and Xcode helpers may not share authorization. Keep privacy unknown until a relevant observation proves it. If a minimal authorized session reports a blocker, identify the exact visible process and one System Settings action; never request a password/biometric response or automate the privacy control. Rerun only the affected live check afterward.

`Target Prepared` requires selected Xcode tooling, Mac2 installation, required doctor checks, and resolvable application identity without a disposable session. `Live Ready` additionally requires `/status` with Mac2, matching Appium MCP identity, a real Mac2 session against the intended application, and observed window/UI evidence. Preserve user-owned applications and pre-existing servers; clean only task-owned session/server resources.
