"""Stable, content-free diagnostics at the contract boundary."""

import json

CONTRACT_MISMATCH = "AUTOGENESIS_CONTRACT_MISMATCH"
CONTRACT_INTEGRITY_ERROR = "AUTOGENESIS_CONTRACT_INTEGRITY_ERROR"
PROJECT_INSTRUCTIONS_INVALID = "AUTOGENESIS_PROJECT_INSTRUCTIONS_INVALID"


class ContractError(ValueError):
    """Only fixed reason identifiers enter errors, never caller content."""

    def __init__(self, code: str, reason: str) -> None:
        self.code = code
        self.reason = reason
        super().__init__(json.dumps(self.to_dict(), sort_keys=True))

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "reason": self.reason}
