import type { EnrichedScope } from '../api/types';
import { displayNamespace, displayCeiling } from '../utils/display';

const ALL_TYPES = ['OBSERVE', 'PROPOSE', 'COMMIT'] as const;

interface Props {
  scopes: EnrichedScope[];
}

export default function ScopePopover({ scopes }: Props) {
  if (scopes.length === 0) {
    return (
      <div className="p-3 text-sm text-gray-400">
        No scopes assigned
      </div>
    );
  }

  return (
    <div className="p-3 space-y-2 min-w-[300px]">
      {scopes.map((scope) => {
        const typeSet = new Set(scope.types);
        return (
          <div key={scope.id} className="flex items-center gap-2 text-sm flex-wrap">
            <span className="font-medium text-gray-200">
              {displayNamespace(scope.namespace)}
            </span>
            <span className="text-gray-600">·</span>
            <span className="text-gray-300">
              {displayCeiling(scope.ceiling)}
            </span>
            <span className="text-gray-600">·</span>
            {ALL_TYPES.map((t) => {
              const has = typeSet.has(t);
              return (
                <span key={t} className="whitespace-nowrap">
                  <span>{has ? '✅' : '❌'}</span>{' '}
                  <span className={`text-xs ${has ? 'text-gray-200' : 'text-gray-500'}`}>
                    {t}
                  </span>
                  {!has && t === 'COMMIT' && (
                    <span className="text-xs text-amber-400 ml-0.5">(vote required)</span>
                  )}
                </span>
              );
            })}
          </div>
        );
      })}
    </div>
  );
}
