"""Release layout shared by the loader and deterministic release tooling."""

CONTRACT_VERSION = "2.2.0"
SCHEMA_VERSION = 2
CORE_POLICY = "core-policy.md"
WORKFLOWS = (
    "execute_scenario",
    "generate_scenario_test",
    "execute_natural_language_task",
)
SKILLS = ("autogenesis-setup", "autogenesis-run")
SCHEMAS = ("manifest", "identity", "arguments", "secret-reference")
APPIUM_SKILLS_ROOT = "skills/autogenesis-setup/references/appium-skills"
APPIUM_SKILLS_MANIFEST = f"{APPIUM_SKILLS_ROOT}/manifest.json"
ASSET_PATHS = (
    CORE_POLICY,
    *(f"workflows/{name}.md" for name in WORKFLOWS),
    *(f"skills/{name}/SKILL.md" for name in SKILLS),
    *(f"schemas/{name}.schema.json" for name in SCHEMAS),
    APPIUM_SKILLS_MANIFEST,
)
