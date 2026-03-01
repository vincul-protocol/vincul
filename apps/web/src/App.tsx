import { useState, useCallback, useEffect } from 'react';
import type { WsEvent } from './api/types';
import { api } from './api/client';
import { useWebSocket } from './hooks/useWebSocket';
import { useDemoState } from './hooks/useDemoState';
import Header from './components/Header';
import StatusPanel from './components/StatusPanel';
import ReceiptTimeline from './components/ReceiptTimeline';
import FlowSetup from './components/FlowSetup';
import FlowRaananBook from './components/FlowRaananBook';
import FlowYakiDenied from './components/FlowYakiDenied';
import FlowVoteWiden from './components/FlowVoteWiden';
import FlowDissolve from './components/FlowDissolve';

export default function App() {
  const [events, setEvents] = useState<WsEvent[]>([]);
  const [completedFlows, setCompletedFlows] = useState<Set<number>>(new Set());
  const { status, refresh, setStatus } = useDemoState();

  // Fetch initial status
  useEffect(() => {
    refresh();
  }, [refresh]);

  // WebSocket event handler
  const handleWsEvent = useCallback((event: WsEvent) => {
    setEvents((prev) => [event, ...prev]);
  }, []);

  useWebSocket(handleWsEvent);

  // Flow completion handler
  const markComplete = useCallback(
    (flow: number) => {
      setCompletedFlows((prev) => new Set(prev).add(flow));
      refresh();
    },
    [refresh],
  );

  // Reset handler
  const handleReset = useCallback(async () => {
    await api.resetDemo();
    setEvents([]);
    setCompletedFlows(new Set());
    setStatus(null);
    await refresh();
  }, [refresh, setStatus]);

  const setupDone = completedFlows.has(1);

  return (
    <div className="min-h-screen bg-gray-950 text-gray-100">
      <Header status={status} onReset={handleReset} />

      <div className="flex gap-6 p-6 max-w-screen-2xl mx-auto">
        {/* Main: Flow cards */}
        <main className="flex-1 space-y-4 min-w-0">
          <FlowSetup
            disabled={false}
            onComplete={() => markComplete(1)}
          />
          <FlowRaananBook
            disabled={!setupDone}
            onComplete={() => markComplete(2)}
          />
          <FlowYakiDenied
            disabled={!setupDone}
            onComplete={() => markComplete(3)}
          />
          <FlowVoteWiden
            disabled={!setupDone || !completedFlows.has(3)}
            onComplete={() => markComplete(4)}
          />
          <FlowDissolve
            disabled={!setupDone}
            onComplete={() => markComplete(5)}
          />
        </main>

        {/* Sidebar */}
        <aside className="w-96 space-y-4 flex-shrink-0">
          <StatusPanel status={status} />
          <ReceiptTimeline events={events} />
        </aside>
      </div>
    </div>
  );
}
