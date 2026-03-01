import type { DemoStatus } from '../api/types';
import ScopeCard from './ScopeCard';

export default function StatusPanel({ status }: { status: DemoStatus | null }) {
  if (!status) {
    return (
      <div className="bg-gray-900 rounded-lg border border-gray-800 p-4">
        <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wider mb-2">
          Live Status
        </h2>
        <p className="text-sm text-gray-500">Loading...</p>
      </div>
    );
  }

  return (
    <div className="bg-gray-900 rounded-lg border border-gray-800 p-4 space-y-4">
      <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wider">
        Live Status
      </h2>

      {/* Scopes */}
      {status.scopes.length > 0 && (
        <div>
          <h3 className="text-xs text-gray-500 mb-2">
            Scopes ({status.scopes.length})
          </h3>
          <div className="space-y-2">
            {status.scopes.map((s) => (
              <ScopeCard key={s.id} scope={s} />
            ))}
          </div>
        </div>
      )}

      {/* Votes */}
      {Object.keys(status.active_votes).length > 0 && (
        <div>
          <h3 className="text-xs text-gray-500 mb-2">Active Votes</h3>
          {Object.entries(status.active_votes).map(([vid, v]) => (
            <div key={vid} className="bg-gray-800/50 rounded px-3 py-2 text-sm">
              <div className="text-gray-300 text-xs mb-1">{v.request}</div>
              <div className="flex items-center gap-2">
                <div className="flex-1 bg-gray-700 rounded-full h-1.5">
                  <div
                    className="bg-blue-500 h-1.5 rounded-full transition-all"
                    style={{ width: `${(v.votes / v.threshold) * 100}%` }}
                  />
                </div>
                <span className="text-xs text-gray-400">
                  {v.votes}/{v.threshold}
                </span>
                {v.resolved && (
                  <span className="text-xs text-green-400">passed</span>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
