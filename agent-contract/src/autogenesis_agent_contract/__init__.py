"""Canonical AutoGenesis Agent Contract, release 2.0.0 / schema 2."""

from .appendix import ProjectAppendix, load_project_appendix
from .contract import AgentContract, load_contract
from .errors import (
    CONTRACT_INTEGRITY_ERROR,
    CONTRACT_MISMATCH,
    PROJECT_INSTRUCTIONS_INVALID,
    ContractError,
)
from .generation import (
    GENERATION_APPROVAL_REQUIRED,
    GENERATION_DESTINATION_INVALID,
    GENERATION_PREVIEW_MISMATCH,
    GENERATION_PREVIEW_REQUIRED,
    GENERATION_PREVIEW_STALE,
    GENERATION_WRITE_FAILED,
    GenerationCommitError,
    GenerationPreview,
    commit_generation_preview,
    prepare_generation_preview,
    validate_generation_destination,
)
from .identity import ContractIdentity, RuntimeContractRequirement
from .mcp import register_mcp
from .secret_ref import (
    REDACTED, SECRET_BINDING_REQUIRED, SECRET_REFERENCE_INVALID,
    SECRET_REFERENCE_REQUIRED, SECRET_RESOLUTION_FAILED, SecretBinding,
    SecretBindings, SecretInput, SecretRef, SecretReferenceError, UnboundSecret, apply_bindings,
    contains_credential_url, credential_key, environment_reference, execution_plaintext, input_reference,
    mark_control_argument_secret, mark_secret, normalize_bindings, protect_config,
    public_view, record_arguments, require_sensitive_target, resolve,
    safe_secret_error, sanitize_result, sensitive_control, serialize,
    tool_execution, unresolved_bindings,
)

__all__ = [
    "AgentContract", "ContractIdentity", "RuntimeContractRequirement",
    "ProjectAppendix", "ContractError", "load_contract", "load_project_appendix",
    "register_mcp", "CONTRACT_MISMATCH", "CONTRACT_INTEGRITY_ERROR",
    "PROJECT_INSTRUCTIONS_INVALID", "SecretRef", "UnboundSecret", "SecretInput",
    "SecretBinding", "SecretBindings", "SecretReferenceError", "SECRET_REFERENCE_REQUIRED",
    "SECRET_BINDING_REQUIRED", "SECRET_REFERENCE_INVALID", "SECRET_RESOLUTION_FAILED",
    "REDACTED", "environment_reference", "protect_config", "resolve", "serialize",
    "public_view", "contains_credential_url", "credential_key", "sensitive_control", "tool_execution",
    "record_arguments", "mark_secret", "mark_control_argument_secret",
    "execution_plaintext", "input_reference", "require_sensitive_target",
    "safe_secret_error", "unresolved_bindings", "normalize_bindings",
    "apply_bindings", "sanitize_result", "GenerationCommitError", "GenerationPreview",
    "GENERATION_PREVIEW_REQUIRED", "GENERATION_APPROVAL_REQUIRED",
    "GENERATION_PREVIEW_MISMATCH", "GENERATION_PREVIEW_STALE",
    "GENERATION_DESTINATION_INVALID", "GENERATION_WRITE_FAILED",
    "prepare_generation_preview", "commit_generation_preview", "validate_generation_destination",
]
