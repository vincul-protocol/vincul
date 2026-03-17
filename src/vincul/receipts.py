"""
vincul.receipts — Receipt schema, builders, and append-only log
spec: spec/receipts/RECEIPT.md, spec/receipts/FAILURE_CODES.md

Depends on: vincul.hashing, vincul.types
"""

from __future__ import annotations

import json
import uuid as uuid_mod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from vincul.hashing import vincul_hash, is_valid_vincul_hash
from vincul.types import FailureCode, Hash, ReceiptKind, Timestamp, UUID


# ── Timestamp helper ──────────────────────────────────────────

def now_utc() -> Timestamp:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def new_uuid() -> UUID:
    return str(uuid_mod.uuid4())


# ── Core Receipt dataclass ────────────────────────────────────

@dataclass(frozen=True)
class Receipt:
    """
    A Vincul Receipt. Immutable once receipt_hash is set.

    Fields match the envelope defined in RECEIPT.md §2.
    signatures is excluded from the hash (detached signature model).
    """
    receipt_id:    UUID
    receipt_kind:  ReceiptKind
    issued_at:     Timestamp

    # intent
    action:        str
    description:   str
    initiated_by:  str

    # authority
    scope_id:      UUID | None
    scope_hash:    Hash | None
    contract_id:   UUID
    contract_hash: Hash
    signatories:   list[str]

    # result
    outcome:       str         # "success" | "failure"
    detail:        dict[str, Any]

    prior_receipt: Hash | None = None
    receipt_hash:  Hash | None = None   # set after construction
    signatures:    list[dict]  = field(default_factory=list)

    # ── Serialization ─────────────────────────────────────────

    def _payload_for_hash(self) -> dict:
        """
        Canonical payload for hashing — excludes receipt_hash and signatures.
        Per HASHING.md §6.2.
        """
        return {
            "receipt_id":   self.receipt_id,
            "receipt_kind": self.receipt_kind.value,
            "issued_at":    self.issued_at,
            "intent": {
                "action":       self.action,
                "description":  self.description,
                "initiated_by": self.initiated_by,
            },
            "authority": {
                "scope_id":      self.scope_id,
                "scope_hash":    self.scope_hash,
                "contract_id":   self.contract_id,
                "contract_hash": self.contract_hash,
                "signatories":   self.signatories,
            },
            "result": {
                "outcome": self.outcome,
                "detail":  self.detail,
            },
            "prior_receipt": self.prior_receipt,
        }

    def compute_hash(self) -> Hash:
        return vincul_hash("receipt", self._payload_for_hash())

    def seal(self) -> "Receipt":
        """Compute and set receipt_hash. Raises if already sealed.

        Not thread-safe: the check-then-set is not atomic. Concurrent
        callers could both pass the guard. This is acceptable because
        seal() is deterministic (same fields → same hash) and Vincul
        stores have no thread-safety guarantees. Callers needing
        concurrency must synchronize externally.
        """
        if self.receipt_hash is not None:
            raise RuntimeError("Receipt already sealed")
        object.__setattr__(self, "receipt_hash", self.compute_hash())
        return self

    def to_dict(self) -> dict:
        d = self._payload_for_hash()
        d["receipt_hash"] = self.receipt_hash
        d["signatures"] = self.signatures
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Receipt":
        return cls(
            receipt_id    = d["receipt_id"],
            receipt_kind  = ReceiptKind(d["receipt_kind"]),
            issued_at     = d["issued_at"],
            action        = d["intent"]["action"],
            description   = d["intent"]["description"],
            initiated_by  = d["intent"]["initiated_by"],
            scope_id      = d["authority"]["scope_id"],
            scope_hash    = d["authority"]["scope_hash"],
            contract_id   = d["authority"]["contract_id"],
            contract_hash = d["authority"]["contract_hash"],
            signatories   = d["authority"]["signatories"],
            outcome       = d["result"]["outcome"],
            detail        = d["result"]["detail"],
            prior_receipt = d.get("prior_receipt"),
            receipt_hash  = d.get("receipt_hash"),
            signatures    = d.get("signatures", []),
        )

    def verify_hash(self) -> bool:
        """Return True if stored receipt_hash matches recomputed hash."""
        if not self.receipt_hash:
            return False
        return self.compute_hash() == self.receipt_hash


# ── Receipt builders ──────────────────────────────────────────
# Each builder returns a sealed Receipt.

def _base(
    kind: ReceiptKind,
    action: str,
    description: str,
    initiated_by: str,
    scope_id: UUID | None,
    scope_hash: Hash | None,
    contract_id: UUID,
    contract_hash: Hash,
    signatories: list[str],
    outcome: str,
    detail: dict,
    prior_receipt: Hash | None = None,
) -> Receipt:
    return Receipt(
        receipt_id    = new_uuid(),
        receipt_kind  = kind,
        issued_at     = now_utc(),
        action        = action,
        description   = description,
        initiated_by  = initiated_by,
        scope_id      = scope_id,
        scope_hash    = scope_hash,
        contract_id   = contract_id,
        contract_hash = contract_hash,
        signatories   = signatories,
        outcome       = outcome,
        detail        = detail,
        prior_receipt = prior_receipt,
    ).seal()


def delegation_receipt(
    *,
    initiated_by: str,
    scope_id: UUID,
    scope_hash: Hash,
    contract_id: UUID,
    contract_hash: Hash,
    child_scope_id: UUID,
    child_scope_hash: Hash,
    parent_scope_id: UUID,
    types_granted: list[str],
    delegate_granted: bool,
    revoke_granted: str,
    expires_at: Timestamp | None,
    ceiling_hash: Hash,
    description: str = "",
) -> Receipt:
    return _base(
        kind          = ReceiptKind.DELEGATION,
        action        = "delegate",
        description   = description or f"Delegate to scope {child_scope_id}",
        initiated_by  = initiated_by,
        scope_id      = scope_id,
        scope_hash    = scope_hash,
        contract_id   = contract_id,
        contract_hash = contract_hash,
        signatories   = [initiated_by],
        outcome       = "success",
        detail        = {
            "child_scope_id":    child_scope_id,
            "child_scope_hash":  child_scope_hash,
            "parent_scope_id":   parent_scope_id,
            "types_granted":     types_granted,
            "delegate_granted":  delegate_granted,
            "revoke_granted":    revoke_granted,
            "expires_at":        expires_at,
            "ceiling_hash":      ceiling_hash,
        },
    )


def commitment_receipt(
    *,
    initiated_by: str,
    scope_id: UUID,
    scope_hash: Hash,
    contract_id: UUID,
    contract_hash: Hash,
    namespace: str,
    resource: str,
    params: dict,
    reversible: bool,
    revert_window: str | None,
    external_ref: str | None,
    budget_consumed: list[dict] | None = None,
    description: str = "",
) -> Receipt:
    return _base(
        kind          = ReceiptKind.COMMITMENT,
        action        = "commit",
        description   = description or f"Commit action on {namespace}/{resource}",
        initiated_by  = initiated_by,
        scope_id      = scope_id,
        scope_hash    = scope_hash,
        contract_id   = contract_id,
        contract_hash = contract_hash,
        signatories   = [initiated_by],
        outcome       = "success",
        detail        = {
            "action_type":      "COMMIT",
            "namespace":        namespace,
            "resource":         resource,
            "params":           params,
            "reversible":       reversible,
            "revert_window":    revert_window,
            "external_ref":     external_ref,
            "budget_consumed":  budget_consumed,
        },
    )


def failure_receipt(
    *,
    initiated_by: str,
    scope_id: UUID | None,
    scope_hash: Hash | None,
    contract_id: UUID,
    contract_hash: Hash,
    error_code: FailureCode,
    message: str,
    recoverable: bool = False,
    prior_receipt: Hash | None = None,
    **extra_detail: Any,
) -> Receipt:
    detail = {
        "error_code":    error_code.value,
        "message":       message,
        "recoverable":   recoverable,
        "scope_id":      scope_id,
        "scope_hash":    scope_hash,
        "contract_id":   contract_id,
        "contract_hash": contract_hash,
        **extra_detail,
    }
    return _base(
        kind          = ReceiptKind.FAILURE,
        action        = "fail",
        description   = f"Action denied: {message}",
        initiated_by  = initiated_by,
        scope_id      = scope_id,
        scope_hash    = scope_hash,
        contract_id   = contract_id,
        contract_hash = contract_hash,
        signatories   = [],
        outcome       = "failure",
        detail        = detail,
        prior_receipt = prior_receipt,
    )


def revocation_receipt(
    *,
    initiated_by: str,
    scope_id: UUID,
    scope_hash: Hash,
    contract_id: UUID,
    contract_hash: Hash,
    revocation_root: UUID,
    authority_type: str,
    effective_at: Timestamp,
    cascade_method: str = "root+proof",
    revert_attempts: list = None,
    non_revertable: list = None,
    description: str = "",
) -> Receipt:
    return _base(
        kind          = ReceiptKind.REVOCATION,
        action        = "revoke",
        description   = description or f"Revoke scope {scope_id}",
        initiated_by  = initiated_by,
        scope_id      = scope_id,
        scope_hash    = scope_hash,
        contract_id   = contract_id,
        contract_hash = contract_hash,
        signatories   = [initiated_by],
        outcome       = "success",
        detail        = {
            "revocation_root":  revocation_root,
            "revoked_by":       initiated_by,
            "authority_type":   authority_type,
            "effective_at":     effective_at,
            "cascade_method":   cascade_method,
            "revert_attempts":  revert_attempts or [],
            "non_revertable":   non_revertable or [],
        },
    )


def attestation_receipt(
    *,
    initiated_by: str,
    scope_id: UUID,
    scope_hash: Hash,
    contract_id: UUID,
    contract_hash: Hash,
    attests_receipt_id: UUID,
    attests_receipt_hash: Hash,
    response_hash_algo: str,
    response_hash_value: str,
    response_schema: str,
    external_ref: str | None,
    produced_at: Timestamp,
    prior_receipt: Hash | None = None,
    description: str = "",
) -> Receipt:
    return _base(
        kind          = ReceiptKind.ATTESTATION,
        action        = "attest",
        description   = description or f"Attest to commitment {attests_receipt_id}",
        initiated_by  = initiated_by,
        scope_id      = scope_id,
        scope_hash    = scope_hash,
        contract_id   = contract_id,
        contract_hash = contract_hash,
        signatories   = [initiated_by],
        outcome       = "success",
        detail        = {
            "attests_receipt_id":   attests_receipt_id,
            "attests_receipt_hash": attests_receipt_hash,
            "response_hash": {
                "algo":  response_hash_algo,
                "value": response_hash_value,
            },
            "response_schema": response_schema,
            "external_ref":    external_ref,
            "produced_at":     produced_at,
        },
        prior_receipt = prior_receipt,
    )


def revert_attempt_receipt(
    *,
    initiated_by: str,
    scope_id: UUID,
    scope_hash: Hash,
    contract_id: UUID,
    contract_hash: Hash,
    target_commitment: UUID,
    triggered_by: UUID,
    revert_detail: str,
    residual: str | None = None,
    outcome: str = "success",
    prior_receipt: Hash | None = None,
    description: str = "",
) -> Receipt:
    return _base(
        kind          = ReceiptKind.REVERT_ATTEMPT,
        action        = "revert",
        description   = description or f"Revert attempt for commitment {target_commitment}",
        initiated_by  = initiated_by,
        scope_id      = scope_id,
        scope_hash    = scope_hash,
        contract_id   = contract_id,
        contract_hash = contract_hash,
        signatories   = [initiated_by],
        outcome       = outcome,
        detail        = {
            "target_commitment": target_commitment,
            "triggered_by":     triggered_by,
            "revert_detail":    revert_detail,
            "residual":         residual,
        },
        prior_receipt = prior_receipt,
    )


def ledger_snapshot_receipt(
    *,
    initiated_by: str,
    scope_id: UUID,
    scope_hash: Hash,
    contract_id: UUID,
    contract_hash: Hash,
    snapshot_type: str,
    covers_scope_id: UUID,
    snapshot_from: Timestamp,
    snapshot_to: Timestamp,
    balances: list[dict],
    prior_snapshot: Hash | None = None,
    commitment_refs: list[Hash] | None = None,
    prior_receipt: Hash | None = None,
    description: str = "",
) -> Receipt:
    return _base(
        kind          = ReceiptKind.LEDGER_SNAPSHOT,
        action        = "ledger_snapshot",
        description   = description or f"Ledger snapshot ({snapshot_type}) for scope {covers_scope_id}",
        initiated_by  = initiated_by,
        scope_id      = scope_id,
        scope_hash    = scope_hash,
        contract_id   = contract_id,
        contract_hash = contract_hash,
        signatories   = [initiated_by],
        outcome       = "success",
        detail        = {
            "snapshot_type":    snapshot_type,
            "covers_scope_id":  covers_scope_id,
            "snapshot_period": {
                "from": snapshot_from,
                "to":   snapshot_to,
            },
            "balances":         balances,
            "prior_snapshot":   prior_snapshot,
            "commitment_refs":  commitment_refs,
        },
        prior_receipt = prior_receipt,
    )


def activation_receipt(
    *,
    initiated_by: str,
    contract_id: UUID,
    contract_hash: Hash,
    activated_at: Timestamp,
    decision_rule: str,
    signatures_present: int,
    signatories: list[str],
    description: str = "",
) -> Receipt:
    return _base(
        kind          = ReceiptKind.CONTRACT_ACTIVATION,
        action        = "activate_contract",
        description   = description or "Coalition contract activated",
        initiated_by  = initiated_by,
        scope_id      = None,
        scope_hash    = None,
        contract_id   = contract_id,
        contract_hash = contract_hash,
        signatories   = signatories,
        outcome       = "success",
        detail        = {
            "contract_id":          contract_id,
            "contract_hash":        contract_hash,
            "activated_at":         activated_at,
            "activated_by":         initiated_by,
            "decision_rule":        decision_rule,
            "signatures_present":   signatures_present,
        },
    )



def dissolution_receipt(
    *,
    initiated_by: str,
    contract_id: UUID,
    contract_hash_before: Hash,
    contract_hash_after: Hash,
    dissolved_at: Timestamp,
    decision_rule: str,
    signatures_present: int,
    signatories: list[str],
    ledger_snapshot_hash: Hash | None = None,
    description: str = "",
) -> Receipt:
    return _base(
        kind          = ReceiptKind.CONTRACT_DISSOLUTION,
        action        = "dissolve_contract",
        description   = description or "Coalition dissolved",
        initiated_by  = initiated_by,
        scope_id      = None,
        scope_hash    = None,
        contract_id   = contract_id,
        contract_hash = contract_hash_before,
        signatories   = signatories,
        outcome       = "success",
        detail        = {
            "contract_id":           contract_id,
            "contract_hash_before":  contract_hash_before,
            "contract_hash_after":   contract_hash_after,
            "dissolved_at":          dissolved_at,
            "dissolved_by":          initiated_by,
            "decision_rule":         decision_rule,
            "signatures_present":    signatures_present,
            "ledger_snapshot_hash":  ledger_snapshot_hash,
        },
    )


# ── Append-only ReceiptLog ────────────────────────────────────

class ReceiptLog:
    """
    Append-only in-memory receipt store.
    Supports timeline queries by contract, scope, and kind.

    In production: back with a persistent append-only store.
    Invariant: once appended, a receipt is never mutated or removed.
    """

    def __init__(self) -> None:
        self._by_hash:     dict[Hash, Receipt] = {}
        self._by_contract: dict[UUID, list[Hash]] = {}
        self._by_scope:    dict[UUID, list[Hash]] = {}
        self._ordered:     list[Hash] = []

    def append(self, receipt: Receipt) -> Receipt:
        """
        Append a receipt to the log.
        Raises ValueError if receipt_hash is missing or if hash is duplicate.
        Raises ValueError if hash verification fails.
        """
        if not receipt.receipt_hash:
            raise ValueError("Cannot append receipt without receipt_hash. Call .seal() first.")
        if not receipt.verify_hash():
            raise ValueError(
                f"Receipt hash mismatch for {receipt.receipt_id}. "
                "Receipt may have been tampered with."
            )
        if receipt.receipt_hash in self._by_hash:
            raise ValueError(f"Duplicate receipt_hash: {receipt.receipt_hash}")

        self._by_hash[receipt.receipt_hash] = receipt
        self._ordered.append(receipt.receipt_hash)

        self._by_contract.setdefault(receipt.contract_id, []).append(receipt.receipt_hash)
        if receipt.scope_id:
            self._by_scope.setdefault(receipt.scope_id, []).append(receipt.receipt_hash)

        return receipt

    def get(self, receipt_hash: Hash) -> Receipt | None:
        return self._by_hash.get(receipt_hash)

    def for_contract(self, contract_id: UUID) -> list[Receipt]:
        """All receipts for a contract, in append order."""
        return [self._by_hash[h] for h in self._by_contract.get(contract_id, [])]

    def for_scope(self, scope_id: UUID) -> list[Receipt]:
        """All receipts for a scope, in append order."""
        return [self._by_hash[h] for h in self._by_scope.get(scope_id, [])]

    def timeline(self) -> list[Receipt]:
        """All receipts in append order."""
        return [self._by_hash[h] for h in self._ordered]

    def __len__(self) -> int:
        return len(self._ordered)
