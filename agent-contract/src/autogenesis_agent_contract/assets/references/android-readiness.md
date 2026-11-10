# Android readiness

Require native macOS or Windows and select exactly one profile: authorized physical device, emulator/AVD, or SDK-only build tooling. Use the shared readiness result and mark every profile-specific layer required, optional, or not-applicable before discovery. A physical route does not require emulator package, image, AVD, or boot; SDK-only does not require a live device.

Load authenticated `setup-uiautomator2` only when setup or prerequisite repair is required. Its current Appium/Driver setup, doctor, and server criteria remain authoritative. Use `appium-troubleshooting` for an existing UiAutomator2 session, transport, activity, helper-server, source, or locator failure. Optional FFmpeg and bundletool apply only when requested.

## Select one task environment

Record configured, detected, selected, rejected, and unverified values. Use the same selected `JAVA_HOME`, Android SDK root, Node/Appium mode, `APPIUM_HOME`, and PATH for official checks, Appium server, Appium MCP, and the session. Prefer temporary environment values; persistence is a separate protected change.

### Java/JDK

Consider, in order, a task-scoped `JAVA_HOME`; `java` and `javac` paired from task PATH; OS-registered or package-manager JDKs; retained user JDK installations; and Android Studio JBR. Conventional JBR locations include the installed Android Studio application on macOS and Windows, but directory presence is not proof.

For every candidate execute its exact `java` and `javac`, record actual version and reported `java.home`, and reject stubs, broken pairs, or candidates violating observed Driver/SDK requirements. Missing PATH Java or one failed configured candidate does not justify installation. Prefer a working current candidate, then a working Android Studio JBR, then another compatible installed JDK.

### Android SDK

Consider task-scoped `ANDROID_HOME`, legacy `ANDROID_SDK_ROOT` as evidence only, Android Studio's configured SDK, conventional user roots (`~/Library/Android/sdk` on macOS and `%LOCALAPPDATA%/Android/Sdk` on Windows), and other retained SDK roots. An incomplete configured root must not hide a complete conventional root.

Execute the selected tools rather than trusting directories: `adb version` for platform tools; the exact existing `sdkmanager --version` only when SDK package management is needed; and `emulator -version` plus the matching `avdmanager` only for an emulator route. Check only target-relevant platform/build-tools. Do not require `latest` command-line tools when another installed revision works, mix tools from different SDK roots, or add emulator directories to PATH for a physical request.

### Target

Treat `adb devices` daemon start, USB authorization, emulator launch, application install, and session creation as runtime effects. A physical route selects one online authorized device; offline, unauthorized, or materially different multiple devices require one relevant observation or user choice. An emulator route prefers a compatible running emulator, then an existing AVD; a configured AVD is not boot-complete. Image download, AVD creation, erase/reset, and persistent configuration require approval.

## Evaluate and repair

Classify Java, SDK, target, Node/Appium, UiAutomator2, and applicable doctor evidence independently. Preserve raw official required-fix/warning meaning while applying profile applicability; an emulator-only warning is not a physical-device blocker, but do not claim the raw doctor passed when it did not.

Install only when every applicable existing candidate is unusable. One minimum repair plan identifies exact source/version, destination, license or security effect, persistence, rollback, and affected checks. After approval rerun only those checks, with the same selected environment.

`Target Prepared` requires all applicable static environment constraints, UiAutomator2 installation, required doctor checks, and a resolvable target profile. `Live Ready` additionally requires a managed or preserved Appium server, `/status` with UiAutomator2, matching Appium MCP Contract identity, a real selected-target session, intended application identity, and observed Android UI. Stop task-owned server/session resources and preserve pre-existing ones.
