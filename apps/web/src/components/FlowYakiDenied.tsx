import { useState } from 'react';
import { api } from '../api/client';
import type { ActionResult } from '../api/types';
import FlowRunner from './FlowRunner';

interface Props {
  disabled: boolean;
  scopeId: string;
  onComplete: () => void;
}

export default function FlowYakiDenied({ disabled, scopeId, onComplete }: Props) {
  const [result, setResult] = useState<ActionResult | null>(null);

  const run = async () => {
    const r = await api.performAction({
      principal: 'principal:yaki',
      scope_id: scopeId,
      action: {
        type: 'COMMIT',
        namespace: 'travel.accommodation',
        resource: 'hotel:rome-center',
        params: { cost: 450 },
      },
      budget_amounts: { EUR: '450.00' },
    });
    setResult(r);
    onComplete();
  };

  return (
    <FlowRunner
      number={3}
      title="Yaki's Personal Agent Tries Hotel Booking"
      description="COMMIT on OBSERVE+PROPOSE-only scope -- should fail with TYPE_ESCALATION"
      assertion="Scope Enforcement"
      disabled={disabled}
      onRun={run}
      result={
        result && (
          <div className="bg-red-900/20 border border-red-800 rounded p-3">
            <div className="flex items-center gap-2 mb-2">
              <span className="text-sm font-medium text-red-400">
                Denied
              </span>
              <span className="px-1.5 py-0.5 bg-red-900 text-red-300 rounded text-xs font-mono">
                {String(result.detail.error_code)}
              </span>
            </div>
            <div className="text-sm text-gray-300">
              {String(result.detail.message)}
            </div>
            <div className="mt-2 text-xs text-gray-400">
              Scope permits:{' '}
              {(result.detail.scope_types as string[])?.map((t) => (
                <span
                  key={t}
                  className="inline-block px-1.5 py-0.5 bg-gray-700 rounded mr-1 text-gray-300"
                >
                  {t}
                </span>
              ))}
              <span className="ml-2 text-red-400">
                Requested: {String(result.detail.action_type)}
              </span>
            </div>
            <div className="mt-1 text-xs text-gray-500 font-mono">
              receipt: {result.receipt_hash.slice(0, 16)}...
            </div>
          </div>
        )
      }
    />
  );
}
