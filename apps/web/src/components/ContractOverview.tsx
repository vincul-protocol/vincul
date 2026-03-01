import type { DemoFullState } from '../api/types';
import { principalName, displayCeiling } from '../utils/display';

const statusColors: Record<string, string> = {
  active: 'bg-green-900/50 text-green-300 border-green-800',
  draft: 'bg-yellow-900/50 text-yellow-300 border-yellow-800',
  dissolved: 'bg-gray-800 text-gray-400 border-gray-700',
};

interface Props {
  state: DemoFullState | null;
}

export default function ContractOverview({ state }: Props) {
  if (!state || !state.contract) {
    return (
      <div className="bg-gray-900 rounded-lg border border-gray-800 p-4 min-h-[3.5rem]">
        <div className="text-sm text-gray-500">No contract active</div>
      </div>
    );
  }

  const { contract, principals, governance, budget_policy } = state;
  const statusClass = statusColors[contract.status] ?? statusColors.draft;

  return (
    <div className="bg-gray-900 rounded-lg border border-gray-800">
      {/* Header — always visible, scannable */}
      <div className="flex items-center justify-between p-4">
        <div>
          <h2 className="text-lg font-semibold text-gray-100">{contract.title}</h2>
          <p className="text-xs text-gray-500 mt-0.5">{contract.description}</p>
        </div>
        <div className="flex items-center gap-3 flex-shrink-0">
          <span className="text-xs text-gray-500">{principals.length} principals</span>
          <span className={`text-xs px-2 py-0.5 rounded border ${statusClass}`}>
            {contract.status}
          </span>
        </div>
      </div>

      {/* Collapsible sections */}
      <div className="border-t border-gray-800 divide-y divide-gray-800">
        {/* Principals */}
        <details>
          <summary className="px-4 py-2.5 text-sm text-gray-400 cursor-pointer hover:text-gray-300 select-none list-none flex items-center gap-2">
            <span className="text-gray-600 transition-transform [details[open]>&]:rotate-90 text-xs">&#9654;</span>
            Principals
            <span className="text-xs text-gray-600 ml-auto">{principals.length} members</span>
          </summary>
          <div className="px-4 pb-3">
            <div className="flex flex-wrap gap-1.5">
              {principals.map((p) => (
                <span
                  key={p.principal_id}
                  className="px-2 py-0.5 rounded text-xs bg-gray-800 text-gray-300"
                >
                  {principalName(p.principal_id)}
                  <span className="text-gray-600 ml-1">{p.role}</span>
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
            <span className="text-xs text-gray-600 ml-auto">{governance.threshold}/{principals.length} threshold</span>
          </summary>
          <div className="px-4 pb-3 text-sm space-y-1">
            <div className="flex justify-between text-xs">
              <span className="text-gray-500">Decision rule</span>
              <span className="text-gray-300">{governance.decision_rule} ({governance.threshold}/{principals.length})</span>
            </div>
            <div className="flex justify-between text-xs">
              <span className="text-gray-500">Amendment rule</span>
              <span className="text-gray-300">{governance.amendment_rule} ({governance.amendment_threshold}/{principals.length})</span>
            </div>
          </div>
        </details>

        {/* Budget Policy */}
        <details>
          <summary className="px-4 py-2.5 text-sm text-gray-400 cursor-pointer hover:text-gray-300 select-none list-none flex items-center gap-2">
            <span className="text-gray-600 transition-transform [details[open]>&]:rotate-90 text-xs">&#9654;</span>
            Budget Policy
            <span className="text-xs text-gray-600 ml-auto">
              {budget_policy.allowed ? 'enabled' : 'disabled'}
            </span>
          </summary>
          <div className="px-4 pb-3 text-sm space-y-1">
            {budget_policy.dimensions.map((d) => (
              <div key={d.name} className="flex justify-between text-xs">
                <span className="text-gray-500">{d.name}</span>
                <span className="text-gray-300">
                  {displayCeiling(`action.params.cost <= ${d.ceiling}`)}
                </span>
              </div>
            ))}
          </div>
        </details>
      </div>
    </div>
  );
}
