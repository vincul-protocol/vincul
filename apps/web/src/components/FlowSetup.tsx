import { useState } from 'react';
import { api } from '../api/client';
import type { SetupResult } from '../api/types';
import FlowRunner from './FlowRunner';

interface Props {
  disabled: boolean;
  onComplete: (result: SetupResult) => void;
}

export default function FlowSetup({ disabled, onComplete }: Props) {
  const [result, setResult] = useState<SetupResult | null>(null);

  const run = async () => {
    const r = await api.setupContract();
    setResult(r);
    onComplete(r);
  };

  return (
    <FlowRunner
      number={1}
      title="Form Coalition Contract"
      description="Register and activate the Group Trip to Italy contract with 3 delegated scopes"
      assertion="Bounded Delegation"
      disabled={disabled}
      onRun={run}
      result={
        result && (
          <div className="space-y-3">
            {/* Contract */}
            <div className="bg-gray-800/50 rounded p-3">
              <div className="text-xs text-gray-500 mb-1">Contract</div>
              <div className="font-mono text-sm text-gray-300">
                {result.contract_id}
              </div>
              <div className="font-mono text-xs text-gray-500 mt-1">
                hash: {result.contract_hash.slice(0, 16)}...
              </div>
            </div>

            {/* Scope tree */}
            <div className="bg-gray-800/50 rounded p-3">
              <div className="text-xs text-gray-500 mb-2">Scope Hierarchy</div>
              <div className="text-sm text-gray-300 space-y-1 font-mono">
                <div>
                  <span className="text-blue-400">travel</span>
                  <span className="text-gray-600 text-xs ml-2">(root, all types, TOP/TOP)</span>
                </div>
                <div className="ml-4">
                  <span className="text-green-400">travel.flights</span>
                  <span className="text-gray-600 text-xs ml-2">(O+P+C, cost {'<='} 1500)</span>
                </div>
                <div className="ml-4">
                  <span className="text-purple-400">travel.accommodation</span>
                  <span className="text-gray-600 text-xs ml-2">(O+P only, cost {'<='} 1500)</span>
                </div>
              </div>
            </div>

            {/* Principals */}
            <div className="bg-gray-800/50 rounded p-3">
              <div className="text-xs text-gray-500 mb-1">
                Principals ({result.principals.length})
              </div>
              <div className="flex flex-wrap gap-1">
                {result.principals.map((p) => (
                  <span
                    key={p}
                    className="px-2 py-0.5 bg-gray-700 rounded text-xs text-gray-300"
                  >
                    {p.split(':')[1]}
                  </span>
                ))}
              </div>
            </div>
          </div>
        )
      }
    />
  );
}
