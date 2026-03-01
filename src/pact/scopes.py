"""
pact.scopes — Scope DAG store, delegation validation, revocation cascade
spec: spec/scope/SCHEMA.md, spec/revocation/SEMANTICS.md

The scope engine is the enforcement backbone. It answers two questions:
  1. Is this scope currently valid? (validity predicate, §5.2)
  2. Is this delegation structurally sound? (delegation constraints, §7)

It also executes revocation cascade (SEMANTICS.md §4) and maintains
the parent-pointer DAG that makes both of the above locally decidable.

Depends on: pact.hashing, pact.types
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterator

from pact.hashing import pact_hash, normalize_contract
from pact.types import (
    Domain, FailureCode, Hash, OperationType,
    ScopeStatus, Timestamp, UUID, ValidationResult,
)


# ── Scope descriptor ──────────────────────────────────────────

@dataclass
class Scope:
    """
    A Pact Scope descriptor.  All fields map directly to SCHEMA.md §6.

    `descriptor_hash` is set by ScopeStore.add() after structural validation.
    It covers all fields except itself (detached, like receipt_hash).
    """
    id:                  UUID
    issued_by_scope_id:  UUID | None          # None for root scopes
    issued_by:           str                  # principal_id or contract_id
    issued_at:           Timestamp
    expires_at:          Timestamp | None

    domain:              Domain
    predicate:           str                  # ConstraintExpression string
    ceiling:             str                  # ConstraintExpression string

    delegate:            bool                 # never implied; default False
    revoke:              str                  # "principal_only" | "coalition_if_granted"

    status:              ScopeStatus = ScopeStatus.ACTIVE
    effective_at:        Timestamp | None = None   # set when pending_revocation

    descriptor_hash:     Hash | None = None   # set after construction

    # ── Serialization ─────────────────────────────────────────

    def _payload_for_hash(self) -> dict:
        """All fields except descriptor_hash, per HASHING.md §6.1."""
        return {
            "id":                 self.id,
            "issued_by_scope_id": self.issued_by_scope_id,
            "issued_by":          self.issued_by,
            "issued_at":          self.issued_at,
            "expires_at":         self.expires_at,
            "domain":             self.domain.to_dict(),
            "predicate":          self.predicate,
            "ceiling":            self.ceiling,
            "delegate":           self.delegate,
            "revoke":             self.revoke,
            "status":             self.status.value,
            "effective_at":       self.effective_at,
        }

    def compute_hash(self) -> Hash:
        return pact_hash("scope", self._payload_for_hash())

    def seal(self) -> "Scope":
        """Compute and set descriptor_hash. Returns self for chaining."""
        self.descriptor_hash = self.compute_hash()
        return self

    def to_dict(self) -> dict:
        d = self._payload_for_hash()
        d["descriptor_hash"] = self.descriptor_hash
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Scope":
        return cls(
            id                 = d["id"],
            issued_by_scope_id = d["issued_by_scope_id"],
            issued_by          = d["issued_by"],
            issued_at          = d["issued_at"],
            expires_at         = d.get("expires_at"),
            domain             = Domain.from_dict(d["domain"]),
            predicate          = d["predicate"],
            ceiling            = d["ceiling"],
            delegate           = d["delegate"],
            revoke             = d["revoke"],
            status             = ScopeStatus(d.get("status", "active")),
            effective_at       = d.get("effective_at"),
            descriptor_hash    = d.get("descriptor_hash"),
        )

    def is_root(self) -> bool:
        return self.issued_by_scope_id is None

    def __repr__(self) -> str:
        return (
            f"Scope(id={self.id!r}, ns={self.domain.namespace!r}, "
            f"types={[t.value for t in self.domain.types]}, status={self.status.value!r})"
        )


# ── Delegation validation ─────────────────────────────────────

class DelegationValidator:
    """
    Stateless validator for delegation constraints (SCHEMA.md §7).
    Given parent and proposed child scope descriptors, returns
    ValidationResult(allow) or ValidationResult(deny, code, message).

    All checks are locally decidable — no DAG traversal required here.
    DAG integrity (cycle detection, depth limits) is enforced by ScopeStore.
    """

    @staticmethod
    def validate(parent: Scope, child: Scope) -> ValidationResult:
        """
        Run all delegation constraint checks in precedence order.
        First failure wins — returns immediately with the relevant code.
        """
        checks = [
            DelegationValidator._check_parent_status,
            DelegationValidator._check_type_containment,
            DelegationValidator._check_namespace_containment,
            DelegationValidator._check_ceiling_containment,
            DelegationValidator._check_predicate_within_ceiling,
            DelegationValidator._check_delegate_gate,
            DelegationValidator._check_revoke_gate,
        ]
        for check in checks:
            result = check(parent, child)
            if not result:
                return result
        return ValidationResult.allow()

    # ── Individual checks ─────────────────────────────────────

    @staticmethod
    def _check_parent_status(parent: Scope, child: Scope) -> ValidationResult:
        """
        Parent must be active. pending_revocation blocks delegation.
        (SCHEMA.md §7, status gate; SEMANTICS.md §5.2)
        """
        if parent.status == ScopeStatus.ACTIVE:
            return ValidationResult.allow()
        if parent.status == ScopeStatus.PENDING_REVOCATION:
            return ValidationResult.deny(
                FailureCode.DELEGATION_MALFORMED,
                f"Parent scope {parent.id!r} is pending revocation and may not issue child scopes.",
                parent_scope_id=parent.id,
                parent_status=parent.status.value,
            )
        return ValidationResult.deny(
            FailureCode.DELEGATION_MALFORMED,
            f"Parent scope {parent.id!r} is {parent.status.value!r} and cannot delegate.",
            parent_scope_id=parent.id,
            parent_status=parent.status.value,
        )

    @staticmethod
    def _check_type_containment(parent: Scope, child: Scope) -> ValidationResult:
        """
        child.domain.types ⊆ parent.domain.types  (SCHEMA.md §7)
        Also validates contiguity of child types.
        """
        # Validate contiguous prefix first
        result = DelegationValidator._validate_type_contiguity(child.domain.types)
        if not result:
            return result

        parent_types = set(parent.domain.types)
        child_types = set(child.domain.types)
        excess = child_types - parent_types
        if excess:
            return ValidationResult.deny(
                FailureCode.TYPE_ESCALATION,
                f"Child scope requests types {[t.value for t in excess]} "
                f"not held by parent scope {parent.id!r}.",
                parent_types=[t.value for t in parent.domain.types],
                child_types=[t.value for t in child.domain.types],
                excess_types=[t.value for t in excess],
            )
        return ValidationResult.allow()

    @staticmethod
    def _validate_type_contiguity(types: tuple[OperationType, ...]) -> ValidationResult:
        """
        Types must form a contiguous prefix of OBSERVE < PROPOSE < COMMIT.
        (SCHEMA.md §1.2)
        """
        if not types:
            return ValidationResult.deny(
                FailureCode.DELEGATION_MALFORMED,
                "Scope must declare at least one operation type.",
            )
        ordered = OperationType.ordered()
        type_set = set(types)
        # Must be {ordered[0]}, {ordered[0], ordered[1]}, or all three
        for i in range(len(ordered)):
            if type_set == set(ordered[:i+1]):
                return ValidationResult.allow()
        return ValidationResult.deny(
            FailureCode.DELEGATION_MALFORMED,
            f"Operation types {[t.value for t in types]} are not a contiguous prefix "
            f"of OBSERVE < PROPOSE < COMMIT.",
            types=[t.value for t in types],
        )

    @staticmethod
    def _check_namespace_containment(parent: Scope, child: Scope) -> ValidationResult:
        """
        child namespace must be within parent namespace coverage.
        (SCHEMA.md §2.2: B == A OR B starts with A + ".")
        """
        if not parent.domain.contains_namespace(child.domain.namespace):
            return ValidationResult.deny(
                FailureCode.DELEGATION_MALFORMED,
                f"Child namespace {child.domain.namespace!r} is not within "
                f"parent namespace {parent.domain.namespace!r}.",
                parent_namespace=parent.domain.namespace,
                child_namespace=child.domain.namespace,
            )
        return ValidationResult.allow()

    @staticmethod
    def _check_ceiling_containment(parent: Scope, child: Scope) -> ValidationResult:
        """
        child.ceiling ⊆ parent.ceiling  (SCHEMA.md §3, §7)

        In v0.2 without a full DSL evaluator, we enforce:
        - If parent.ceiling == "TOP", anything is allowed (TOP is universal)
        - If child.ceiling == "TOP" but parent.ceiling != "TOP": violation
        - If parent.ceiling == child.ceiling: allowed (equal is contained)
        - Otherwise: flag for DSL evaluator (not yet implemented; allow with note)

        The constraint DSL evaluator (pact.constraints) will provide full
        subset checking in a subsequent implementation step.
        """
        if parent.ceiling == "TOP":
            return ValidationResult.allow()
        if child.ceiling == "TOP" and parent.ceiling != "TOP":
            return ValidationResult.deny(
                FailureCode.CEILING_VIOLATED,
                f"Child ceiling 'TOP' exceeds parent ceiling {parent.ceiling!r}.",
                parent_ceiling=parent.ceiling,
                child_ceiling=child.ceiling,
            )
        # Equal ceilings are always contained
        if child.ceiling == parent.ceiling:
            return ValidationResult.allow()
        # Non-trivial subset check deferred to pact.constraints
        # (allowed here; full DSL eval enforces at action time)
        return ValidationResult.allow()

    @staticmethod
    def _check_predicate_within_ceiling(parent: Scope, child: Scope) -> ValidationResult:
        """
        child.predicate ⊆ child.ceiling  (SCHEMA.md §3)

        BOTTOM predicate is always valid (permits nothing).
        TOP predicate requires TOP ceiling.
        """
        if child.predicate == "BOTTOM":
            return ValidationResult.allow()
        if child.predicate == "TOP" and child.ceiling != "TOP":
            return ValidationResult.deny(
                FailureCode.DELEGATION_MALFORMED,
                f"Child predicate 'TOP' exceeds child ceiling {child.ceiling!r}.",
                child_predicate=child.predicate,
                child_ceiling=child.ceiling,
            )
        return ValidationResult.allow()

    @staticmethod
    def _check_delegate_gate(parent: Scope, child: Scope) -> ValidationResult:
        """
        child.delegate = True only if parent.delegate = True.
        (SCHEMA.md §1.3, §7: delegate is never implied)
        """
        if child.delegate and not parent.delegate:
            return ValidationResult.deny(
                FailureCode.DELEGATION_UNAUTHORIZED,
                f"Parent scope {parent.id!r} does not carry delegate=true; "
                f"child may not be issued with delegate=true.",
                parent_delegate=parent.delegate,
            )
        return ValidationResult.allow()

    @staticmethod
    def _check_revoke_gate(parent: Scope, child: Scope) -> ValidationResult:
        """
        child.revoke = "coalition_if_granted" only if parent explicitly carries it.
        (SCHEMA.md §1.3)
        """
        if (child.revoke == "coalition_if_granted"
                and parent.revoke != "coalition_if_granted"):
            return ValidationResult.deny(
                FailureCode.DELEGATION_UNAUTHORIZED,
                f"Parent scope {parent.id!r} does not carry coalition_if_granted revoke; "
                f"child may not claim it.",
                parent_revoke=parent.revoke,
            )
        return ValidationResult.allow()


# ── Scope validity ────────────────────────────────────────────

def _parse_timestamp(ts: str) -> datetime:
    """Parse ISO 8601 UTC timestamp to aware datetime."""
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _now() -> datetime:
    return datetime.now(timezone.utc)


def check_scope_validity(
    scope: Scope,
    at: datetime | None = None,
    contract_dissolved: bool = False,
    contract_expired: bool = False,
) -> ValidationResult:
    """
    Evaluate the validity predicate (SCHEMA.md §5.2) for a single scope,
    without DAG traversal. Ancestor checking is the caller's responsibility
    (ScopeStore.validate_scope does the full check).

    Conditions checked here (1, 2, 4, 5):
      1. status ∈ {active, pending_revocation} and if pending, t < effective_at
      2. scope not directly revoked
      4. governing contract not dissolved
      5. t < expires_at (or expires_at is null)

    Condition 3 (no ancestor revoked) requires DAG traversal — handled by ScopeStore.
    """
    t = at or _now()

    # Condition 4: contract validity
    if contract_dissolved:
        return ValidationResult.deny(
            FailureCode.CONTRACT_DISSOLVED,
            "The governing Coalition Contract has been dissolved.",
        )
    if contract_expired:
        return ValidationResult.deny(
            FailureCode.CONTRACT_EXPIRED,
            "The governing Coalition Contract has expired.",
        )

    # Condition 2: directly revoked
    if scope.status == ScopeStatus.REVOKED:
        return ValidationResult.deny(
            FailureCode.SCOPE_REVOKED,
            f"Scope {scope.id!r} has been revoked.",
            scope_id=scope.id,
        )

    # Condition 1a: expired status
    if scope.status == ScopeStatus.EXPIRED:
        return ValidationResult.deny(
            FailureCode.SCOPE_EXPIRED,
            f"Scope {scope.id!r} has expired.",
            scope_id=scope.id,
        )

    # Condition 5: expires_at wall clock
    if scope.expires_at is not None:
        expires = _parse_timestamp(scope.expires_at)
        if t >= expires:
            return ValidationResult.deny(
                FailureCode.SCOPE_EXPIRED,
                f"Scope {scope.id!r} expired at {scope.expires_at}.",
                scope_id=scope.id,
                expires_at=scope.expires_at,
            )

    # Condition 1b: pending_revocation window
    if scope.status == ScopeStatus.PENDING_REVOCATION:
        if scope.effective_at is None:
            # Malformed pending_revocation — treat as revoked (fail closed)
            return ValidationResult.deny(
                FailureCode.SCOPE_REVOKED,
                f"Scope {scope.id!r} is pending revocation with no effective_at; "
                f"treating as revoked (fail closed).",
                scope_id=scope.id,
            )
        effective = _parse_timestamp(scope.effective_at)
        if t >= effective:
            return ValidationResult.deny(
                FailureCode.SCOPE_REVOKED,
                f"Scope {scope.id!r} revocation became effective at {scope.effective_at}.",
                scope_id=scope.id,
                effective_at=scope.effective_at,
            )
        # Still within pending window — valid for actions, not for delegation
        return ValidationResult.allow()

    # Must be active
    if scope.status != ScopeStatus.ACTIVE:
        return ValidationResult.deny(
            FailureCode.SCOPE_INVALID,
            f"Scope {scope.id!r} has unexpected status {scope.status.value!r}.",
            scope_id=scope.id,
            status=scope.status.value,
        )

    return ValidationResult.allow()


# ── ScopeStore: the DAG ───────────────────────────────────────

class ScopeStore:
    """
    In-memory scope DAG store.

    Responsibilities:
    - Store scope descriptors indexed by scope_id
    - Maintain parent-pointer index for DAG traversal
    - Enforce structural invariants on add (cycle detection, depth limit)
    - Evaluate the full validity predicate including ancestor traversal
    - Execute revocation cascade

    All state transitions are append-friendly: revocation marks status,
    it never removes scope descriptors. The full history is always visible.

    In production: back with persistent storage.
    The public API surface is stable regardless of storage backend.
    """

    MAX_DEPTH: int = 10   # compliance profile default; overridable at construction

    def __init__(self, max_depth: int = MAX_DEPTH) -> None:
        self._scopes:   dict[UUID, Scope] = {}
        self._children: dict[UUID, list[UUID]] = {}  # parent_id → [child_id, ...]
        self._max_depth = max_depth

    # ── Add ───────────────────────────────────────────────────

    def add(self, scope: Scope) -> Scope:
        """
        Add a scope to the store.

        Validates:
        - No duplicate scope_id
        - Type contiguity
        - Parent exists (if not root)
        - No cycle
        - Depth within max_depth
        - Seals descriptor_hash if not already set

        Does NOT validate delegation constraints (parent/child relationship).
        Call DelegationValidator.validate(parent, child) before add().
        """
        if scope.id in self._scopes:
            raise ValueError(f"Duplicate scope id: {scope.id!r}")

        # Validate type contiguity
        result = DelegationValidator._validate_type_contiguity(scope.domain.types)
        if not result:
            raise ValueError(f"Malformed scope types: {result.message}")

        # Validate parent exists (if not root)
        if scope.issued_by_scope_id is not None:
            if scope.issued_by_scope_id not in self._scopes:
                raise ValueError(
                    f"Parent scope {scope.issued_by_scope_id!r} not found in store. "
                    f"Add parent before child."
                )

        # Cycle detection via ancestor walk
        depth = self._check_no_cycle_and_get_depth(scope)
        if depth > self._max_depth:
            raise ValueError(
                f"Scope {scope.id!r} would be at depth {depth}, "
                f"exceeding max_depth={self._max_depth}. "
                f"Declared in compliance profile."
            )

        # Seal if needed
        if scope.descriptor_hash is None:
            scope.seal()

        # Register
        self._scopes[scope.id] = scope
        if scope.issued_by_scope_id is not None:
            self._children.setdefault(scope.issued_by_scope_id, []).append(scope.id)

        return scope

    def _check_no_cycle_and_get_depth(self, scope: Scope) -> int:
        """
        Walk ancestor chain to detect cycles and measure depth.
        Returns depth (root = 0).
        Raises ValueError on cycle.
        """
        depth = 0
        visited: set[UUID] = {scope.id}
        current_id = scope.issued_by_scope_id

        while current_id is not None:
            if current_id in visited:
                raise ValueError(
                    f"Cycle detected in delegation DAG at scope {current_id!r}."
                )
            visited.add(current_id)
            depth += 1
            parent = self._scopes.get(current_id)
            if parent is None:
                # Parent not in store — add() will catch this above, but be safe
                break
            current_id = parent.issued_by_scope_id

        return depth

    # ── Retrieve ──────────────────────────────────────────────

    def get(self, scope_id: UUID) -> Scope | None:
        return self._scopes.get(scope_id)

    def get_or_raise(self, scope_id: UUID) -> Scope:
        scope = self._scopes.get(scope_id)
        if scope is None:
            raise KeyError(f"Scope {scope_id!r} not found in store.")
        return scope

    def children_of(self, scope_id: UUID) -> list[Scope]:
        """Direct children of a scope."""
        return [self._scopes[cid] for cid in self._children.get(scope_id, [])]

    def ancestors_of(self, scope_id: UUID) -> list[Scope]:
        """
        All ancestors from immediate parent to root, in order.
        O(depth) — bounded by max_depth.
        """
        ancestors = []
        scope = self._scopes.get(scope_id)
        if scope is None:
            return ancestors
        current_id = scope.issued_by_scope_id
        while current_id is not None:
            ancestor = self._scopes.get(current_id)
            if ancestor is None:
                break
            ancestors.append(ancestor)
            current_id = ancestor.issued_by_scope_id
        return ancestors

    def subtree_of(self, scope_id: UUID) -> list[Scope]:
        """
        All descendants (transitive children), including the scope itself.
        BFS traversal. Used for revocation cascade.
        """
        result = []
        queue = [scope_id]
        while queue:
            current = queue.pop(0)
            scope = self._scopes.get(current)
            if scope is not None:
                result.append(scope)
                queue.extend(self._children.get(current, []))
        return result

    def __len__(self) -> int:
        return len(self._scopes)

    def __contains__(self, scope_id: UUID) -> bool:
        return scope_id in self._scopes

    # ── Full validity check (including ancestor traversal) ────

    def validate_scope(
        self,
        scope_id: UUID,
        at: datetime | None = None,
        contract_dissolved: bool = False,
        contract_expired: bool = False,
        resolution_deadline_ms: int | None = 5000,
    ) -> ValidationResult:
        """
        Full validity predicate per SCHEMA.md §5.2 — all five conditions.

        Condition 3 (ancestor revoked) requires DAG traversal.
        Fail-closed: if the scope is not in the store, deny.

        resolution_deadline_ms: not enforced here (in-process store is always
        immediate); included in signature for compliance profile alignment.
        Async/distributed implementations should enforce this bound.
        """
        scope = self._scopes.get(scope_id)
        if scope is None:
            return ValidationResult.deny(
                FailureCode.SCOPE_INVALID,
                f"Scope {scope_id!r} not found. Failing closed.",
                scope_id=scope_id,
            )

        # Conditions 1, 2, 4, 5
        result = check_scope_validity(
            scope, at=at,
            contract_dissolved=contract_dissolved,
            contract_expired=contract_expired,
        )
        if not result:
            return result

        # Condition 3: ancestor revoked (O(depth), bounded by max_depth)
        for ancestor in self.ancestors_of(scope_id):
            if ancestor.status == ScopeStatus.REVOKED:
                return ValidationResult.deny(
                    FailureCode.ANCESTOR_INVALID,
                    f"Ancestor scope {ancestor.id!r} of {scope_id!r} has been revoked.",
                    scope_id=scope_id,
                    ancestor_scope_id=ancestor.id,
                    ancestor_error_code=FailureCode.SCOPE_REVOKED.value,
                )
            if ancestor.status == ScopeStatus.EXPIRED:
                return ValidationResult.deny(
                    FailureCode.ANCESTOR_INVALID,
                    f"Ancestor scope {ancestor.id!r} of {scope_id!r} has expired.",
                    scope_id=scope_id,
                    ancestor_scope_id=ancestor.id,
                    ancestor_error_code=FailureCode.SCOPE_EXPIRED.value,
                )

        return ValidationResult.allow()

    # ── Revocation ────────────────────────────────────────────

    def revoke(
        self,
        scope_id: UUID,
        effective_at: datetime | None = None,
        initiated_by: str = "",
    ) -> "RevocationResult":
        """
        Revoke a scope and cascade to all descendants.
        (SEMANTICS.md §4.1: cascading invalidation is the protocol default)

        If effective_at is in the future: marks as pending_revocation.
        If effective_at is now or past (default): marks as revoked immediately.

        Returns RevocationResult with the full set of affected scope IDs.
        """
        scope = self.get_or_raise(scope_id)
        now = _now()
        effective = effective_at or now

        affected_ids: list[UUID] = []
        pending_ids: list[UUID] = []

        if effective_at is not None and effective > now:
            # Pending revocation: marks root as pending; descendants unaffected until effective
            scope.status = ScopeStatus.PENDING_REVOCATION
            scope.effective_at = effective.strftime("%Y-%m-%dT%H:%M:%SZ")
            # Re-seal: status field changed, descriptor_hash must update
            scope.seal()
            pending_ids.append(scope_id)
        else:
            # Immediate: cascade through entire subtree
            subtree = self.subtree_of(scope_id)
            for s in subtree:
                if s.status not in (ScopeStatus.REVOKED,):
                    s.status = ScopeStatus.REVOKED
                    s.effective_at = effective.strftime("%Y-%m-%dT%H:%M:%SZ")
                    s.seal()
                    affected_ids.append(s.id)

        return RevocationResult(
            root_scope_id=scope_id,
            revoked_ids=affected_ids,
            pending_ids=pending_ids,
            effective_at=effective.strftime("%Y-%m-%dT%H:%M:%SZ"),
            initiated_by=initiated_by,
        )

    def apply_pending_revocations(self, at: datetime | None = None) -> list[UUID]:
        """
        Scan for pending_revocation scopes whose effective_at has passed
        and promote them (and their descendants) to revoked.
        Called periodically or before any validation in time-sensitive contexts.
        Returns list of newly revoked scope IDs.
        """
        check_time = at or _now()
        newly_revoked: list[UUID] = []

        for scope in list(self._scopes.values()):
            if scope.status != ScopeStatus.PENDING_REVOCATION:
                continue
            if scope.effective_at is None:
                continue
            effective = _parse_timestamp(scope.effective_at)
            if check_time >= effective:
                # Directly cascade — bypass the future-time check in revoke()
                # since we're explicitly promoting a past-due pending revocation.
                effective_str = effective.strftime("%Y-%m-%dT%H:%M:%SZ")
                subtree = self.subtree_of(scope.id)
                for s in subtree:
                    if s.status != ScopeStatus.REVOKED:
                        s.status = ScopeStatus.REVOKED
                        s.effective_at = effective_str
                        s.seal()
                        newly_revoked.append(s.id)

        return newly_revoked


# ── RevocationResult ──────────────────────────────────────────

@dataclass(frozen=True)
class RevocationResult:
    """
    Returned by ScopeStore.revoke().
    Consumed by pact.receipts to produce RevocationReceipt.
    """
    root_scope_id: UUID
    revoked_ids:   list[UUID]   # immediately revoked (includes root and all descendants)
    pending_ids:   list[UUID]   # marked pending_revocation (future effective_at)
    effective_at:  Timestamp
    initiated_by:  str

    @property
    def is_immediate(self) -> bool:
        return len(self.revoked_ids) > 0

    @property
    def is_pending(self) -> bool:
        return len(self.pending_ids) > 0

    @property
    def all_affected(self) -> list[UUID]:
        return self.revoked_ids + self.pending_ids
