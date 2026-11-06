"""Release layout shared by the loader and deterministic release tooling."""

CONTRACT_VERSION = "2.1.0"
SCHEMA_VERSION = 2
CORE_POLICY = "core-policy.md"
WORKFLOWS = (
    "execute_scenario",
    "generate_scenario_test",
    "execute_natural_language_task",
)
SKILLS = ("autogenesis",)
SCHEMAS = ("manifest", "identity", "arguments", "secret-reference")
REFERENCES = (
    "install",
    "readiness-common",
    "appium-environment",
    "android-readiness",
    "ios-simulator-readiness",
    "ios-real-device-readiness",
    "macos-readiness",
    "windows-readiness",
    "execution-common",
    "android-execution",
    "apple-execution",
    "windows-execution",
)
APPIUM_SKILLS_ROOT = "appium-skills"
APPIUM_SKILLS_MANIFEST = f"{APPIUM_SKILLS_ROOT}/manifest.json"
ASSET_PATHS = (
    CORE_POLICY,
    *(f"workflows/{name}.md" for name in WORKFLOWS),
    *(f"skills/{name}/SKILL.md" for name in SKILLS),
    *(f"references/{name}.md" for name in REFERENCES),
    *(f"schemas/{name}.schema.json" for name in SCHEMAS),
    APPIUM_SKILLS_MANIFEST,
)
