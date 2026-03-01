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

// ── Constants ────────────────────────────────────────────────

export const PRINCIPALS = [
  'principal:raanan',
  'principal:yaki',
  'principal:coordinator',
  'principal:alice',
  'principal:bob',
  'principal:carol',
  'principal:dan',
  'principal:eve',
] as const;

export const CONTRACT_ID = 'c0000000-0000-0000-0000-000000000001';
export const ROOT_SCOPE_ID = 's0000000-0000-0000-0000-000000000001';
export const RAANAN_FLIGHTS_ID = 's0000000-0000-0000-0000-000000000002';
export const YAKI_ACCOMMODATION_ID = 's0000000-0000-0000-0000-000000000003';
