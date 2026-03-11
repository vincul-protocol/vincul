import { useState, useCallback } from 'react';
import { api } from '../api/client';
import type {
  MarketplaceSetupResult,
  MarketplaceContractResult,
  MarketplaceScopeResult,
  MarketplaceInvokeResult,
  MarketplaceRevokeResult,
  MarketplaceAuditResult,
} from '../api/types';
import FlowRunner from './FlowRunner';

const MP_ASSERTIONS = {
  IDENTITY: 'Cross-Vendor Identity',
  CONTRACT: 'Contract Integrity',
  DELEGATION: 'Bounded Delegation',
  ATTESTATION: 'Tool Attestation',
  REVOCATION: 'Real Revocation',
  AUDIT: 'Verifiable Receipts',
} as const;

const roleColors: Record<string, { dot: string; badge: string; border: string }> = {
  agent_host:    { dot: 'bg-blue-400',   badge: 'bg-blue-900/50 text-blue-300 border-blue-800/50',   border: 'border-blue-800' },
  tool_provider: { dot: 'bg-green-400',  badge: 'bg-green-900/50 text-green-300 border-green-800/50', border: 'border-green-800' },
  data_provider: { dot: 'bg-purple-400', badge: 'bg-purple-900/50 text-purple-300 border-purple-800/50', border: 'border-purple-800' },
};

function ReceiptDetail({ kind, detail, description }: {
  kind: string;
  detail: Record<string, unknown>;
  description: string;
}) {
  switch (kind) {
    case 'contract_activation':
      return (
        <span>
          Contract activated — {String(detail.decision_rule ?? '')} with{' '}
          {String(detail.signatures_present ?? '')} signatures
        </span>
      );
    case 'delegation':
      return (
        <span className="font-mono">
          <span className="text-gray-500">parent:</span>{' '}
          {String(detail.parent_scope_id ?? '').slice(0, 8)}...
          <span className="text-gray-500 ml-1">child:</span>{' '}
          {String(detail.child_scope_id ?? '').slice(0, 8)}...
          {Boolean(detail.delegate_granted) && (
            <span className="text-purple-400 ml-1">+delegate</span>
          )}
        </span>
      );
    case 'commitment':
      return (
        <span>
          <span className="font-mono">{String(detail.namespace ?? '')}</span>
          {' / '}
          <span className="font-mono">{String(detail.resource ?? '')}</span>
          {Boolean(detail.external_ref) && (
            <span className="text-gray-500 ml-1">
              ref: {String(detail.external_ref)}
            </span>
          )}
        </span>
      );
    case 'revocation':
      return (
        <span>
          Scope <span className="font-mono">{String(detail.revocation_root ?? '').slice(0, 8)}...</span>
          {' '}revoked ({String(detail.cascade_method ?? '')})
          {' at '}{String(detail.effective_at ?? '')}
        </span>
      );
    case 'failure': {
      const code = String(detail.error_code ?? '');
      const msg = String(detail.message ?? '');
      return (
        <span>
          <span className="text-red-400 font-mono">{code}</span>
          {msg && <span className="text-gray-500 ml-1">— {msg}</span>}
        </span>
      );
    }
    default:
      return <span className="text-gray-500">{description}</span>;
  }
}

interface Props {
  onReset?: () => void;
}

export default function MarketplaceDemo({ onReset }: Props) {
  const [completedSteps, setCompletedSteps] = useState<Set<number>>(new Set());

  const [setupResult, setSetupResult] = useState<MarketplaceSetupResult | null>(null);
  const [contractResult, setContractResult] = useState<MarketplaceContractResult | null>(null);
  const [scopeResult, setScopeResult] = useState<MarketplaceScopeResult | null>(null);
  const [invokeResult, setInvokeResult] = useState<MarketplaceInvokeResult | null>(null);
  const [revokeResult, setRevokeResult] = useState<MarketplaceRevokeResult | null>(null);
  const [postRevokeResult, setPostRevokeResult] = useState<MarketplaceInvokeResult | null>(null);
  const [constraintResult, setConstraintResult] = useState<MarketplaceInvokeResult | null>(null);
  const [auditResult, setAuditResult] = useState<MarketplaceAuditResult | null>(null);

  const markDone = useCallback((step: number) => {
    setCompletedSteps((prev) => new Set(prev).add(step));
  }, []);

  const handleReset = useCallback(async () => {
    await api.marketplaceReset();
    setCompletedSteps(new Set());
    setSetupResult(null);
    setContractResult(null);
    setScopeResult(null);
    setInvokeResult(null);
    setRevokeResult(null);
    setPostRevokeResult(null);
    setConstraintResult(null);
    setAuditResult(null);
    onReset?.();
  }, [onReset]);

  const done = (n: number) => completedSteps.has(n);

  return (
    <div className="space-y-4">
      {/* Header bar */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-bold text-white">Cross-Vendor Tool Marketplace</h2>
          <p className="text-sm text-gray-400">
            VendorA agents invoke VendorB tools under scoped delegation with cryptographic attestation
          </p>
        </div>
        <button
          onClick={handleReset}
          className="px-3 py-1.5 text-sm bg-gray-800 hover:bg-gray-700 rounded border border-gray-700 transition-colors"
        >
          Reset Marketplace
        </button>
      </div>

      {/* ── Contract Overview Panel ──────────────────────────── */}
      {contractResult && (
        <div className="bg-gray-900 rounded-lg border border-gray-800">
          <div className="flex items-center justify-between p-4">
            <div>
              <h2 className="text-lg font-semibold text-gray-100">
                {String((contractResult.purpose as Record<string, string>).title ?? 'Coalition Contract')}
              </h2>
              <p className="text-xs text-gray-500 mt-0.5">
                {String((contractResult.purpose as Record<string, string>).description ?? '')}
              </p>
            </div>
            <div className="flex items-center gap-3 flex-shrink-0">
              <span className="text-xs text-gray-500">{contractResult.principals.length} principals</span>
              <span className="text-xs px-2 py-0.5 rounded border bg-green-900/50 text-green-300 border-green-800">
                active
              </span>
            </div>
          </div>

          <div className="border-t border-gray-800 divide-y divide-gray-800">
            {/* Principals */}
            <details>
              <summary className="px-4 py-2.5 text-sm text-gray-400 cursor-pointer hover:text-gray-300 select-none list-none flex items-center gap-2">
                <span className="text-gray-600 transition-transform [details[open]>&]:rotate-90 text-xs">&#9654;</span>
                Principals
                <span className="text-xs text-gray-600 ml-auto">{contractResult.principals.length} members</span>
              </summary>
              <div className="px-4 pb-3">
                <div className="flex flex-wrap gap-1.5">
                  {contractResult.principals.map((pid) => (
                    <span key={pid} className="px-2 py-0.5 rounded text-xs bg-gray-800 text-gray-300">
                      {pid.split(':').slice(1).join(':')}
                      {setupResult?.vendors && (
                        <span className="text-gray-600 ml-1">
                          {setupResult.vendors.find((v) => v.id === pid)?.role ?? ''}
                        </span>
                      )}
                    </span>
                  ))}
                </div>
              </div>
            </details>

            {/* Governance */}
            <details>
              <summary className="px-4 py-2.5 text-sm text-gray-400 cursor-pointer hover:text-gray-300 select-none list-none flex items-center gap-2">
                <span className="text-gray-600 transition-transform [details[open]>&]:rotate-90 text-xs">&#9654;</span>
                Governance
                <span className="text-xs text-gray-600 ml-auto">
                  {String((contractResult.governance as Record<string, string>).decision_rule ?? 'unanimous')}
                </span>
              </summary>
              <div className="px-4 pb-3 text-sm space-y-1">
                <div className="flex justify-between text-xs">
                  <span className="text-gray-500">Decision rule</span>
                  <span className="text-gray-300">
                    {String((contractResult.governance as Record<string, string>).decision_rule ?? 'unanimous')}
                  </span>
                </div>
                <div className="flex justify-between text-xs">
                  <span className="text-gray-500">Descriptor hash</span>
                  <span className="text-gray-300 font-mono">{contractResult.descriptor_hash.slice(0, 24)}...</span>
                </div>
                <div className="flex justify-between text-xs">
                  <span className="text-gray-500">Hash verified</span>
                  <span className={contractResult.hash_valid ? 'text-green-400' : 'text-red-400'}>
                    {contractResult.hash_valid ? 'valid' : 'invalid'}
                  </span>
                </div>
              </div>
            </details>

            {/* Scope DAG */}
            {scopeResult && (
              <details>
                <summary className="px-4 py-2.5 text-sm text-gray-400 cursor-pointer hover:text-gray-300 select-none list-none flex items-center gap-2">
                  <span className="text-gray-600 transition-transform [details[open]>&]:rotate-90 text-xs">&#9654;</span>
                  Scope DAG
                  <span className="text-xs text-gray-600 ml-auto">{scopeResult.scopes.length} scopes</span>
                </summary>
                <div className="px-4 pb-3 space-y-1">
                  {scopeResult.scopes.map((s, i) => (
                    <div key={s.id} className="flex items-center gap-2 text-xs" style={{ marginLeft: `${i * 12}px` }}>
                      <span className={`w-1.5 h-1.5 rounded-full ${
                        s.status === 'active' ? 'bg-green-400' : 'bg-red-400'
                      }`} />
                      <span className={`font-mono ${
                        s.label === 'root' ? 'text-blue-400' :
                        s.label === 'mid' ? 'text-yellow-400' : 'text-green-400'
                      }`}>
                        {s.label}
                      </span>
                      <span className="text-gray-500">
                        {s.ceiling} | delegate: {String(s.delegate)}
                      </span>
                      <span className={`ml-auto px-1.5 py-0.5 rounded ${
                        s.status === 'active'
                          ? 'bg-green-900/50 text-green-400'
                          : 'bg-red-900/50 text-red-400'
                      }`}>
                        {s.status}
                      </span>
                    </div>
                  ))}
                </div>
              </details>
            )}
          </div>
        </div>
      )}

      {/* ── Vendor / Agent Cards ─────────────────────────────── */}
      {setupResult?.vendors && (
        <div className="grid grid-cols-3 gap-3">
          {setupResult.vendors.map((v) => {
            const colors = roleColors[v.role] ?? roleColors.data_provider;
            return (
              <div
                key={v.id}
                className={`bg-gray-900 rounded-lg border p-3 ${colors.border}`}
              >
                <div className="flex items-center gap-2 mb-2">
                  <span className={`w-2.5 h-2.5 rounded-full ${colors.dot}`} />
                  <span className="font-medium text-gray-100 text-sm">
                    {v.id.split(':')[1]}
                  </span>
                </div>
                <div className="flex items-center gap-2 mb-2">
                  <span className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium border ${colors.badge}`}>
                    {v.role === 'agent_host' && (
                      <svg width="10" height="10" viewBox="0 0 16 16" fill="currentColor" className="opacity-80">
                        <circle cx="8" cy="5" r="3" />
                        <path d="M2 14c0-3.3 2.7-6 6-6s6 2.7 6 6" />
                      </svg>
                    )}
                    {v.role === 'tool_provider' && (
                      <svg width="10" height="10" viewBox="0 0 16 16" fill="currentColor" className="opacity-80">
                        <path d="M3 2h10v12H3z" opacity="0.3" />
                        <path d="M5 5h6M5 8h6M5 11h4" stroke="currentColor" strokeWidth="1.2" fill="none" />
                      </svg>
                    )}
                    {v.role === 'data_provider' && (
                      <svg width="10" height="10" viewBox="0 0 16 16" fill="currentColor" className="opacity-80">
                        <ellipse cx="8" cy="4" rx="6" ry="2.5" opacity="0.3" />
                        <ellipse cx="8" cy="8" rx="6" ry="2.5" opacity="0.3" />
                        <ellipse cx="8" cy="12" rx="6" ry="2.5" opacity="0.3" />
                      </svg>
                    )}
                    {v.role.replace('_', ' ')}
                  </span>
                </div>
                <div className="text-[10px] text-gray-600 font-mono truncate">
                  pubkey: {v.pubkey}
                </div>
                {/* Show tool manifest for tool_provider */}
                {v.role === 'tool_provider' && setupResult.tool_manifest && (
                  <div className="mt-2 pt-2 border-t border-gray-800">
                    <div className="text-[10px] text-gray-500">tool manifest</div>
                    <div className="text-[10px] text-gray-400 font-mono mt-0.5">
                      {String((setupResult.tool_manifest as Record<string, string>).tool_id ?? '')}
                    </div>
                  </div>
                )}
                {/* Show agent info for agent_host */}
                {v.role === 'agent_host' && (
                  <div className="mt-2 pt-2 border-t border-gray-800">
                    <div className="text-[10px] text-gray-500">buyer agent</div>
                    <div className="text-[10px] text-gray-400 font-mono mt-0.5">
                      agent:VendorA:buyerAgent1
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      {/* ── Flow Steps ───────────────────────────────────────── */}

      {/* Step 1: Setup Vendors */}
      <FlowRunner
        number={1}
        title="Register Vendors"
        description="Create 3 cross-vendor principals with Ed25519 key pairs and tool manifest"
        assertion={MP_ASSERTIONS.IDENTITY}
        disabled={false}
        onRun={async () => {
          const r = await api.marketplaceSetup();
          setSetupResult(r);
          markDone(1);
        }}
        result={
          setupResult?.vendors && (
            <div className="space-y-3">
              <div className="bg-gray-800/50 rounded p-3">
                <div className="text-xs text-gray-500 mb-2">Vendors Registered</div>
                <div className="space-y-2">
                  {setupResult.vendors.map((v) => (
                    <div key={v.id} className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <span className={`w-2 h-2 rounded-full ${
                          roleColors[v.role]?.dot ?? 'bg-gray-400'
                        }`} />
                        <span className="text-sm text-gray-300 font-mono">{v.id}</span>
                      </div>
                      <div className="flex items-center gap-2">
                        <span className="text-xs text-gray-500">{v.role.replace('_', ' ')}</span>
                        <span className="text-xs text-gray-600 font-mono">{v.pubkey}</span>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
              {setupResult.tool_manifest && (
                <div className="bg-gray-800/50 rounded p-3">
                  <div className="text-xs text-gray-500 mb-1">Tool Manifest</div>
                  <div className="text-xs text-gray-400 font-mono whitespace-pre-wrap">
                    {JSON.stringify(setupResult.tool_manifest, null, 2).slice(0, 300)}
                  </div>
                </div>
              )}
            </div>
          )
        }
      />

      {/* Step 2: Create Contract */}
      <FlowRunner
        number={2}
        title="Create Coalition Contract"
        description="Activate a multi-vendor contract with descriptor hash integrity"
        assertion={MP_ASSERTIONS.CONTRACT}
        disabled={!done(1)}
        onRun={async () => {
          const r = await api.marketplaceContract();
          setContractResult(r);
          markDone(2);
        }}
        result={
          contractResult && (
            <div className="space-y-3">
              <div className="bg-gray-800/50 rounded p-3">
                <div className="text-xs text-gray-500 mb-1">Contract</div>
                <div className="font-mono text-sm text-gray-300">{contractResult.contract_id}</div>
                <div className="font-mono text-xs text-gray-500 mt-1">
                  hash: {contractResult.descriptor_hash.slice(0, 24)}...
                </div>
                <div className="flex items-center gap-2 mt-2">
                  <span className={`text-xs px-1.5 py-0.5 rounded ${
                    contractResult.hash_valid
                      ? 'bg-green-900/50 text-green-400'
                      : 'bg-red-900/50 text-red-400'
                  }`}>
                    {contractResult.hash_valid ? 'hash valid' : 'hash invalid'}
                  </span>
                  <span className="text-xs text-gray-500">
                    {contractResult.principals.length} principals
                  </span>
                </div>
              </div>
              <div className="bg-gray-800/50 rounded p-3">
                <div className="text-xs text-gray-500 mb-1">Purpose</div>
                <div className="text-sm text-gray-300">
                  {String((contractResult.purpose as Record<string, string>).title ?? '')}
                </div>
                <div className="text-xs text-gray-400 mt-1">
                  {String((contractResult.purpose as Record<string, string>).description ?? '')}
                </div>
              </div>
              <div className="bg-gray-800/50 rounded p-3">
                <div className="text-xs text-gray-500 mb-1">Governance</div>
                <div className="grid grid-cols-2 gap-1 text-xs">
                  <span className="text-gray-500">Decision rule:</span>
                  <span className="text-gray-300">
                    {String((contractResult.governance as Record<string, string>).decision_rule ?? '')}
                  </span>
                </div>
              </div>
            </div>
          )
        }
      />

      {/* Step 3: Create Scope DAG */}
      <FlowRunner
        number={3}
        title="Build Scope DAG"
        description="Create root -> mid -> leaf delegation chain with narrowing ceilings"
        assertion={MP_ASSERTIONS.DELEGATION}
        disabled={!done(2)}
        onRun={async () => {
          const r = await api.marketplaceScope();
          setScopeResult(r);
          markDone(3);
        }}
        result={
          scopeResult && (
            <div className="space-y-3">
              <div className="bg-gray-800/50 rounded p-3">
                <div className="text-xs text-gray-500 mb-2">Scope Hierarchy</div>
                <div className="space-y-1">
                  {scopeResult.scopes.map((s, i) => (
                    <div key={s.id} className="font-mono text-sm" style={{ marginLeft: `${i * 16}px` }}>
                      <span className={`${
                        s.label === 'root' ? 'text-blue-400' :
                        s.label === 'mid' ? 'text-yellow-400' : 'text-green-400'
                      }`}>
                        {s.label}
                      </span>
                      <span className="text-gray-600 text-xs ml-2">
                        ceiling: {s.ceiling} | delegate: {String(s.delegate)} | {s.status}
                      </span>
                    </div>
                  ))}
                </div>
              </div>

              <div className="bg-gray-800/50 rounded p-3">
                <div className="text-xs text-gray-500 mb-2">
                  Delegation Receipts ({scopeResult.delegation_receipts.length})
                </div>
                {scopeResult.delegation_receipts.map((r) => (
                  <div key={r.receipt_hash} className="text-xs font-mono text-gray-400 mb-1">
                    {r.parent_scope_id.slice(0, 8)}... -&gt; {r.child_scope_id.slice(0, 8)}...
                    <span className="text-gray-600 ml-2">
                      receipt: {r.receipt_hash.slice(0, 12)}...
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )
        }
      />

      {/* Step 4: Invoke Tool */}
      <FlowRunner
        number={4}
        title="Invoke Tool (Success)"
        description="Agent places order through tool provider — attested result with cryptographic signature"
        assertion={MP_ASSERTIONS.ATTESTATION}
        disabled={!done(3)}
        onRun={async () => {
          const r = await api.marketplaceInvoke('item-abc-001', 3);
          setInvokeResult(r);
          markDone(4);
        }}
        result={
          invokeResult && (
            <div className={`rounded p-3 ${
              invokeResult.success
                ? 'bg-green-900/20 border border-green-800'
                : 'bg-red-900/20 border border-red-800'
            }`}>
              <div className="flex items-center gap-2 mb-2">
                <span className={`text-sm font-medium ${
                  invokeResult.success ? 'text-green-400' : 'text-red-400'
                }`}>
                  {invokeResult.success ? 'Success' : 'Failed'}
                </span>
                <span className="text-xs text-gray-500">{invokeResult.receipt_kind}</span>
              </div>

              {invokeResult.success && invokeResult.payload && (
                <div className="space-y-2">
                  <div className="text-sm text-gray-300">
                    Order: <span className="font-mono text-green-300">
                      {String(invokeResult.payload.order_id)}
                    </span>
                    {' '} | ${String(invokeResult.payload.charged_amount_usd)}
                  </div>

                  {invokeResult.attested_result && (
                    <div className="bg-gray-800/50 rounded p-2 mt-2">
                      <div className="text-xs text-gray-500 mb-1">Attested Result</div>
                      <div className="grid grid-cols-2 gap-1 text-xs">
                        <div className="text-gray-400">Tool:</div>
                        <div className="text-gray-300 font-mono">{invokeResult.attested_result.tool_id}</div>
                        <div className="text-gray-400">Signer:</div>
                        <div className="text-gray-300 font-mono">{invokeResult.attested_result.signature.signer_id}</div>
                        <div className="text-gray-400">Algorithm:</div>
                        <div className="text-gray-300 font-mono">{invokeResult.attested_result.signature.algo}</div>
                        <div className="text-gray-400">Signature valid:</div>
                        <div className={invokeResult.signature_valid ? 'text-green-400' : 'text-red-400'}>
                          {invokeResult.signature_valid ? 'yes' : 'no'}
                        </div>
                      </div>
                      <div className="mt-1 text-xs text-gray-600 font-mono">
                        payload hash: {invokeResult.attested_result.result_payload_hash.slice(0, 24)}...
                      </div>
                    </div>
                  )}
                </div>
              )}

              <div className="mt-2 text-xs text-gray-500 font-mono">
                receipt: {invokeResult.receipt_hash.slice(0, 16)}...
              </div>
            </div>
          )
        }
      />

      {/* Step 5: Revoke + Post-Revoke */}
      <FlowRunner
        number={5}
        title="Revoke Scope & Fail-Closed"
        description="Revoke mid scope (BFS cascade to leaf), then invoke to prove fail-closed behavior"
        assertion={MP_ASSERTIONS.REVOCATION}
        disabled={!done(4)}
        onRun={async () => {
          const rev = await api.marketplaceRevoke();
          setRevokeResult(rev);

          // Update scope statuses in the overview panel
          if (scopeResult) {
            const updated = { ...scopeResult, scopes: scopeResult.scopes.map((s) => {
              const revState = rev.scope_states.find((rs) => rs.id === s.id);
              return revState ? { ...s, status: revState.status } : s;
            })};
            setScopeResult(updated);
          }

          try {
            const postRev = await api.marketplaceInvoke('item-abc-002', 2);
            setPostRevokeResult(postRev);
          } catch {
            // Expected failure
          }

          try {
            const cv = await api.marketplaceInvoke('item-abc-003', 99);
            setConstraintResult(cv);
          } catch {
            // Expected failure
          }

          markDone(5);
        }}
        result={
          revokeResult && (
            <div className="space-y-3">
              <div className="bg-amber-900/20 border border-amber-800 rounded p-3">
                <div className="flex items-center gap-2 mb-2">
                  <span className="text-sm font-medium text-amber-400">Revoked</span>
                  <span className="text-xs text-gray-500">
                    {revokeResult.revoked_scope_ids.length} scopes cascaded
                  </span>
                </div>
                <div className="space-y-1">
                  {revokeResult.scope_states.map((s) => (
                    <div key={s.id} className="flex items-center gap-2 text-xs">
                      <span className="text-gray-400 font-mono">{s.label}</span>
                      <span className={`px-1.5 py-0.5 rounded ${
                        s.status === 'active'
                          ? 'bg-green-900/50 text-green-400'
                          : 'bg-red-900/50 text-red-400'
                      }`}>
                        {s.status}
                      </span>
                    </div>
                  ))}
                </div>
                <div className="mt-2 text-xs text-gray-500 font-mono">
                  receipt: {revokeResult.receipt_hash.slice(0, 16)}...
                </div>
              </div>

              {postRevokeResult && (
                <div className="bg-red-900/20 border border-red-800 rounded p-3">
                  <div className="text-xs text-gray-500 mb-1">Post-Revocation Invoke</div>
                  <div className="flex items-center gap-2 mb-1">
                    <span className="text-sm font-medium text-red-400">Denied</span>
                    {postRevokeResult.failure_code && (
                      <span className="px-1.5 py-0.5 bg-red-900 text-red-300 rounded text-xs font-mono">
                        {postRevokeResult.failure_code}
                      </span>
                    )}
                  </div>
                  <div className="text-xs text-gray-400">{postRevokeResult.message}</div>
                  <div className="mt-1 text-xs text-gray-500 font-mono">
                    receipt: {postRevokeResult.receipt_hash.slice(0, 16)}...
                  </div>
                </div>
              )}

              {constraintResult && (
                <div className="bg-red-900/20 border border-red-800 rounded p-3">
                  <div className="text-xs text-gray-500 mb-1">Constraint Violation (qty=99)</div>
                  <div className="flex items-center gap-2 mb-1">
                    <span className="text-sm font-medium text-red-400">Denied</span>
                    {constraintResult.failure_code && (
                      <span className="px-1.5 py-0.5 bg-red-900 text-red-300 rounded text-xs font-mono">
                        {constraintResult.failure_code}
                      </span>
                    )}
                  </div>
                  <div className="text-xs text-gray-400">{constraintResult.message}</div>
                  <div className="mt-1 text-xs text-gray-500 font-mono">
                    receipt: {constraintResult.receipt_hash.slice(0, 16)}...
                  </div>
                </div>
              )}
            </div>
          )
        }
      />

      {/* Step 6: Audit Trail */}
      <FlowRunner
        number={6}
        title="Audit Trail"
        description="Full receipt timeline with hash verification across all operations"
        assertion={MP_ASSERTIONS.AUDIT}
        disabled={!done(5)}
        onRun={async () => {
          const r = await api.marketplaceAudit();
          setAuditResult(r);
          markDone(6);
        }}
        result={
          auditResult && (
            <div className="space-y-3">
              <div className="bg-gray-800/50 rounded p-3">
                <div className="flex items-center gap-3">
                  <span className="text-sm text-gray-300">
                    {auditResult.total_receipts} receipts
                  </span>
                  <span className={`text-xs px-2 py-0.5 rounded ${
                    auditResult.all_hashes_valid
                      ? 'bg-green-900/50 text-green-400'
                      : 'bg-red-900/50 text-red-400'
                  }`}>
                    {auditResult.all_hashes_valid ? 'all hashes valid' : 'hash mismatch detected'}
                  </span>
                </div>
              </div>

              <div className="bg-gray-800/50 rounded p-3 max-h-80 overflow-y-auto">
                <div className="text-xs text-gray-500 mb-2">Receipt Timeline</div>
                <table className="w-full text-xs">
                  <thead>
                    <tr className="text-gray-500 text-left border-b border-gray-700">
                      <th className="py-1 pr-2 w-6">#</th>
                      <th className="py-1 pr-2">Kind</th>
                      <th className="py-1 pr-2">Outcome</th>
                      <th className="py-1 pr-2">Initiated By</th>
                      <th className="py-1 pr-2">Detail</th>
                      <th className="py-1 pr-2">Receipt Hash</th>
                      <th className="py-1 w-8 text-center">Hash</th>
                    </tr>
                  </thead>
                  <tbody>
                    {auditResult.receipts.map((r) => (
                      <tr key={r.index} className="border-b border-gray-800/50 last:border-0 align-top">
                        <td className="py-1.5 pr-2 text-gray-600 text-right">{r.index}</td>
                        <td className="py-1.5 pr-2">
                          <span className={`px-1.5 py-0.5 rounded font-mono whitespace-nowrap ${
                            r.receipt_kind === 'delegation' ? 'bg-purple-900/50 text-purple-300' :
                            r.receipt_kind === 'contract_activation' ? 'bg-blue-900/50 text-blue-300' :
                            r.receipt_kind === 'commitment' ? 'bg-emerald-900/50 text-emerald-300' :
                            r.receipt_kind === 'revocation' ? 'bg-amber-900/50 text-amber-300' :
                            r.receipt_kind === 'failure' ? 'bg-red-900/50 text-red-300' :
                            'bg-gray-700 text-gray-300'
                          }`}>
                            {r.receipt_kind}
                          </span>
                        </td>
                        <td className={`py-1.5 pr-2 ${r.outcome === 'success' ? 'text-green-400' : 'text-red-400'}`}>
                          {r.outcome}
                        </td>
                        <td className="py-1.5 pr-2 text-gray-400 font-mono break-all">
                          {r.initiated_by}
                        </td>
                        <td className="py-1.5 pr-2 text-gray-400">
                          <ReceiptDetail kind={r.receipt_kind} detail={r.detail} description={r.description} />
                        </td>
                        <td className="py-1.5 pr-2 text-gray-600 font-mono whitespace-nowrap">
                          {r.receipt_hash.slice(0, 16)}...
                        </td>
                        <td className={`py-1.5 text-center ${r.hash_valid ? 'text-green-600' : 'text-red-600'}`}>
                          {r.hash_valid ? 'ok' : 'bad'}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )
        }
      />
    </div>
  );
}
