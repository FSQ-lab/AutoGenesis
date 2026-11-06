# Apple-platform execution

Apply to iOS/tvOS XCUITest and native macOS Mac2 after selecting the correct Runtime route. Confirm the current application, window/surface, focus, context, and target identity only as needed. Do not rerun setup for an already verified live context.

Prefer accessibility identifiers and stable semantic attributes, then a bounded predicate or class-chain strategy supported by the observed Runtime. Use narrowly scoped hierarchy evidence before XPath; coordinates are a last resort with current geometry. Distinguish application content from iOS system alerts, SpringBoard, macOS menus, sheets, browser chrome, and Web content.

On iOS, verify current application/context after launch, alert handling, navigation, or WebView changes. On macOS, verify target bundle, active window, focus, and whether a control belongs to browser chrome or page accessibility content. Never treat a visible label alone as proof that the intended window or application owns it.

After timeout, interruption, or a missing response, query the smallest available session/application state before recovery. Do not rebuild WDA, change signing, reset a device, relaunch an application, or create a new session without evidence that the current state requires it and the action remains authorized. Close only task-owned sessions and preserve user applications, pre-existing WDA, simulators/devices, and servers.
