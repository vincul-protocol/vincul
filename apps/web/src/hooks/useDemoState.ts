import { useState, useCallback } from 'react';
import { api } from '../api/client';
import type { DemoStatus, DemoFullState } from '../api/types';

export function useDemoState() {
  const [status, setStatus] = useState<DemoStatus | null>(null);
  const [state, setState] = useState<DemoFullState | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [s, st] = await Promise.all([
        api.getStatus(),
        api.getState(),
      ]);
      setStatus(s);
      setState(st);
    } catch {
      // silent — status is best-effort
    }
  }, []);

  return { status, state, refresh, setStatus, setState };
}
