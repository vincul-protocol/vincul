import { useState, useCallback, useEffect, useRef } from 'react';
import type { SetupResult, WsEvent } from './api/types';
import { api } from './api/client';
import { useWebSocket } from './hooks/useWebSocket';
import { useDemoState } from './hooks/useDemoState';
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
import MarketplaceDemo from './components/MarketplaceDemo';

type DemoTab = 'trip' | 'marketplace';

export default function App() {
  const [activeTab, setActiveTab] = useState<DemoTab>('trip');
  const [events, setEvents] = useState<WsEvent[]>([]);
  const [completedFlows, setCompletedFlows] = useState<Set<number>>(new Set());
  const [animatingCards, setAnimatingCards] = useState<Set<string>>(new Set());
  const [setupResult, setSetupResult] = useState<SetupResult | null>(null);
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
    setSetupResult(null);
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
      {/* Header with tab navigation */}
      <header className="bg-gray-900 border-b border-gray-800">
        <div className="px-6 py-4 flex items-center justify-between">
          <div className="flex items-center gap-4">
            <h1 className="text-xl font-bold text-white tracking-tight">
              Vincul Protocol Demo
            </h1>
          </div>

          <div className="flex items-center gap-4">
            {activeTab === 'trip' && status && (
              <div className="flex items-center gap-2 text-sm">
                <span className="text-gray-400">Contract:</span>
                <span className={`px-2 py-0.5 rounded text-xs font-medium text-white ${
                  status.contract.status === 'active' ? 'bg-green-600' :
                  status.contract.status === 'draft' ? 'bg-yellow-600' :
                  status.contract.status === 'dissolved' ? 'bg-gray-600' : 'bg-gray-700'
                }`}>
                  {status.contract.status ?? 'none'}
                </span>
                <span className="text-gray-500">| {status.receipt_count} receipts</span>
              </div>
            )}
            {activeTab === 'trip' && (
              <button
                onClick={handleReset}
                className="px-3 py-1.5 text-sm bg-gray-800 hover:bg-gray-700 rounded border border-gray-700 transition-colors"
              >
                Reset Demo
              </button>
            )}
          </div>
        </div>

        {/* Tabs */}
        <div className="px-6 flex gap-0">
          <button
            onClick={() => setActiveTab('trip')}
            className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
              activeTab === 'trip'
                ? 'border-blue-500 text-blue-400'
                : 'border-transparent text-gray-500 hover:text-gray-300'
            }`}
          >
            8-Friends Trip
          </button>
          <button
            onClick={() => setActiveTab('marketplace')}
            className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
              activeTab === 'marketplace'
                ? 'border-blue-500 text-blue-400'
                : 'border-transparent text-gray-500 hover:text-gray-300'
            }`}
          >
            Tool Marketplace
          </button>
        </div>
      </header>

      {activeTab === 'trip' && (
        <>
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
                onComplete={(r) => { setSetupResult(r); markComplete(1); }}
              />
              <FlowRaananBook
                disabled={!setupDone}
                scopeId={setupResult?.scopes.raanan_flights ?? ''}
                onComplete={() => markComplete(2)}
              />
              <FlowYakiDenied
                disabled={!setupDone}
                scopeId={setupResult?.scopes.yaki_accommodation ?? ''}
                onComplete={() => markComplete(3)}
              />
              <FlowVoteWiden
                disabled={!setupDone || !completedFlows.has(3)}
                scopeId={setupResult?.scopes.yaki_accommodation ?? ''}
                onComplete={() => markComplete(4)}
              />
              <FlowDissolve
                disabled={!setupDone}
                scopeId={setupResult?.scopes.raanan_flights ?? ''}
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
        </>
      )}

      {activeTab === 'marketplace' && (
        <div className="px-6 py-6 max-w-screen-2xl mx-auto">
          <MarketplaceDemo onReset={() => {
            setEvents([]);
            setCompletedFlows(new Set());
            setAnimatingCards(new Set());
            setSetupResult(null);
            setStatus(null);
            setState(null);
          }} />
        </div>
      )}
    </div>
  );
}
