"""Canonical AutoGenesis Agent Contract, release 1.0.0 / schema 1."""

from .appendix import ProjectAppendix, load_project_appendix
from .contract import AgentContract, load_contract
from .errors import (
    CONTRACT_INTEGRITY_ERROR,
    CONTRACT_MISMATCH,
    PROJECT_INSTRUCTIONS_INVALID,
    ContractError,
)
from .identity import ContractIdentity, RuntimeContractRequirement
from .mcp import register_mcp

__all__ = [
    "AgentContract", "ContractIdentity", "RuntimeContractRequirement",
    "ProjectAppendix", "ContractError", "load_contract", "load_project_appendix",
    "register_mcp", "CONTRACT_MISMATCH", "CONTRACT_INTEGRITY_ERROR",
    "PROJECT_INSTRUCTIONS_INVALID",
]
