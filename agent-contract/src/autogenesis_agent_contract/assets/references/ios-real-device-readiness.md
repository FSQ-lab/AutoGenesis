# iOS real-device readiness

Require native macOS and one selected physical iOS or tvOS device. Complete authenticated `setup-xcuitest` shared prerequisites before loading `xcuitest-real-device-config`. Use `appium-troubleshooting` only for later runtime failures outside signing or WDA deployment.

Select the least-change WDA route before requesting signing information: reachable running WDA endpoint, compatible preinstalled WDA, compatible prebuilt/pre-signed artifact, reusable local signing/provisioning assets, then Appium-managed local build and install. Stop at the first route that satisfies the selected target. A running endpoint that accepts an Appium session does not require local build or signing evidence.

Observe device visibility with the selected Xcode, connection, unlock, trust, Developer Mode, developer services, WDA route, endpoint reachability, signing match, provisioning match, bundle identity, deployment, and connectivity only as applicable. Keep device identifiers as transient operational values and durable redacted fingerprints. Never request or record Apple passwords, private keys, provisioning contents, signing archives, or credentials.

Trust, Developer Mode, signing/provisioning changes, bundle changes, privileged commands, and device/WDA installation are protected or human-only. Present one current human action at a time; connection, unlock, trust, and Developer Mode are distinct actions.

`Target Prepared` requires shared XCUITest prerequisites, a selected device, and a viable WDA route with applicable trust/signing/deployment prerequisites. `Live Ready` requires matching Appium MCP identity, a real session attached through the selected WDA route, the intended application identity, and observed UI. Preserve pre-existing WDA and device state; clean only task-owned session/server resources.
