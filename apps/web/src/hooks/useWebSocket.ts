import { useEffect, useRef, useCallback } from 'react';
import type { WsEvent } from '../api/types';

export function useWebSocket(onEvent: (event: WsEvent) => void) {
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimer = useRef<number>();
  const onEventRef = useRef(onEvent);
  onEventRef.current = onEvent;

  const connect = useCallback((aborted: { current: boolean }) => {
    if (aborted.current) return;
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const url = `${protocol}//${window.location.host}/ws`;
    const ws = new WebSocket(url);

    ws.onmessage = (e) => {
      try {
        const event = JSON.parse(e.data) as WsEvent;
        onEventRef.current(event);
      } catch {
        // ignore unparseable messages
      }
    };

    ws.onclose = () => {
      if (!aborted.current) {
        reconnectTimer.current = window.setTimeout(() => connect(aborted), 2000);
      }
    };

    ws.onerror = () => {
      ws.close();
    };

    wsRef.current = ws;
  }, []);

  useEffect(() => {
    const aborted = { current: false };
    connect(aborted);
    return () => {
      aborted.current = true;
      clearTimeout(reconnectTimer.current);
      wsRef.current?.close();
    };
  }, [connect]);

  return wsRef;
}
