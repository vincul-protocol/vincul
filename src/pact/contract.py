"""
pact.contract — Coalition Contract schema, lifecycle, governance, and store
spec: spec/contract/COALITION.md

Implements:
- CoalitionContract dataclass (exact schema from spec)
- Structural validation (invariants 2, 12, 13)
- Governance signature checks (unanimous, majority, threshold)
- ContractStore: in-memory store satisfying ContractStoreProtocol

The two-store model:
  ContractStore owns contract state (draft/active/dissolved/expired).
  ReceiptLog owns the audit trail.
  Receipt emission is the caller's (runtime's) responsibility.

Depends on: pact.hashing, pact.types
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from pact.hashing import normalize_contract, pact_hash
from pact.types import (
    ContractStatus, DecisionRule, Hash, Timestamp, UUID,
)


# ── Timestamp helper ─────────────────────────────────────────

def _parse_timestamp(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ── CoalitionContract dataclass ──────────────────────────────

@dataclass
class CoalitionContract:
    """
    A Coalition Contract descriptor. All fields match COALITION.md §2.

    Nested structures (purpose, principals, governance, budget_policy,
    activation) are plain dicts to match the canonical hash format used
    by ci/check_vectors.py and pact.hashing.normalize_contract().

    descriptor_hash is set by ContractStore.put() or .seal().
    It covers all fields except itself (detached, like receipt_hash).
    """
    contract_id:    UUID
    version:        str
    purpose:        dict[str, Any]
    principals:     list[dict[str, Any]]
    governance:     dict[str, Any]
    budget_policy:  dict[str, Any]
    activation:     dict[str, Any]

    descriptor_hash: Hash | None = None

    # ── Serialization ─────────────────────────────────────────

    def _payload_for_hash(self) -> dict:
        """All fields except descriptor_hash, per HASHING.md §6."""
        return {
            "contract_id":  self.contract_id,
            "version":      self.version,
            "purpose":      self.purpose,
            "principals":   self.principals,
            "governance":   self.governance,
            "budget_policy": self.budget_policy,
            "activation":   self.activation,
        }

    def normalize(self) -> dict:
        """
        Return a normalized deep copy: principals sorted by principal_id.
        This is the form that goes into pact_hash().
        """
        return normalize_contract(self._payload_for_hash())

    def compute_hash(self) -> Hash:
        return pact_hash("contract", self.normalize())

    def seal(self) -> "CoalitionContract":
        """Compute and set descriptor_hash. Returns self for chaining."""
        self.descriptor_hash = self.compute_hash()
        return self

    def to_dict(self) -> dict:
        d = self._payload_for_hash()
        d["descriptor_hash"] = self.descriptor_hash
        return d

    def _deep_copy(self) -> "CoalitionContract":
        """Return an independent deep copy (for before-snapshots)."""
        return CoalitionContract.from_dict(json.loads(json.dumps(self.to_dict())))

    @classmethod
    def from_dict(cls, d: dict) -> "CoalitionContract":
        return cls(
            contract_id    = d["contract_id"],
            version        = d["version"],
            purpose        = d["purpose"],
            principals     = d["principals"],
            governance     = d["governance"],
            budget_policy  = d["budget_policy"],
            activation     = d["activation"],
            descriptor_hash = d.get("descriptor_hash"),
        )

    def verify_hash(self) -> bool:
        """Return True if stored descriptor_hash matches recomputed hash."""
        if not self.descriptor_hash:
            return False
        return self.compute_hash() == self.descriptor_hash

    # ── Status queries ────────────────────────────────────────

    @property
    def status(self) -> ContractStatus:
        return ContractStatus(self.activation["status"])

    def is_active(self) -> bool:
        return self.activation["status"] == ContractStatus.ACTIVE.value

    def is_dissolved(self) -> bool:
        return self.activation["status"] == ContractStatus.DISSOLVED.value

    def is_draft(self) -> bool:
        return self.activation["status"] == ContractStatus.DRAFT.value

    def is_expired_by_clock(self, at: datetime | None = None) -> bool:
        """True if purpose.expires_at is set and wall clock has passed it."""
        expires_at = self.purpose.get("expires_at")
        if expires_at is None:
            return False
        t = at or _now()
        return t >= _parse_timestamp(expires_at)

    def is_valid(self, at: datetime | None = None) -> bool:
        """
        Contract validity predicate (COALITION.md §6):
          1. activation.status == "active"
          2. purpose.expires_at is null OR t < expires_at
          3. activation.dissolved_at is null
        """
        if not self.is_active():
            return False
        if self.is_expired_by_clock(at):
            return False
        if self.activation.get("dissolved_at") is not None:
            return False
        return True

    # ── Principal helpers ─────────────────────────────────────

    def principal_ids(self) -> list[str]:
        """Sorted list of principal_id strings."""
        return sorted(p["principal_id"] for p in self.principals)

    def has_principal(self, principal_id: str) -> bool:
        return any(p["principal_id"] == principal_id for p in self.principals)

    def get_principal(self, principal_id: str) -> dict | None:
        for p in self.principals:
            if p["principal_id"] == principal_id:
                return p
        return None

    def __repr__(self) -> str:
        return (
            f"CoalitionContract(id={self.contract_id!r}, "
            f"status={self.activation['status']!r}, "
            f"principals={len(self.principals)})"
        )


# ── Structural validation ────────────────────────────────────

def validate_contract(contract: CoalitionContract) -> None:
    """
    Validate structural invariants. Raises ValueError on violation.

    Checks:
    - At least 2 principals (invariant 12)
    - purpose.title is non-empty
    - threshold rules (null/present consistency with decision_rule)
    - budget_policy consistency (dimensions null/present vs allowed flag)
    """
    # Invariant 12: minimum 2 principals
    if len(contract.principals) < 2:
        raise ValueError(
            f"Coalition requires at least 2 principals, got {len(contract.principals)}. "
            f"Single-principal contracts are malformed (invariant 12)."
        )

    # Unique principal IDs
    pids = [p["principal_id"] for p in contract.principals]
    if len(pids) != len(set(pids)):
        raise ValueError("Duplicate principal_id values in contract.")

    # Purpose title non-empty
    title = contract.purpose.get("title", "")
    if not title or not title.strip():
        raise ValueError("Contract purpose.title must be non-empty.")

    # Governance threshold rules
    gov = contract.governance
    rule = gov.get("decision_rule")
    threshold = gov.get("threshold")

    if rule not in (r.value for r in DecisionRule):
        raise ValueError(f"Unknown decision_rule: {rule!r}")

    if rule == DecisionRule.THRESHOLD.value:
        if threshold is None:
            raise ValueError(
                "governance.threshold must be set when decision_rule is 'threshold'."
            )
        if not isinstance(threshold, int) or threshold <= 0:
            raise ValueError(
                f"governance.threshold must be a positive integer, got {threshold!r}."
            )
        if threshold > len(contract.principals):
            raise ValueError(
                f"governance.threshold ({threshold}) exceeds number of "
                f"principals ({len(contract.principals)})."
            )
    else:
        if threshold is not None:
            raise ValueError(
                f"governance.threshold must be null when decision_rule is {rule!r}."
            )

    # Budget policy consistency
    bp = contract.budget_policy
    allowed = bp.get("allowed", False)
    dimensions = bp.get("dimensions")

    if allowed:
        if dimensions is None or len(dimensions) == 0:
            raise ValueError(
                "budget_policy.dimensions must be non-empty when budget is allowed."
            )
    else:
        if dimensions is not None:
            raise ValueError(
                "budget_policy.dimensions must be null when budget is not allowed."
            )


# ── Governance signature check ───────────────────────────────

def check_governance(
    contract: CoalitionContract,
    signatures: list[str],
) -> bool:
    """
    Check if signatures satisfy the governance decision_rule.

    signatures: list of principal_id strings that have signed.
    Only principals listed in the contract count (invariant 9).
    Each principal counts at most once regardless of duplicates.

    Returns True if governance requirement is met.
    """
    contract_pids = {p["principal_id"] for p in contract.principals}
    qualifying = contract_pids & set(signatures)

    rule = contract.governance["decision_rule"]
    threshold = contract.governance.get("threshold")
    total = len(contract.principals)

    if rule == DecisionRule.UNANIMOUS.value:
        return len(qualifying) == total
    elif rule == DecisionRule.MAJORITY.value:
        return len(qualifying) > total / 2
    elif rule == DecisionRule.THRESHOLD.value:
        return len(qualifying) >= threshold
    else:
        return False


# ── ContractStore ────────────────────────────────────────────

class ContractStore:
    """
    In-memory coalition contract store.

    Source of truth for contract state. Receipt emission is the
    caller's responsibility — the store is deterministic state only.

    Satisfies ContractStoreProtocol from pact.interfaces.
    """

    def __init__(self) -> None:
        self._contracts: dict[UUID, CoalitionContract] = {}
        self._by_hash:   dict[Hash, UUID] = {}

    # ── Put ───────────────────────────────────────────────────

    def put(self, contract: CoalitionContract) -> CoalitionContract:
        """
        Store a contract. Validates structure, seals, and indexes.
        Raises ValueError on duplicate contract_id or structural violation.
        """
        if contract.contract_id in self._contracts:
            raise ValueError(f"Duplicate contract_id: {contract.contract_id!r}")

        validate_contract(contract)

        if contract.descriptor_hash is None:
            contract.seal()

        self._contracts[contract.contract_id] = contract
        self._by_hash[contract.descriptor_hash] = contract.contract_id
        return contract

    # ── Get ───────────────────────────────────────────────────

    def get(self, contract_id: UUID) -> CoalitionContract | None:
        return self._contracts.get(contract_id)

    def get_or_raise(self, contract_id: UUID) -> CoalitionContract:
        c = self._contracts.get(contract_id)
        if c is None:
            raise KeyError(f"Contract {contract_id!r} not found in store.")
        return c

    def get_by_hash(self, contract_hash: Hash) -> CoalitionContract | None:
        cid = self._by_hash.get(contract_hash)
        if cid is None:
            return None
        return self._contracts.get(cid)

    # ── Activate ──────────────────────────────────────────────

    def activate(
        self,
        contract_id: UUID,
        activated_at: Timestamp,
        signatures: list[str],
    ) -> tuple[CoalitionContract, CoalitionContract]:
        """
        Transition draft → active.

        Returns (contract_before, contract_after).
        contract_before is a deep copy snapshot of the prior state.

        Raises ValueError if:
        - Contract not found
        - Contract is not in draft status
        - Signatures do not satisfy governance.decision_rule
        """
        contract = self.get_or_raise(contract_id)

        if not contract.is_draft():
            raise ValueError(
                f"Cannot activate contract {contract_id!r}: "
                f"status is {contract.activation['status']!r}, expected 'draft'."
            )

        if not check_governance(contract, signatures):
            raise ValueError(
                f"Cannot activate contract {contract_id!r}: "
                f"signatures do not satisfy governance rule "
                f"({contract.governance['decision_rule']})."
            )

        # Snapshot before state (deep copy — shares no mutable dicts)
        before = contract._deep_copy()

        # Remove old hash from index
        if contract.descriptor_hash in self._by_hash:
            del self._by_hash[contract.descriptor_hash]

        # Mutate
        contract.activation["status"] = ContractStatus.ACTIVE.value
        contract.activation["activated_at"] = activated_at
        contract.seal()

        # Update hash index
        self._by_hash[contract.descriptor_hash] = contract.contract_id

        return before, contract

    # ── Dissolve ──────────────────────────────────────────────

    def dissolve(
        self,
        contract_id: UUID,
        dissolved_at: Timestamp,
        dissolved_by: str,
        signatures: list[str],
    ) -> tuple[CoalitionContract, CoalitionContract]:
        """
        Transition active → dissolved.

        Returns (contract_before, contract_after).
        contract_before is a deep copy snapshot of the prior state.

        Raises ValueError if:
        - Contract not found
        - Contract is not in active status
        - Signatures do not satisfy governance.decision_rule
        """
        contract = self.get_or_raise(contract_id)

        if not contract.is_active():
            raise ValueError(
                f"Cannot dissolve contract {contract_id!r}: "
                f"status is {contract.activation['status']!r}, expected 'active'."
            )

        if not check_governance(contract, signatures):
            raise ValueError(
                f"Cannot dissolve contract {contract_id!r}: "
                f"signatures do not satisfy governance rule "
                f"({contract.governance['decision_rule']})."
            )

        # Snapshot before state (deep copy — shares no mutable dicts)
        before = contract._deep_copy()

        # Remove old hash from index
        if contract.descriptor_hash in self._by_hash:
            del self._by_hash[contract.descriptor_hash]

        # Mutate
        contract.activation["status"] = ContractStatus.DISSOLVED.value
        contract.activation["dissolved_at"] = dissolved_at
        contract.seal()

        # Update hash index
        self._by_hash[contract.descriptor_hash] = contract.contract_id

        return before, contract

    # ── Status queries ────────────────────────────────────────

    def is_active(self, contract_id: UUID) -> bool:
        c = self._contracts.get(contract_id)
        return c is not None and c.is_active()

    def is_dissolved(self, contract_id: UUID) -> bool:
        c = self._contracts.get(contract_id)
        return c is not None and c.is_dissolved()

    # ── Metrics ───────────────────────────────────────────────

    def __len__(self) -> int:
        return len(self._contracts)

    def __contains__(self, contract_id: UUID) -> bool:
        return contract_id in self._contracts
