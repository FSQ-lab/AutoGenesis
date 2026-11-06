# Native macOS readiness

Require native macOS and use Appium Mac2, never XCUITest. Load authenticated `setup-mac2` only when setup or prerequisite repair is required. Existing Mac2 runtime failures not covered by the official workflow require targeted primary documentation; do not route them through unsupported troubleshooting guidance.

Observe the active Xcode command-line tools, license/first-launch state, selected global Appium or explicitly requested local mode, Mac2 installation and required doctor results, target application/bundle identity, Appium server ownership, and the actual process identity that needs macOS privacy authorization. Execute selected tools rather than trusting paths alone.

Accessibility and other TCC approvals are process-identity-specific. Terminal, a Coding Agent app, MCP client, Runtime, Node/Appium, and Xcode helpers may not share authorization. If a minimal Mac2 session reports a privacy blocker, identify the exact visible application/process the user must authorize, request that one action, and rerun the narrow live check. Moving, reinstalling, or re-signing an executable can invalidate prior authorization.

Changing Xcode selection, accepting licenses, first-launch installation, installing Appium/Mac2, or privacy settings is protected or human-only. Browser tasks use the browser bundle as a macOS desktop application through Accessibility; they do not require ChromeDriver or EdgeDriver.

`Target Prepared` requires selected Xcode tooling, Mac2 installation, required doctor checks, and a resolvable application identity. `Live Ready` additionally requires `/status` with Mac2, matching Appium MCP identity, a real Mac2 session against the intended bundle/application, and observed window/UI evidence. Preserve user-owned applications and pre-existing servers.
