import type { DemoFullState, EnrichedScope } from '../api/types';
import { usePopover } from '../hooks/usePopover';
import StakeholderCard from './StakeholderCard';
import ScopePopover from './ScopePopover';
import Popover from './Popover';

interface Props {
  state: DemoFullState | null;
  cardRefs: React.MutableRefObject<Map<string, HTMLDivElement>>;
  animatingCards?: Set<string>;
}

export default function StakeholderGrid({ state, cardRefs, animatingCards }: Props) {
  const { state: popoverState, handlers } = usePopover();

  if (!state || !state.contract) {
    return (
      <div className="bg-gray-900 rounded-lg border border-gray-800 p-4 min-h-[5rem]">
        <div className="text-sm text-gray-500">Run Flow 1 to see stakeholders</div>
      </div>
    );
  }

  // Group scopes by principal
  const scopesByPrincipal = new Map<string, EnrichedScope[]>();
  for (const scope of state.scopes) {
    if (scope.principal_id) {
      const existing = scopesByPrincipal.get(scope.principal_id) ?? [];
      existing.push(scope);
      scopesByPrincipal.set(scope.principal_id, existing);
    }
  }

  const activePrincipal = popoverState.activeId;
  const activeScopes = activePrincipal ? (scopesByPrincipal.get(activePrincipal) ?? []) : [];

  return (
    <>
      <div className="grid grid-cols-4 gap-3">
        {state.principals.map((p) => (
          <StakeholderCard
            key={p.principal_id}
            principal={p}
            scopes={scopesByPrincipal.get(p.principal_id) ?? []}
            isActive={popoverState.activeId === p.principal_id}
            onHoverEnter={handlers.onMouseEnter}
            onHoverLeave={handlers.onMouseLeave}
            onClickCard={handlers.onClick}
            cardRef={(el) => {
              if (el) cardRefs.current.set(p.principal_id, el);
              else cardRefs.current.delete(p.principal_id);
            }}
            animationClass={animatingCards?.has(p.principal_id) ? 'animate-pulse-red' : undefined}
          />
        ))}
      </div>

      <Popover
        anchorEl={popoverState.anchorEl}
        open={!!popoverState.activeId}
        onClose={handlers.onClose}
        onMouseEnter={handlers.onPopoverMouseEnter}
        onMouseLeave={handlers.onPopoverMouseLeave}
      >
        <ScopePopover scopes={activeScopes} />
      </Popover>
    </>
  );
}
