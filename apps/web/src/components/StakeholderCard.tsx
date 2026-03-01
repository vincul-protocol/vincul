import { useRef, useCallback } from 'react';
import type { EnrichedScope, PrincipalInfo } from '../api/types';
import { principalName } from '../utils/display';

interface Props {
  principal: PrincipalInfo;
  scopes: EnrichedScope[];
  isActive: boolean;
  onHoverEnter: (id: string, el: HTMLElement) => void;
  onHoverLeave: () => void;
  onClickCard: (id: string, el: HTMLElement) => void;
  cardRef: (el: HTMLDivElement | null) => void;
  animationClass?: string;
}

export default function StakeholderCard({
  principal,
  scopes,
  isActive,
  onHoverEnter,
  onHoverLeave,
  onClickCard,
  cardRef,
  animationClass,
}: Props) {
  const elRef = useRef<HTMLDivElement | null>(null);

  const setRef = useCallback((el: HTMLDivElement | null) => {
    elRef.current = el;
    cardRef(el);
  }, [cardRef]);

  const handleMouseEnter = useCallback(() => {
    if (elRef.current) onHoverEnter(principal.principal_id, elRef.current);
  }, [onHoverEnter, principal.principal_id]);

  const handleClick = useCallback(() => {
    if (elRef.current) onClickCard(principal.principal_id, elRef.current);
  }, [onClickCard, principal.principal_id]);

  const name = principalName(principal.principal_id);
  const scopeCount = scopes.length;
  const hasCommit = scopes.some((s) => s.types.includes('COMMIT'));

  return (
    <div
      ref={setRef}
      onMouseEnter={handleMouseEnter}
      onMouseLeave={onHoverLeave}
      onClick={handleClick}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          handleClick();
        }
      }}
      className={`
        relative bg-gray-900 rounded-lg border p-3 cursor-pointer
        transition-colors select-none
        ${isActive ? 'border-blue-500 bg-gray-800' : 'border-gray-800 hover:border-gray-600'}
        ${animationClass ?? ''}
      `}
    >
      {/* Name */}
      <div className="font-medium text-gray-100 text-sm">{name}</div>

      {/* Agent badge */}
      <div className="flex items-center gap-2 mt-1">
        <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium bg-blue-900/50 text-blue-300 border border-blue-800/50">
          <svg width="10" height="10" viewBox="0 0 16 16" fill="currentColor" className="opacity-80">
            <circle cx="8" cy="5" r="3" />
            <path d="M2 14c0-3.3 2.7-6 6-6s6 2.7 6 6" />
            <rect x="12" y="2" width="3" height="3" rx="0.5" opacity="0.6" />
          </svg>
          Agent
        </span>
        {scopeCount > 0 && (
          <span className="text-[10px] text-gray-500">
            {scopeCount} scope{scopeCount > 1 ? 's' : ''}
            {!hasCommit && scopeCount > 0 && (
              <span className="text-amber-500 ml-1">limited</span>
            )}
          </span>
        )}
      </div>
    </div>
  );
}
