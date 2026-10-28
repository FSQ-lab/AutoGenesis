"""Exact compatibility requirements; no ranges or legacy fallback."""

import re
from dataclasses import asdict, dataclass

from .errors import CONTRACT_MISMATCH, ContractError


def _validate(version: str, digest: str) -> None:
    if (
        not isinstance(version, str)
        or re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version) is None
        or not isinstance(digest, str)
        or re.fullmatch(r"[0-9a-f]{64}", digest) is None
    ):
        raise ContractError(CONTRACT_MISMATCH, "invalid_identity")


@dataclass(frozen=True, slots=True)
class ContractIdentity:
    contract_version: str
    manifest_sha256: str
    schema_version: int = 1

    def __post_init__(self) -> None:
        _validate(self.contract_version, self.manifest_sha256)
        if type(self.schema_version) is not int or self.schema_version < 1:
            raise ContractError(CONTRACT_MISMATCH, "invalid_identity")

    def to_dict(self) -> dict[str, str | int]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class RuntimeContractRequirement:
    contract_version: str
    manifest_sha256: str

    def __post_init__(self) -> None:
        _validate(self.contract_version, self.manifest_sha256)

    def matches(self, identity: ContractIdentity) -> bool:
        return (self.contract_version, self.manifest_sha256) == (
            identity.contract_version, identity.manifest_sha256
        )
