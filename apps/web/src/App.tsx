import { useState, useCallback, useEffect, useRef } from 'react';
import type { WsEvent } from './api/types';
import { api } from './api/client';
import { useWebSocket } from './hooks/useWebSocket';
import { useDemoState } from './hooks/useDemoState';
import Header from './components/Header';
import ContractOverview from './components/ContractOverview';
import StakeholderGrid from './components/StakeholderGrid';
import StatusPanel from './components/StatusPanel';
import ReceiptTimeline from './components/ReceiptTimeline';
import AgentMessageFlow from './components/AgentMessageFlow';
import FlowSetup from './components/FlowSetup';
import FlowRaananBook from './components/FlowRaananBook';
import FlowYakiDenied from './components/FlowYakiDenied';
import FlowVoteWiden from './components/FlowVoteWiden';
import FlowDissolve from './components/FlowDissolve';

export default function App() {
  const [events, setEvents] = useState<WsEvent[]>([]);
  const [completedFlows, setCompletedFlows] = useState<Set<number>>(new Set());
  const [animatingCards, setAnimatingCards] = useState<Set<string>>(new Set());
  const { status, state, refresh, setStatus, setState } = useDemoState();
  const cardRefs = useRef<Map<string, HTMLDivElement>>(new Map());

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
    setAnimatingCards(new Set());
    setStatus(null);
    setState(null);
    await refresh();
  }, [refresh, setStatus, setState]);

  // Animation callbacks for failure pulse
  const handlePulseCard = useCallback((principalId: string) => {
    setAnimatingCards((prev) => new Set(prev).add(principalId));
  }, []);

  const handlePulseEnd = useCallback((principalId: string) => {
    setAnimatingCards((prev) => {
      const next = new Set(prev);
      next.delete(principalId);
      return next;
    });
  }, []);

  const setupDone = completedFlows.has(1);

  return (
    <div className="min-h-screen bg-gray-950 text-gray-100">
      <Header status={status} onReset={handleReset} />

      {/* Full-width section under header: contract + stakeholders */}
      <div className="px-6 pt-6 pb-2 max-w-screen-2xl mx-auto space-y-4">
        <ContractOverview state={state} />
        <StakeholderGrid
          state={state}
          cardRefs={cardRefs}
          animatingCards={animatingCards}
        />
      </div>

      <div className="flex gap-6 px-6 pb-6 max-w-screen-2xl mx-auto">
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

      {/* Animation overlay */}
      <AgentMessageFlow
        events={events}
        cardRefs={cardRefs}
        state={state}
        onPulseCard={handlePulseCard}
        onPulseEnd={handlePulseEnd}
      />
    </div>
  );
}
