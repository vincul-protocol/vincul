import type { ScopeInfo } from '../api/types';

const typeColors: Record<string, string> = {
  OBSERVE: 'bg-blue-900 text-blue-300',
  PROPOSE: 'bg-purple-900 text-purple-300',
  COMMIT: 'bg-green-900 text-green-300',
};

const statusColors: Record<string, string> = {
  active: 'text-green-400',
  revoked: 'text-red-400',
  pending_revocation: 'text-amber-400',
  expired: 'text-gray-400',
};

export default function ScopeCard({ scope }: { scope: ScopeInfo }) {
  return (
    <div className="bg-gray-800/50 rounded px-3 py-2 text-sm">
      <div className="flex items-center justify-between mb-1">
        <span className="font-mono text-gray-300">{scope.namespace}</span>
        <span className={`text-xs ${statusColors[scope.status] ?? 'text-gray-400'}`}>
          {scope.status}
        </span>
      </div>
      <div className="flex gap-1">
        {scope.types.map((t) => (
          <span
            key={t}
            className={`px-1.5 py-0.5 rounded text-xs font-medium ${typeColors[t] ?? 'bg-gray-700 text-gray-300'}`}
          >
            {t}
          </span>
        ))}
      </div>
      <div className="text-xs text-gray-500 mt-1 font-mono truncate">
        {scope.id}
      </div>
    </div>
  );
}
