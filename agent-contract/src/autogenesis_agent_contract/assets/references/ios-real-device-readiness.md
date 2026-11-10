# iOS real-device readiness

Require native macOS and one selected physical iOS or tvOS device. Use the shared readiness result with profile `ios-physical` or `tvos-physical`; simulator runtime, definition, and boot layers are not-applicable. Complete authenticated `setup-xcuitest` shared prerequisites before `xcuitest-real-device-config`. Use `appium-troubleshooting` only for later runtime failures outside signing or WDA deployment.

Record configured, detected, selected, rejected, and unverified Xcode candidates. Execute the relevant Xcode/device tools under one temporary `DEVELOPER_DIR`; do not trust directory presence or switch global Xcode automatically. Use the same Xcode, Node/Appium mode, `APPIUM_HOME`, device, and WDA route across official checks, server, MCP, and session.

Select the least-change WDA route before requesting signing information: reachable running endpoint, compatible preinstalled WDA, compatible prebuilt/pre-signed artifact, reusable local signing/provisioning assets, then Appium-managed local build/install. Stop at the first route satisfying the selected target. A running endpoint that accepts the real session does not require local build or signing evidence.

Observe device visibility with selected Xcode, connection, unlock, trust, Developer Mode, developer services, WDA route, endpoint, signing/provisioning match, bundle identity, deployment, and connectivity only when applicable. Keep device identifiers transient and durable fingerprints redacted. Never request Apple passwords, private keys, provisioning contents, signing archives, or credentials.

Connection, unlock, trust, Developer Mode, account/signing, and device confirmation are distinct user-native actions. Return exactly the next required action, then resume Agent-owned checks. Signing/provisioning changes, bundle changes, privileged commands, and device/WDA installation are protected effects; carry one unchanged approved effect set and rerun only affected layers.

`Target Prepared` requires shared XCUITest prerequisites, selected device, and viable WDA route with applicable trust/signing/deployment layers; it creates no disposable session. `Live Ready` requires matching Appium MCP identity, a real selected-device session through that route, intended application, and observed UI. Preserve pre-existing WDA/device state and clean only task-owned session/server resources.
