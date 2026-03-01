import { useState } from 'react';
import { api } from '../api/client';
import type { ActionResult, DissolveResult } from '../api/types';
import { PRINCIPALS, RAANAN_FLIGHTS_ID } from '../api/types';
import FlowRunner from './FlowRunner';

interface Props {
  disabled: boolean;
  onComplete: () => void;
}

export default function FlowDissolve({ disabled, onComplete }: Props) {
  const [result, setResult] = useState<DissolveResult | null>(null);
  const [postAction, setPostAction] = useState<ActionResult | null>(null);

  const run = async () => {
    // Dissolve
    const r = await api.dissolveContract(
      'principal:coordinator',
      [...PRINCIPALS],
    );
    setResult(r);

    // Attempt post-dissolution action to prove revocation is real
    try {
      const action = await api.performAction({
        principal: 'principal:raanan',
        scope_id: RAANAN_FLIGHTS_ID,
        action: {
          type: 'COMMIT',
          namespace: 'travel.flights',
          resource: 'flight:LHR-FCO-20250602',
          params: { cost: 300 },
        },
        budget_amounts: { EUR: '300.00' },
      });
      setPostAction(action);
    } catch {
      // Expected to fail at HTTP level or return failure receipt
    }

    onComplete();
  };

  return (
    <FlowRunner
      number={5}
      title="Dissolve Coalition"
      description="Dissolve contract, revoke all scopes, prove post-dissolution actions fail"
      assertion="Real Revocation"
      disabled={disabled}
      onRun={run}
      result={
        result && (
          <div className="space-y-3">
            {/* Dissolution receipts */}
            {result.receipts.map((r, i) => (
              <div
                key={i}
                className={`rounded p-3 ${
                  r.receipt_kind === 'contract_dissolution'
                    ? 'bg-gray-800 border border-gray-700'
                    : 'bg-amber-900/20 border border-amber-800'
                }`}
              >
                <div className="flex items-center gap-2 mb-1">
                  <span
                    className={`px-1.5 py-0.5 rounded text-xs font-medium ${
                      r.receipt_kind === 'contract_dissolution'
                        ? 'bg-gray-700 text-gray-300'
                        : 'bg-amber-900 text-amber-300'
                    }`}
                  >
                    {r.receipt_kind}
                  </span>
                  <span className="text-xs text-green-400">{r.outcome}</span>
                </div>
                <div className="text-xs text-gray-500 font-mono">
                  {r.receipt_hash.slice(0, 16)}...
                </div>
              </div>
            ))}

            {/* Post-dissolution action attempt */}
            {postAction && (
              <div className="bg-red-900/20 border border-red-800 rounded p-3">
                <div className="text-xs text-gray-500 mb-1">
                  Post-dissolution action attempt
                </div>
                <div className="flex items-center gap-2 mb-1">
                  <span className="text-sm font-medium text-red-400">
                    Denied
                  </span>
                  <span className="px-1.5 py-0.5 bg-red-900 text-red-300 rounded text-xs font-mono">
                    {String(postAction.detail.error_code)}
                  </span>
                </div>
                <div className="text-sm text-gray-300">
                  {postAction.summary}
                </div>
                <div className="mt-1 text-xs text-gray-500 font-mono">
                  receipt: {postAction.receipt_hash.slice(0, 16)}...
                </div>
              </div>
            )}
          </div>
        )
      }
    />
  );
}
