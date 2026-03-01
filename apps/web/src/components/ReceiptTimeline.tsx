import type { WsEvent } from '../api/types';
import ReceiptCard from './ReceiptCard';

export default function ReceiptTimeline({ events }: { events: WsEvent[] }) {
  return (
    <div className="bg-gray-900 rounded-lg border border-gray-800 p-4 flex flex-col" style={{ maxHeight: '60vh' }}>
      <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wider mb-3">
        Event Timeline
        {events.length > 0 && (
          <span className="ml-2 text-gray-600 normal-case">({events.length})</span>
        )}
      </h2>
      {events.length === 0 ? (
        <p className="text-sm text-gray-500">No events yet. Run a flow to start.</p>
      ) : (
        <div className="space-y-2 overflow-y-auto timeline-scroll">
          {events.map((event, i) => (
            <ReceiptCard key={i} event={event} />
          ))}
        </div>
      )}
    </div>
  );
}
