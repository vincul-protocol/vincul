import { useState, useCallback } from 'react';
import { api } from '../api/client';
import type { DemoStatus } from '../api/types';

export function useDemoState() {
  const [status, setStatus] = useState<DemoStatus | null>(null);

  const refresh = useCallback(async () => {
    try {
      const s = await api.getStatus();
      setStatus(s);
    } catch {
      // silent — status is best-effort
    }
  }, []);

  return { status, refresh, setStatus };
}
