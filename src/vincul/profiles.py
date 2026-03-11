"""
vincul.profiles — Compliance Profile schema, validation, and store
spec: spec/implementation/COMPLIANCE_PROFILES.md

Implements:
- ComplianceProfile dataclass (exact schema from spec §2)
- Structural validation (max_constraint_atoms ≤ 64, max_constraint_nesting_depth ≤ 8)
- ProfileStore: in-memory store indexed by profile_id and descriptor_hash

Depends on: vincul.hashing, vincul.types
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from vincul.hashing import normalize_profile, vincul_hash
from vincul.types import Hash


# ── ComplianceProfile dataclass ──────────────────────────────

@dataclass
class ComplianceProfile:
    """
    A Compliance Profile descriptor. All fields match COMPLIANCE_PROFILES.md §2.

    Nested structures (implementation, bounds) are plain dicts to match
    the canonical hash format used by ci/check_vectors.py and
    vincul.hashing.normalize_profile().

    descriptor_hash is set by ProfileStore.put() or .seal().
    It covers all fields except itself (detached, like contract descriptor_hash).
    """
    profile_id:               str
    protocol_version:         str
    implementation:           dict[str, Any]
    bounds:                   dict[str, Any]
    supported_receipt_kinds:  list[str]
    supported_failure_codes:  list[str]
    signature_algorithms:     list[str]
    attestation_schemas:      list[str] | None

    descriptor_hash: Hash | None = None

    # ── Serialization ─────────────────────────────────────────

    def _payload_for_hash(self) -> dict:
        """All fields except descriptor_hash, per HASHING.md §6."""
        return {
            "profile_id":              self.profile_id,
            "protocol_version":        self.protocol_version,
            "implementation":          self.implementation,
            "bounds":                  self.bounds,
            "supported_receipt_kinds": self.supported_receipt_kinds,
            "supported_failure_codes": self.supported_failure_codes,
            "signature_algorithms":    self.signature_algorithms,
            "attestation_schemas":     self.attestation_schemas,
        }

    def normalize(self) -> dict:
        """
        Return a normalized deep copy: set-like arrays sorted lexicographically.
        This is the form that goes into vincul_hash().
        """
        return normalize_profile(self._payload_for_hash())

    def compute_hash(self) -> Hash:
        return vincul_hash("profile", self.normalize())

    def seal(self) -> "ComplianceProfile":
        """Compute and set descriptor_hash. Raises if already sealed.

        Not thread-safe: the check-then-set is not atomic. Concurrent
        callers could both pass the guard. This is acceptable because
        seal() is deterministic (same fields → same hash) and Vincul
        stores have no thread-safety guarantees. Callers needing
        concurrency must synchronize externally.
        """
        if self.descriptor_hash is not None:
            raise RuntimeError("ComplianceProfile already sealed")
        self.descriptor_hash = self.compute_hash()
        return self

    def to_dict(self) -> dict:
        d = self._payload_for_hash()
        d["descriptor_hash"] = self.descriptor_hash
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "ComplianceProfile":
        return cls(
            profile_id              = d["profile_id"],
            protocol_version        = d["protocol_version"],
            implementation          = d["implementation"],
            bounds                  = d["bounds"],
            supported_receipt_kinds = d["supported_receipt_kinds"],
            supported_failure_codes = d["supported_failure_codes"],
            signature_algorithms    = d["signature_algorithms"],
            attestation_schemas     = d.get("attestation_schemas"),
            descriptor_hash         = d.get("descriptor_hash"),
        )

    def verify_hash(self) -> bool:
        """Return True if stored descriptor_hash matches recomputed hash."""
        if not self.descriptor_hash:
            return False
        return self.compute_hash() == self.descriptor_hash

    def __repr__(self) -> str:
        return (
            f"ComplianceProfile(id={self.profile_id!r}, "
            f"protocol={self.protocol_version!r})"
        )


# ── Structural validation ────────────────────────────────────

PROTOCOL_MAX_CONSTRAINT_ATOMS = 64
PROTOCOL_MAX_CONSTRAINT_NESTING_DEPTH = 8


def validate_profile(profile: ComplianceProfile) -> None:
    """
    Validate structural invariants. Raises ValueError on violation.

    Checks (COMPLIANCE_PROFILES.md §3.3):
    - max_constraint_atoms must be ≤ 64
    - max_constraint_nesting_depth must be ≤ 8
    """
    atoms = profile.bounds.get("max_constraint_atoms")
    if atoms is not None and atoms > PROTOCOL_MAX_CONSTRAINT_ATOMS:
        raise ValueError(
            f"max_constraint_atoms ({atoms}) exceeds protocol maximum "
            f"({PROTOCOL_MAX_CONSTRAINT_ATOMS}). "
            f"Implementations may not declare looser bounds than the protocol allows."
        )

    depth = profile.bounds.get("max_constraint_nesting_depth")
    if depth is not None and depth > PROTOCOL_MAX_CONSTRAINT_NESTING_DEPTH:
        raise ValueError(
            f"max_constraint_nesting_depth ({depth}) exceeds protocol maximum "
            f"({PROTOCOL_MAX_CONSTRAINT_NESTING_DEPTH}). "
            f"Implementations may not declare looser bounds than the protocol allows."
        )


# ── Coalition interoperability (§4) ──────────────────────────

def effective_bound(
    profiles: list[ComplianceProfile],
    bound_name: str,
) -> int | None:
    """
    Compute the effective bound across coalition participants (§4).
    The most restrictive declared bound governs. null does not override
    a declared bound.

    Returns None only if all profiles declare null for this bound.
    """
    values = [
        p.bounds.get(bound_name)
        for p in profiles
        if p.bounds.get(bound_name) is not None
    ]
    if not values:
        return None
    return min(values)


# ── ProfileStore ─────────────────────────────────────────────

class ProfileStore:
    """
    In-memory compliance profile store.
    Indexed by profile_id and descriptor_hash.
    """

    def __init__(self) -> None:
        self._profiles: dict[str, ComplianceProfile] = {}
        self._by_hash:  dict[Hash, str] = {}

    def put(self, profile: ComplianceProfile) -> ComplianceProfile:
        """
        Store a profile. Validates structure, seals, and indexes.
        Raises ValueError on duplicate profile_id or structural violation.
        """
        if profile.profile_id in self._profiles:
            raise ValueError(f"Duplicate profile_id: {profile.profile_id!r}")

        validate_profile(profile)

        if profile.descriptor_hash is None:
            profile.seal()

        self._profiles[profile.profile_id] = profile
        self._by_hash[profile.descriptor_hash] = profile.profile_id
        return profile

    def get(self, profile_id: str) -> ComplianceProfile | None:
        return self._profiles.get(profile_id)

    def get_by_hash(self, profile_hash: Hash) -> ComplianceProfile | None:
        pid = self._by_hash.get(profile_hash)
        if pid is None:
            return None
        return self._profiles.get(pid)

    def __len__(self) -> int:
        return len(self._profiles)

    def __contains__(self, profile_id: str) -> bool:
        return profile_id in self._profiles
