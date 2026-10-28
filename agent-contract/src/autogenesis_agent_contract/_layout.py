"""Release layout shared by the loader and deterministic release tooling."""

CONTRACT_VERSION = "1.1.0"
SCHEMA_VERSION = 2
CORE_POLICY = "core-policy.md"
WORKFLOWS = (
    "execute_scenario",
    "generate_scenario_test",
    "execute_natural_language_task",
)
SKILLS = ("autoGenesis-run", "autoGenesis-win")
SCHEMAS = ("manifest", "identity", "arguments", "secret-reference")
ASSET_PATHS = (
    CORE_POLICY,
    *(f"workflows/{name}.md" for name in WORKFLOWS),
    *(f"skills/{name}/SKILL.md" for name in SKILLS),
    *(f"schemas/{name}.schema.json" for name in SCHEMAS),
)
