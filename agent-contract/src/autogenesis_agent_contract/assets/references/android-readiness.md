# Android readiness

Require native macOS or Windows and select exactly one target class: authorized physical device, emulator/AVD, or SDK-only build tooling. Do not require emulator assets for a physical device or live device state for an SDK-only request.

Load authenticated `setup-uiautomator2` with `autogenesis appium-workflow setup-uiautomator2 --json` only when setup or prerequisite repair is required. Its official Driver setup, doctor, and server criteria remain authoritative. Use `appium-troubleshooting` for an existing UiAutomator2 session, transport, activity, helper-server, source, or locator failure after prerequisites pass. Optional FFmpeg and bundletool apply only when the user requested their capability.

Observe applicable candidates before mutation:

- Node/npm and the selected global Appium or explicitly requested local `npx --no-install` mode; evaluate active `engines.node` and peer constraints exactly.
- Java and `javac`; prefer a working current candidate, then Android Studio JBR, then other installed JDKs.
- Explicit Android SDK settings and conventional complete SDK roots. An incomplete `ANDROID_HOME` must not hide a complete default SDK.
- `sdkmanager`, platform-tools/ADB, required platform/build-tools, and emulator binaries only when applicable.
- Installed UiAutomator2 version and required doctor results.

Use temporary `JAVA_HOME`, `ANDROID_HOME`, and `PATH` when an existing candidate works. Persist them only as an approved change. License acceptance and SDK/Driver/package installation are protected changes.

`adb devices` may start the ADB daemon. Treat daemon start, USB authorization, emulator launch, application install, and session creation as runtime effects. A physical-device route requires one selected online authorized device; multiple materially different targets require one short user choice. An emulator route reuses a running compatible emulator, then an existing AVD; downloading an image or creating an AVD requires approval. A configured AVD is not a booted usable target.

`Target Prepared` requires applicable environment constraints, UiAutomator2 installation, required doctor checks, and a resolvable target class. `Live Ready` additionally requires a managed or preserved Appium server, `/status` with UiAutomator2, matching Appium MCP Contract identity, a real selected-device session, the intended application identity, and observed Android UI. Stop a server started for this task; preserve a pre-existing server.
