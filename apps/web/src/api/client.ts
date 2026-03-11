import type {
  ActionRequest,
  ActionResult,
  DemoFullState,
  DemoStatus,
  DissolveResult,
  MarketplaceAuditResult,
  MarketplaceContractResult,
  MarketplaceInvokeResult,
  MarketplaceRevokeResult,
  MarketplaceScopeResult,
  MarketplaceSetupResult,
  OpenVoteRequest,
  SetupResult,
  VoteSessionResult,
} from './types';

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
    this.name = 'ApiError';
  }
}

async function request<T>(
  method: 'GET' | 'POST',
  path: string,
  body?: unknown,
): Promise<T> {
  const res = await fetch(path, {
    method,
    headers: body ? { 'Content-Type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new ApiError(res.status, err.detail ?? 'Unknown error');
  }

  return res.json();
}

export const api = {
  setupContract: () =>
    request<SetupResult>('POST', '/contract/setup'),

  dissolveContract: (initiated_by: string, signatures: string[]) =>
    request<DissolveResult>('POST', '/contract/dissolve', { initiated_by, signatures }),

  performAction: (payload: ActionRequest) =>
    request<ActionResult>('POST', '/action', payload),

  openVote: (payload: OpenVoteRequest) =>
    request<VoteSessionResult>('POST', '/vote/open', payload),

  castVote: (vote_id: string, principal: string) =>
    request<VoteSessionResult>('POST', '/vote/cast', { vote_id, principal }),

  resetDemo: () =>
    request<{ status: string }>('POST', '/demo/reset'),

  getStatus: () =>
    request<DemoStatus>('GET', '/demo/status'),

  getState: () =>
    request<DemoFullState>('GET', '/demo/state'),

  // Marketplace endpoints
  marketplaceSetup: () =>
    request<MarketplaceSetupResult>('POST', '/marketplace/setup'),

  marketplaceContract: () =>
    request<MarketplaceContractResult>('POST', '/marketplace/contract'),

  marketplaceScope: () =>
    request<MarketplaceScopeResult>('POST', '/marketplace/scope'),

  marketplaceInvoke: (item_id: string, quantity: number, shipping_zip = '10001') =>
    request<MarketplaceInvokeResult>('POST', '/marketplace/invoke', { item_id, quantity, shipping_zip }),

  marketplaceRevoke: () =>
    request<MarketplaceRevokeResult>('POST', '/marketplace/revoke'),

  marketplaceAudit: () =>
    request<MarketplaceAuditResult>('GET', '/marketplace/audit'),

  marketplaceReset: () =>
    request<{ status: string }>('POST', '/marketplace/reset'),
};
