// ── Backend response types ───────────────────────────────────

export interface DemoStatus {
  setup_complete: boolean;
  contract: {
    id: string;
    status: string | null;
    hash: string | null;
  };
  scopes: ScopeInfo[];
  receipt_count: number;
  active_votes: Record<string, VoteInfo>;
}

export interface ScopeInfo {
  id: string;
  namespace: string;
  types: string[];
  status: string;
}

export interface VoteInfo {
  request: string;
  votes: number;
  threshold: number;
  resolved: boolean;
}

export interface SetupResult {
  status: string;
  contract_id: string;
  contract_hash: string;
  scopes: {
    root: string;
    raanan_flights: string;
    yaki_accommodation: string;
  };
  principals: string[];
}

export interface ActionResult {
  receipt_kind: string;
  receipt_hash: string;
  outcome: string;
  detail: Record<string, unknown>;
  summary: string;
}

export interface DissolveResult {
  status: string;
  receipts: Array<{
    receipt_kind: string;
    receipt_hash: string;
    outcome: string;
  }>;
}

export interface VoteSessionResult {
  vote_id: string;
  scope_id: string;
  request: string;
  requested_types: string[];
  requested_ceiling: string;
  votes_for: string[];
  threshold: number;
  resolved: boolean;
  new_scope_id: string | null;
  delegation_receipt?: {
    receipt_kind: string;
    receipt_hash: string;
    outcome: string;
  };
}

// ── Request types ────────────────────────────────────────────

export interface ActionRequest {
  principal: string;
  scope_id: string;
  action: {
    type: string;
    namespace: string;
    resource: string;
    params: Record<string, unknown>;
  };
  budget_amounts?: Record<string, string> | null;
}

export interface OpenVoteRequest {
  scope_id: string;
  request: string;
  requested_types: string[];
  requested_ceiling: string;
}

// ── Enriched state types (from GET /demo/state) ─────────────

export interface DemoFullState {
  contract: {
    id: string;
    title: string;
    description: string;
    status: string;
    hash: string | null;
    version: string;
    expires_at: string | null;
  } | null;
  principals: PrincipalInfo[];
  governance: GovernanceInfo;
  budget_policy: BudgetPolicyInfo;
  scopes: EnrichedScope[];
  receipt_count: number;
}

export interface PrincipalInfo {
  principal_id: string;
  role: string;
}

export interface GovernanceInfo {
  decision_rule: string;
  threshold: number;
  amendment_rule: string;
  amendment_threshold: number;
}

export interface BudgetPolicyInfo {
  allowed: boolean;
  dimensions: Array<{
    name: string;
    unit: string;
    ceiling: string;
  }>;
}

export interface EnrichedScope {
  id: string;
  principal_id: string | null;
  namespace: string;
  types: string[];
  predicate: string;
  ceiling: string;
  delegate: boolean;
  status: string;
  issued_by: string;
  issued_by_scope_id: string | null;
}

// ── WebSocket events ─────────────────────────────────────────

export type WsEvent =
  | {
      event_type: 'contract_setup';
      status: string;
      contract_id: string;
    }
  | {
      event_type: 'receipt';
      receipt_kind: string;
      receipt_hash: string;
      issued_at: string;
      initiated_by: string;
      outcome: string;
      summary: string;
      detail: Record<string, unknown>;
      scope_id?: string | null;
    }
  | {
      event_type: 'vote_opened';
      vote_id: string;
      scope_id: string;
      request: string;
    }
  | {
      event_type: 'vote_cast';
      vote_id: string;
      principal: string;
      votes_count: number;
      resolved: boolean;
    };

// ── Marketplace types ───────────────────────────────────────

export interface MarketplaceVendor {
  id: string;
  role: string;
  pubkey: string;
}

export interface MarketplaceSetupResult {
  status: string;
  vendors: MarketplaceVendor[];
  tool_manifest: Record<string, unknown>;
}

export interface MarketplaceContractResult {
  status: string;
  contract_id: string;
  descriptor_hash: string;
  principals: string[];
  governance: Record<string, unknown>;
  purpose: Record<string, unknown>;
  hash_valid: boolean;
}

export interface MarketplaceScopeEntry {
  label: string;
  id: string;
  namespace: string;
  types: string[];
  ceiling: string;
  predicate: string;
  delegate: boolean;
  status: string;
  parent_scope_id: string | null;
  descriptor_hash: string;
}

export interface MarketplaceDelegationReceipt {
  receipt_hash: string;
  child_scope_id: string;
  parent_scope_id: string;
}

export interface MarketplaceScopeResult {
  status: string;
  scopes: MarketplaceScopeEntry[];
  delegation_receipts: MarketplaceDelegationReceipt[];
}

export interface MarketplaceInvokeResult {
  success: boolean;
  receipt_kind: string;
  receipt_hash: string;
  outcome: string;
  payload?: Record<string, unknown>;
  attested_result?: {
    status: string;
    tool_id: string;
    contract_hash: string;
    scope_hash: string;
    receipt_hash: string;
    result_payload: Record<string, unknown>;
    result_payload_hash: string;
    external_ref: string;
    signature: { signer_id: string; algo: string };
  };
  signature_valid?: boolean;
  failure_code?: string;
  message?: string;
}

export interface MarketplaceRevokeResult {
  status: string;
  revocation_root: string;
  revoked_scope_ids: string[];
  effective_at: string;
  receipt_hash: string;
  scope_states: Array<{ label: string; id: string; status: string }>;
}

export interface MarketplaceAuditReceipt {
  index: number;
  receipt_kind: string;
  outcome: string;
  initiated_by: string;
  receipt_hash: string;
  scope_id: string | null;
  description: string;
  detail: Record<string, unknown>;
  hash_valid: boolean;
}

export interface MarketplaceAuditResult {
  total_receipts: number;
  all_hashes_valid: boolean;
  receipts: MarketplaceAuditReceipt[];
}
