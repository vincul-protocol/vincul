import { useState } from 'react';
import { api } from '../api/client';
import type { ActionResult } from '../api/types';
import { RAANAN_FLIGHTS_ID } from '../api/types';
import FlowRunner from './FlowRunner';

interface Props {
  disabled: boolean;
  onComplete: () => void;
}

export default function FlowRaananBook({ disabled, onComplete }: Props) {
  const [result, setResult] = useState<ActionResult | null>(null);

  const run = async () => {
    const r = await api.performAction({
      principal: 'principal:raanan',
      scope_id: RAANAN_FLIGHTS_ID,
      action: {
        type: 'COMMIT',
        namespace: 'travel.flights',
        resource: 'flight:LHR-TLV-20250601',
        params: { cost: 280 },
      },
      budget_amounts: { EUR: '280.00' },
    });
    setResult(r);
    onComplete();
  };

  return (
    <FlowRunner
      number={2}
      title="Raanan Books Flight"
      description="COMMIT on travel.flights scope with valid authority -- should succeed"
      assertion="Verifiable Receipts"
      disabled={disabled}
      onRun={run}
      result={
        result && (
          <div
            className={`rounded p-3 ${
              result.outcome === 'success'
                ? 'bg-green-900/20 border border-green-800'
                : 'bg-red-900/20 border border-red-800'
            }`}
          >
            <div className="flex items-center gap-2 mb-2">
              <span
                className={`text-sm font-medium ${
                  result.outcome === 'success' ? 'text-green-400' : 'text-red-400'
                }`}
              >
                {result.outcome === 'success' ? 'Committed' : 'Failed'}
              </span>
              <span className="text-xs text-gray-500">
                {result.receipt_kind}
              </span>
            </div>
            <div className="text-sm text-gray-300">{result.summary}</div>
            {result.detail.external_ref != null && (
              <div className="mt-1 text-xs text-gray-400">
                External ref:{' '}
                <span className="font-mono text-gray-300">
                  {String(result.detail.external_ref)}
                </span>
              </div>
            )}
            <div className="mt-1 text-xs text-gray-500 font-mono">
              receipt: {result.receipt_hash.slice(0, 16)}...
            </div>
          </div>
        )
      }
    />
  );
}
