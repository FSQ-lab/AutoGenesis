# AutoGenesis Agent Contract

Canonical Python distribution `autogenesis-agent-contract`, contract `1.1.0`,
manifest schema `2`, Python >=3.10, MCP SDK >=1.23,<2. Requirement and frozen
interface: [issue #2](https://github.com/FSQ-lab/AutoGenesis/issues/2) and
[approved freeze](https://github.com/FSQ-lab/AutoGenesis/issues/2#issuecomment-6462101884).

## Consumer interface

```python
from autogenesis_agent_contract import (
    ContractIdentity, RuntimeContractRequirement, SecretRef, load_contract,
    load_project_appendix, register_mcp,
)
from mcp.server.fastmcp import FastMCP

# These pins belong to the runtime release, independently of the installed wheel.
required = RuntimeContractRequirement(
    contract_version="1.1.0",
    manifest_sha256="80266f59b8ed32c83e374c870817f018361067c0aec6b7ce2b02b8f835850462",
)
contract = load_contract(ContractIdentity(required.contract_version, required.manifest_sha256))
appendix = load_project_appendix("/absolute/business-project")
server = FastMCP("business-runtime", instructions=contract.instructions)
register_mcp(server, contract, appendix, required)
```

- `load_contract(expected_identity: ContractIdentity | None = None) -> AgentContract`
  verifies the pinned manifest and every asset before returning an immutable snapshot.
- `AgentContract.identity -> ContractIdentity` has `contract_version`,
  `manifest_sha256`, and `schema_version` (current `2`); `to_dict()` returns metadata.
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
  reference through recording, preview, confirmation, and generated code, and
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

`autogenesis://agent-contract/identity` returns contract identity plus appendix
presence, the constant relative appendix path, and its separate SHA-256. It
never returns appendix text or a user's absolute project path. Its schema is
`assets/schemas/identity.schema.json`.

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
references. This package does not detect arbitrary credentials in text. The
policy requires bounded attempts, verified ordered steps, cancellation/denial
stops, preview, and explicit approval. It does not implement automation or
runtime approval/write enforcement. Those runtime protections remain issue #8;
consumers must stop where required runtime enforcement is unavailable.

## Generated sources

Only change official assets while authoring a new unreleased contract version.
Published `1.0.0` bytes remain immutable. Contract `1.1.0` adds the versioned
SecretRef schema; later changes require a new version, schema review as appropriate,

```bash
python3 agent-contract/tools/freeze_assets.py --write
python3 agent-contract/tools/sync_skills.py
```

The first tool deterministically materializes the manifest and release pin. The
second verifies those bytes and atomically copies the two canonical thin Skills
to their owned repository paths. Neither follows output symlinks. No other
repository Skill or runtime source is changed. Skill sync uses the shared bounded
regular-file reader for manifest, pin, assets, and projection comparisons; unsafe
inputs fail before any projection is written. Read-only drift checks:

```bash
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

The package writes no project configuration and never edits the appendix. To
roll back integration, revert the consumer dependency/registration and generated
projections together, then uninstall `autogenesis-agent-contract` from that
environment. Business instructions remain intact. There is no fallback to old
policy text. Prompts cannot guarantee model obedience; eval evidence and runtime
guards are required. Hashes detect package drift, not an attacker who can replace
both installed Python code and the independent runtime requirement.
