import { useState, useEffect, useRef, useCallback } from 'react';
import type { WsEvent, DemoFullState } from '../api/types';

interface AnimationSpec {
  id: string;
  type: 'commitment' | 'failure' | 'delegation' | 'revocation' | 'contract_dissolution';
  paths: Array<{ sx: number; sy: number; tx: number; ty: number; color: string }>;
  pulseTarget?: string;
  duration: number;
  startedAt: number;
}

const KIND_COLORS: Record<string, string> = {
  commitment: '#22c55e',
  failure: '#ef4444',
  delegation: '#3b82f6',
  revocation: '#f59e0b',
  contract_dissolution: '#6b7280',
};

const KIND_DURATIONS: Record<string, number> = {
  commitment: 800,
  failure: 600,
  delegation: 800,
  revocation: 1000,
  contract_dissolution: 1200,
};

interface Props {
  events: WsEvent[];
  cardRefs: React.MutableRefObject<Map<string, HTMLDivElement>>;
  state: DemoFullState | null;
  onPulseCard?: (principalId: string) => void;
  onPulseEnd?: (principalId: string) => void;
}

function getCardCenter(el: HTMLDivElement): { x: number; y: number } {
  const rect = el.getBoundingClientRect();
  return { x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 };
}

export default function AgentMessageFlow({ events, cardRefs, state, onPulseCard, onPulseEnd }: Props) {
  const [animations, setAnimations] = useState<AnimationSpec[]>([]);
  const processedRef = useRef<Set<string>>(new Set());

  // Find principal for a scope
  const scopeToPrincipal = useCallback((scopeId: string | null | undefined): string | null => {
    if (!scopeId || !state) return null;
    const scope = state.scopes.find((s) => s.id === scopeId);
    return scope?.principal_id ?? null;
  }, [state]);

  // Process new events
  useEffect(() => {
    if (events.length === 0) return;
    const latest = events[0];
    if (latest.event_type !== 'receipt') return;

    const key = latest.receipt_hash;
    if (processedRef.current.has(key)) return;
    processedRef.current.add(key);

    const kind = latest.receipt_kind as AnimationSpec['type'];
    const duration = KIND_DURATIONS[kind] ?? 800;
    const color = KIND_COLORS[kind] ?? '#6b7280';
    const cards = cardRefs.current;

    const paths: AnimationSpec['paths'] = [];
    let pulseTarget: string | undefined;

    if (kind === 'failure') {
      // Pulse on initiator
      pulseTarget = latest.initiated_by;
      if (onPulseCard && pulseTarget) onPulseCard(pulseTarget);
      setTimeout(() => {
        if (onPulseEnd && pulseTarget) onPulseEnd(pulseTarget);
      }, duration);
    } else if (kind === 'commitment') {
      const sourceEl = cards.get(latest.initiated_by);
      const coordEl = cards.get('principal:coordinator');
      if (sourceEl && coordEl) {
        const s = getCardCenter(sourceEl);
        const t = getCardCenter(coordEl);
        paths.push({ sx: s.x, sy: s.y, tx: t.x, ty: t.y, color });
      }
    } else if (kind === 'delegation') {
      const coordEl = cards.get('principal:coordinator');
      const targetPrincipal = scopeToPrincipal(latest.scope_id);
      const targetEl = targetPrincipal ? cards.get(targetPrincipal) : null;
      if (coordEl && targetEl) {
        const s = getCardCenter(coordEl);
        const t = getCardCenter(targetEl);
        paths.push({ sx: s.x, sy: s.y, tx: t.x, ty: t.y, color });
      }
    } else if (kind === 'revocation') {
      const coordEl = cards.get('principal:coordinator');
      if (coordEl) {
        const s = getCardCenter(coordEl);
        for (const [pid, el] of cards) {
          if (pid !== 'principal:coordinator') {
            const t = getCardCenter(el);
            paths.push({ sx: s.x, sy: s.y, tx: t.x, ty: t.y, color });
          }
        }
      }
    } else if (kind === 'contract_dissolution') {
      // Fade-out handled via CSS class on SVG
    }

    if (paths.length > 0 || pulseTarget) {
      const anim: AnimationSpec = {
        id: key,
        type: kind,
        paths,
        pulseTarget,
        duration,
        startedAt: performance.now(),
      };
      setAnimations((prev) => [...prev, anim]);

      // Remove after duration + buffer
      setTimeout(() => {
        setAnimations((prev) => prev.filter((a) => a.id !== key));
      }, duration + 200);
    }
  }, [events, cardRefs, state, scopeToPrincipal, onPulseCard, onPulseEnd]);

  // Reset processed when events are cleared
  useEffect(() => {
    if (events.length === 0) {
      processedRef.current.clear();
      setAnimations([]);
    }
  }, [events.length]);

  if (animations.length === 0) return null;

  return (
    <svg
      style={{
        position: 'fixed',
        inset: 0,
        width: '100vw',
        height: '100vh',
        pointerEvents: 'none',
        zIndex: 50,
      }}
    >
      {animations.map((anim) =>
        anim.paths.map((p, i) => {
          // Quadratic bezier with control point above midpoint
          const mx = (p.sx + p.tx) / 2;
          const my = Math.min(p.sy, p.ty) - 40;
          const d = `M ${p.sx} ${p.sy} Q ${mx} ${my} ${p.tx} ${p.ty}`;
          // Approximate path length
          const dx = p.tx - p.sx;
          const dy = p.ty - p.sy;
          const pathLen = Math.sqrt(dx * dx + dy * dy) * 1.3;

          return (
            <path
              key={`${anim.id}-${i}`}
              d={d}
              stroke={p.color}
              strokeWidth={2}
              fill="none"
              strokeDasharray={pathLen}
              strokeDashoffset={pathLen}
              opacity={0.8}
              style={{
                animation: `arc-draw ${anim.duration}ms ease-out forwards`,
              }}
            />
          );
        }),
      )}
    </svg>
  );
}
