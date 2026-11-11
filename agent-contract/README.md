# AutoGenesis Agent Contract

Canonical Python distribution `autogenesis-agent-contract`, contract `2.1.0`,
manifest schema `2`, Python >=3.10, MCP SDK >=1.23,<2. Requirement and frozen
interface: [issue #30](https://github.com/FSQ-lab/AutoGenesis/issues/30).

## Consumer interface

```python
from autogenesis_agent_contract import (
    ContractIdentity, RuntimeContractRequirement, SecretRef, load_appium_skills,
    load_contract, load_project_appendix, register_mcp,
)
from mcp.server.fastmcp import FastMCP

# These pins belong to the runtime release, independently of the installed wheel.
required = RuntimeContractRequirement(
    contract_version="2.1.0",
    manifest_sha256="e0f68e4e947114dc6982c3502dab37cdfa5154fb45abe3092d78341da4a4045f",
)
contract = load_contract(ContractIdentity(required.contract_version, required.manifest_sha256))
appendix = load_project_appendix("/absolute/business-project")
server = FastMCP("business-runtime", instructions=contract.instructions)
register_mcp(server, contract, appendix, required)
```

- `load_contract(expected_identity: ContractIdentity | None = None) -> AgentContract`
  verifies the pinned manifest and every asset before returning an immutable snapshot.
- `AgentContract.read_skill(name: str) -> bytes` returns held verified bytes for
  exactly `autogenesis`; it never rereads package paths.
- `AgentContract.read_reference(name: str) -> str` returns one held, verified
  internal install, readiness, or execution reference from the allowlisted
  Contract inventory; unknown and path-like names fail closed.
- `AgentContract.identity -> ContractIdentity` has `contract_version`,
  `manifest_sha256`, and `schema_version` (current `2`); `to_dict()` returns metadata.
- `load_appium_skills(contract: AgentContract | None = None) -> AppiumSkillsBundle`
  verifies the internal supported `appium/skills` snapshot. `load_workflow(id)`
  returns one authenticated official entrypoint with declared Context/tool inventory.
  The broad upstream smoke executable remains excluded; the canonical Skill directs
  the Coding Agent to apply its documented status, selected-Driver, and cleanup
  criteria through the normal terminal and platform MCP. `read_asset(relative)`
  returns held bytes without trusting a mutable package path.
- `AgentContract.instructions -> str` contains the identity and fixed Core Policy.
- `AgentContract.render(workflow_id: str, arguments: Mapping[str, str],
  appendix: ProjectAppendix | None = None) -> str` always emits identity, Core
  Policy, official workflow, subordinate appendix, then task data. Untrusted
  blocks use JSON strings with escaped delimiters. This preserves task text
  while preventing it from syntactically terminating a labeled block.
- `register_mcp(server, contract, appendix, runtime_identity) -> None` registers
  three prompts and one read-only resource. Construct a fresh FastMCP server
  with `instructions=contract.instructions`; differing initialize instructions
  or exact runtime pins fail before registration. Public discovery preflights
  every canonical prompt name and the literal identity URI; any collision fails
  before mutation. Call once on a quiescent server before serving clients, with
  no concurrent registry writers. This function serializes its own registrations.
  Every canonical prompt and identity read shares a publication gate that opens
  only after all insertions and discovery checks succeed. The identity resource
  is inserted last. On any failure, discard the server and abort startup. SDK
  versions 1.23/1.29 have no public prompt/resource rollback, so gated, unusable
  entries may remain after an injected insertion failure. They never return
  canonical prompt content or identity JSON. Initialize instructions already
  belong to the constructed server, so serving a failed instance is unsupported.
- `SecretRef` serializes as `{"$secret": "env:NAME"}`. Runtimes retain this
  reference through recording and the read-only generated-code preview, and
  resolve plaintext only inside the current tool execution.
- `UnboundSecret` serializes as `{"$secret": "unbound:BINDING"}` and blocks
  preview until a Coding Agent supplies an explicit environment-backed binding.
- `load_project_appendix(project_root) -> ProjectAppendix | None` accepts an
  explicit absolute project directory, with no `..` components. Only
  `.autogenesis/instructions.md` is read. Missing means `None`; invalid present
  paths/content fail. Call once at startup and retain that snapshot until restart.
  A snapshot exposes `text` and `sha256`; its representation omits text.
  Windows supports explicit local drive roots through held component handles.
  UNC/device-namespace roots are rejected before native calls. Mapped network,
  SUBST, and unverified drive aliases are rejected without opening their targets.
  Every Windows directory component and final file must be non-reparse; even
  in-root junctions/symlinks are rejected rather than followed.

Runtime consumers must pin an independently approved version and manifest hash.
Deriving the runtime requirement from the newly loaded identity would not detect
a runtime/contract compatibility mismatch.

| MCP prompt | Exact arguments |
| --- | --- |
| `execute_scenario` | required `scenario_text`; optional `feature_file_path` |
| `generate_scenario_test` | required `scenario_text`, `feature_file_path` |
| `execute_natural_language_task` | required `task_text` |

All argument values must be nonempty UTF-8 strings without NUL. No unknown,
override, or disable arguments are supported. Scenario text already includes
applicable Background followed by the selected Scenario, in source order.
Feature paths are context data: rendering does not read them or authorize writes.
Only the generation workflow references generation operations.

The generation workflow ends after `preview_code_changes`. The public Preview
does not expose a generated-file confirmation or commit tool; proposed bytes
cannot be saved through the Contract's stdio surface or an alternate copy route.

`autogenesis://agent-contract/identity` returns contract identity plus appendix
presence, the constant relative appendix path, and its separate SHA-256. It
never returns appendix text or a user's absolute project path. Its schema is
`assets/schemas/identity.schema.json`.

## Agent Install Prompt boundary

Candidate and public generators share one fail-closed installation contract. The
Candidate prompt is externally anchored to one canonical repository, positive Actions
run and attempt, head commit, attempt-qualified name, and exactly one unexpired
immutable artifact with a positive observed artifact ID. The public prompt is anchored
to the exact canonical immutable GitHub Release ID, tag, commit, and asset set. The
builders accept only local `.` for Candidate assets and the exact canonical GitHub
Release URLs for public assets. `SHA256SUMS` is generated after the final prompt and
covers every shipped asset except itself; self-consistent copied bytes are insufficient.

Each prompt selects one local private per-user parent with stable native identity,
current-user ownership, and permissions/ACLs that deny every other OS identity
write/create/delete/delete-child control. Shared, untrusted, unsafe, network-backed,
symlink, and reparse parents are rejected. A cryptographically random leaf with at
least 128 bits of entropy is generated for the exact installation, and its exact
absolute transaction path plus environment/staging/download/extraction/cache children
appear in the immutable plan before explicit approval.

After approval, the exact leaf is atomically created with fail-if-exists and no-follow
reservation semantics. Collision or changed parent/leaf state stops and requires a new
random path, plan, and approval. One exclusive transaction lock is held for the complete
create/install/verify/rollback/cleanup lifecycle. Stable parent/leaf identities and a
private unpredictable ownership marker are recorded. The lock, private parent ownership
and permissions, leaf identity, and marker are rechecked before and after each phase.
Final placement remains native atomic no-replace.

After successful reservation, standard pathname-based stdlib `venv`, `pip`, and
installed CLI operations are permitted within the exact transaction root. The boundary
explicitly trusts processes already running as the same OS user identity and does not
claim to prevent malicious same-user replacement of pathname-addressed state; no native
privileged/sandboxed Bootstrap is introduced. Reservation and cleanup use no-follow
opens where supported. Cleanup deletes only still-matching prompt-owned state; a missing
lock, changed parent permission or identity, substituted leaf, marker mismatch, symlink,
reparse point, or ambiguity forbids deletion and preserves the state.

The base Python creates the venv in isolated mode. Every child receives an explicit
minimal environment that omits all `PYTHON*` and startup customization. Ambient
`PIP_*` and `UV_*` names are removed without reading their values. Pip then receives
only `PIP_CONFIG_FILE=/dev/null` on macOS or `PIP_CONFIG_FILE=NUL` on Windows and
always runs with `--isolated`; failure to establish the platform null configuration
stops installation. Acquisition binds destination, staging, cache, authenticated
requirements/hashes, and the approved opaque source/auth interface to transaction
roots. Offline pip installation additionally fixes `--no-index`, `--no-cache-dir`,
`--find-links`, `--require-hashes`, and `--no-deps` and targets only the reserved venv.
If uv is used, it always receives `--no-config` and explicit transaction cache,
staging, destination, Python, and source bindings; after staging it is likewise
offline/no-index. No ambient user/global configuration, source, cache, target, prefix,
or credentials are inherited. All subsequent operations use absolute disposable-
environment entrypoints while the phase-boundary checks continue to pass.

Before echo/use, source metadata must be a canonical lowercase ASCII DNS hostname,
canonical IP literal, and one finite class: `managed-policy`, `user-approved`,
`default-public`, or `undisclosed`. Interface trust is independent, not self-attested.
Invalid metadata is never echoed and becomes `undisclosed`, stopping installation.
Full URLs, credentials, environment/config values, errors, output, and evidence are
never read for disclosure; redaction after reading is forbidden.

## Integrity and diagnostics

Assets are hashed as exact UTF-8/LF bytes, including their final LF. CRLF and BOM
are rejected, not normalized. The manifest contains all policy, workflow, Skill,
and schema assets except itself. The identity hashes exact manifest bytes; the
release pin in `_release.py` prevents a modified asset plus rewritten manifest
from becoming trusted automatically. Missing, corrupt, unsupported, or mismatched
releases fail closed. No mutable user override or legacy fallback is loaded.
Manifest reads are capped at 64 KiB and each official asset at 256 KiB, before
hashing. Known special files, directories, symlinks/reparse points, and changed
opened files are rejected. Reads are bounded even if a file grows after stat;
POSIX opens are nonblocking/no-follow. Installed wheel assets must be ordinary
filesystem files; zip/custom resource backends are unsupported and fail closed.

`ContractError` is a `ValueError` with `code`, a fixed `reason` identifier, and
`to_dict()`. Its string form is the same JSON object. Reasons never interpolate
caller content, argument names, raw exceptions, or appendix text.

This guarantee applies to errors raised by this package, not all FastMCP or MCP
transport errors. The canonical adapter sanitizes unknown arguments and invalid
values **after the SDK dispatches a known prompt to it**. `AgentContract.render`
also sanitizes unknown workflow IDs directly. However, the SDK rejects unknown
MCP prompt names before calling any adapter and interpolates the name in its
exception and error log. Invalid wire models (for example non-string MCP prompt
argument values) are validated even earlier and may include raw input in
Pydantic diagnostics. Other resources/tools and transport/debug logging are
also outside this boundary. Do not send secrets in dispatch names or malformed
wire data. Consumers need a separate protocol/logging boundary for those cases.
FastMCP's public registration APIs cannot replace its already-bound low-level
dispatch/validation handlers; this package does not mutate private handlers or
claim an end-to-end redaction guarantee. See the supported
[1.23 dispatch implementation](https://github.com/modelcontextprotocol/python-sdk/blob/v1.23.0/src/mcp/server/fastmcp/server.py)
and [1.29 dispatch implementation](https://github.com/modelcontextprotocol/python-sdk/blob/v1.29.1/src/mcp/server/fastmcp/server.py).

| Stable code | Boundary |
| --- | --- |
| `AUTOGENESIS_CONTRACT_MISMATCH` | Invalid/mismatched expected identity, unsupported contract version, runtime pins, initialize instructions |
| `AUTOGENESIS_CONTRACT_INTEGRITY_ERROR` | Asset/manifest/schema failure; unknown workflow or invalid workflow arguments |
| `AUTOGENESIS_PROJECT_INSTRUCTIONS_INVALID` | Invalid root, unsafe/unreadable file, invalid UTF-8, size >64 KiB, invalid appendix snapshot |

Appendix hashes cover exact input bytes, including CRLF if present; they are
separate from official identity. In-root symlinks are supported; escaping or
dangling links fail on POSIX. POSIX opens are anchored to directory descriptors
with no-follow component opens. Windows queries the drive's local volume
identity without opening a filesystem target, then uses handle-relative
`NtCreateFile` opens from that verified volume. Every ancestor, explicit project
root, and `.autogenesis` handle remains held without delete/write sharing until
the read completes. `FILE_OPEN_REPARSE_POINT` and `OBJ_DONT_REPARSE` prevent
following reparse targets; handle metadata rejects reparses and special files.
Names are preserved with no forced case-insensitive lookup, path resolution,
or case-folded containment comparison. The final synchronous handle is read in
bounded chunks and decoded as UTF-8 by the shared snapshot loader. Sharing
conflicts and unverifiable native results fail closed with sanitized reasons.
See [handle-relative object attributes](https://learn.microsoft.com/en-us/windows/win32/api/ntdef/ns-ntdef-_object_attributes)
and [NtCreateFile options](https://learn.microsoft.com/en-us/windows-hardware/drivers/ddi/ntifs/nf-ntifs-ntcreatefile). Only regular files
are read, with a bounded 64 KiB + 1 read. There is no upward discovery, network
fetch, include processing, environment expansion, templating, or execution.

Callers must supply secret-free task and domain text, using environment-variable
references. This package does not detect arbitrary credentials in text. Its
generation module binds a complete read-only preview to the session, a
project-relative proposed destination, base-file state, and digest. Recording
initialization returns only an opaque generation ID. Neither `register_mcp` nor
the Runtime adapters register a confirmation or commit tool; generated-file
writes are unavailable through the public stdio surface.

## Generated sources

Only change official assets while authoring an approved unreleased Contract.
Published Contract bytes remain immutable. The current clean-room cutover replaces
`autogenesis-setup` and `autogenesis-run` with one `autogenesis` Skill and limits
the pinned official Appium snapshot to the reviewed UiAutomator2, XCUITest,
real-device, Mac2, and troubleshooting dependency closure. A release still
requires an explicit version decision and schema review as applicable.

First check out the immutable upstream Appium Skills commit separately. The
verifier checks its Git commit, tree object, and origin when Git metadata is
present, then compares the explicit provenance inventory byte-for-byte:

```bash
git clone https://github.com/appium/skills.git /path/to/appium-skills
git -C /path/to/appium-skills checkout --detach e907024c210fe024c956ed9c74146fc27b1dd013
python3 agent-contract/tools/freeze_appium_skills.py --upstream-root /path/to/appium-skills --write
python3 agent-contract/tools/freeze_assets.py --write
python3 agent-contract/tools/sync_skills.py
```

The first tool rejects a missing external tree, the wrong commit/repository,
unsafe, extra, missing, or transformed allowlisted files, and provenance digest
drift. It freezes only bytes proven equal to the pinned upstream inventory. The
recorded subset digest is reproducible: SHA-256 starts with
`AutoGenesis Appium Skills subset v1\0`, then for each inventory path in sorted
order hashes its UTF-8 path prefixed by a four-byte big-endian length and its
exact content prefixed by an eight-byte big-endian length. The second tool
materializes the outer Contract manifest and release pin. The third
atomically projects the two public Skills. None follows output symlinks. No
Runtime source is changed. All tools use bounded regular-file reads; unsafe or
drifting inputs fail before projection. Read-only checks are:

```bash
python3 agent-contract/tools/freeze_appium_skills.py --upstream-root /path/to/appium-skills
python3 agent-contract/tools/freeze_assets.py
python3 agent-contract/tools/sync_skills.py --check
```

On Windows, check out these assets with `core.autocrlf=false`. CI configures this
before checkout so byte identity is consistent across platforms.

## Integration Lead verification

Run from the repository root with Python 3.10, then Python 3.12. The build tool
must be available (`python3 -m pip install 'build>=1.2,<2'`). No repository-wide
checks are required.

```bash
python3 agent-contract/tools/freeze_appium_skills.py
python3 agent-contract/tools/freeze_assets.py
python3 agent-contract/tools/sync_skills.py --check
python3 -m build --wheel --outdir /tmp/autogenesis-contract-wheel agent-contract
python3 agent-contract/tools/verify_wheel.py --wheel-dir /tmp/autogenesis-contract-wheel --mcp-version 1.23.0 --evidence-dir /tmp/autogenesis-contract-evidence-1.23.0
python3 agent-contract/tools/verify_wheel.py --wheel-dir /tmp/autogenesis-contract-wheel --mcp-version 1.29.1 --evidence-dir /tmp/autogenesis-contract-evidence-1.29.1
```

`verify_wheel.py` creates a fresh venv and business directory outside the checkout,
installs only the built wheel, selected SDK, and focused test dependencies, then
runs `agent-contract/tests` with isolated imports. It records Python, OS, SDK,
runner image/version, contract identity, JUnit results, and initialize/prompts/
resource transcripts. It also prepares paired eval requests, without claiming
model behavior has been evaluated. The venv/business directory is removed;
evidence remains at the explicitly supplied location. On Windows use `python`
and native absolute temporary paths. Windows protocol tests load both present
and absent appendices. Cross-platform native API mocks cover component handle
lifetime/sharing flags, case-sensitive siblings, UNC roots, reparse rejection,
special handles, read bounds, and UTF-8 errors. Common ordinary-file tests run
on Windows too; only POSIX-specific symlink/FIFO behavior is platform-marked.

CI covers Ubuntu 24.04 and Windows 2022, Python 3.10/3.12, SDK 1.23.0/1.29.1.
The same commands must run on the frozen local macOS 26.7.1 arm64/Python 3.12
environment. See [evals/README.md](evals/README.md) for the independent prompt
comparison. VS Code parity remains #3; runtime integration remains #5/#6.
Independent review, security review, acceptance, and issue/PR evidence attachment
remain Integration Lead responsibilities. No implementer-run acceptance is
claimed.

## Rollback and limits

The package writes no project configuration and never edits the appendix.
Candidate rollback removes its packages or isolated environment, the selected
user/project `autogenesis` Skill, MCP entries, downloaded/extracted Candidate
channel, and the selected Agent's cached Skill and Runtime tool schemas together.
Never restore old policy text or a cached write-capable generated-code inventory;
reload the Agent and prove the removed or newly accepted inventory. Business
instructions remain intact. Prompts cannot guarantee model obedience; eval
evidence and runtime guards are required. Hashes detect package drift, not an
attacker who can replace both installed Python code and the independent runtime
requirement.
