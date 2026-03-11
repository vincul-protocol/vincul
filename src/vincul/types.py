"""
vincul.types — Shared domain types and dataclasses
No business logic here. Pure data definitions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


# ── Primitive type aliases ─────────────────────────────────────

Hash = str          # lowercase 64-char hex SHA-256
Timestamp = str     # ISO 8601 UTC, e.g. "2025-01-01T00:00:00Z"
UUID = str          # UUID v4 string


# ── Operation types (spec/scope/SCHEMA.md §2.1) ───────────────

class OperationType(str, Enum):
    OBSERVE = "OBSERVE"
    PROPOSE = "PROPOSE"
    COMMIT  = "COMMIT"

    @classmethod
    def ordered(cls) -> list["OperationType"]:
        return [cls.OBSERVE, cls.PROPOSE, cls.COMMIT]

    def __le__(self, other: "OperationType") -> bool:
        order = self.ordered()
        return order.index(self) <= order.index(other)

    def __lt__(self, other: "OperationType") -> bool:
        order = self.ordered()
        return order.index(self) < order.index(other)


# ── Scope status ──────────────────────────────────────────────

class ScopeStatus(str, Enum):
    ACTIVE              = "active"
    PENDING_REVOCATION  = "pending_revocation"
    REVOKED             = "revoked"
    EXPIRED             = "expired"


# ── Contract status ──────────────────────────────────────────

class ContractStatus(str, Enum):
    DRAFT     = "draft"
    ACTIVE    = "active"
    DISSOLVED = "dissolved"
    EXPIRED   = "expired"


# ── Failure codes (spec/receipts/FAILURE_CODES.md §2) ─────────

class FailureCode(str, Enum):
    # Scope-level
    SCOPE_EXPIRED               = "SCOPE_EXPIRED"
    SCOPE_REVOKED               = "SCOPE_REVOKED"
    SCOPE_EXCEEDED              = "SCOPE_EXCEEDED"
    CEILING_VIOLATED            = "CEILING_VIOLATED"
    TYPE_ESCALATION             = "TYPE_ESCALATION"
    ANCESTOR_INVALID            = "ANCESTOR_INVALID"
    SCOPE_INVALID               = "SCOPE_INVALID"           # legacy
    # Contract-level
    CONTRACT_EXPIRED            = "CONTRACT_EXPIRED"
    CONTRACT_DISSOLVED          = "CONTRACT_DISSOLVED"
    CONTRACT_NOT_ACTIVE         = "CONTRACT_NOT_ACTIVE"
    CONTRACT_INVALID            = "CONTRACT_INVALID"        # legacy
    # Delegation
    DELEGATION_UNAUTHORIZED     = "DELEGATION_UNAUTHORIZED"
    DELEGATION_MALFORMED        = "DELEGATION_MALFORMED"
    # Revocation
    REVOCATION_UNAUTHORIZED     = "REVOCATION_UNAUTHORIZED"
    REVOCATION_STATE_UNRESOLVED = "REVOCATION_STATE_UNRESOLVED"
    # Budget
    BUDGET_EXCEEDED             = "BUDGET_EXCEEDED"
    LEDGER_SNAPSHOT_FAILED      = "LEDGER_SNAPSHOT_FAILED"
    # Catch-all
    UNKNOWN                     = "UNKNOWN"


# ── Governance decision rules ─────────────────────────────────

class DecisionRule(str, Enum):
    UNANIMOUS = "unanimous"
    MAJORITY  = "majority"
    THRESHOLD = "threshold"


# ── Receipt kinds ─────────────────────────────────────────────

class ReceiptKind(str, Enum):
    DELEGATION          = "delegation"
    COMMITMENT          = "commitment"
    REVOCATION          = "revocation"
    REVERT_ATTEMPT      = "revert_attempt"
    FAILURE             = "failure"
    ATTESTATION         = "attestation"
    CONTRACT_ACTIVATION  = "contract_activation"
    CONTRACT_DISSOLUTION = "contract_dissolution"
    LEDGER_SNAPSHOT     = "ledger_snapshot"


# ── Validation result ─────────────────────────────────────────

@dataclass(frozen=True)
class ValidationResult:
    """
    Returned by vincul.validator. Either ALLOW or DENY with a failure code.
    """
    allowed: bool
    failure_code: FailureCode | None = None
    message: str | None = None
    detail: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def allow(cls) -> "ValidationResult":
        return cls(allowed=True)

    @classmethod
    def deny(
        cls,
        code: FailureCode,
        message: str,
        **detail: Any,
    ) -> "ValidationResult":
        return cls(allowed=False, failure_code=code, message=message, detail=detail)

    def __bool__(self) -> bool:
        return self.allowed


# ── Domain ────────────────────────────────────────────────────

@dataclass(frozen=True)
class Domain:
    namespace: str
    types: tuple[OperationType, ...]

    @classmethod
    def from_dict(cls, d: dict) -> "Domain":
        return cls(
            namespace=d["namespace"],
            types=tuple(OperationType(t) for t in d["types"]),
        )

    def to_dict(self) -> dict:
        return {
            "namespace": self.namespace,
            "types": [t.value for t in self.types],
        }

    def contains_namespace(self, child_namespace: str) -> bool:
        """True if this domain's namespace structurally contains child_namespace."""
        return (
            child_namespace == self.namespace
            or child_namespace.startswith(self.namespace + ".")
        )

    def contains_types(self, child_types: tuple[OperationType, ...]) -> bool:
        """True if all child_types are present in this domain's types."""
        return all(t in self.types for t in child_types)
