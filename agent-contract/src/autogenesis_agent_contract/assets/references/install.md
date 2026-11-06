# Machine bootstrap

Use this reference only for installing, activating, or repairing AutoGenesis itself. Do not select a target platform, inspect devices or applications, install Appium dependencies, or create an automation session.

Use `autogenesis install` through the user's chosen Python environment, package index, isolation policy, and `user` or `project` Skill scope. Stable installation uses the immutable Release manifest. Candidate acceptance uses exact first-party wheel URLs and SHA-256 identities without index fallback.

Before mutation, disclose the complete package, Skill scope, destination, source identity, effects, and rollback once. An explicit install request authorizes that unchanged disclosed plan; a diagnosis-only request does not. Preserve unrelated MCP configuration and fail closed on shadow Skills, legacy `autogenesis-setup` or `autogenesis-run`, scope ambiguity, unsafe paths, byte drift, or Contract mismatch.

`Machine Ready` requires the canonical `autogenesis` Skill at the selected discovery scope, the host-supported Runtime packages, matching package versions, verified workflow inventory, and `autogenesis://agent-contract/identity`. Native macOS installs Appium Runtime; native Windows installs Appium and Windows Runtimes. Linux and WSL stop before writes.

A successful package command is not enough. Verify the discovered Skill path and bytes from the Coding Agent when possible. Do not call a target `Prepared` or `Live Ready`, and do not create a platform session merely to validate machine installation.
