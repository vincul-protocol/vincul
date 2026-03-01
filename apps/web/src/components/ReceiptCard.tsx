import { useState } from 'react';
import type { WsEvent } from '../api/types';
import { displayName, displayNamespaceFull, truncateHash, principalName } from '../utils/display';

const kindColors: Record<string, string> = {
  commitment: 'bg-green-900 text-green-300',
  failure: 'bg-red-900 text-red-300',
  delegation: 'bg-purple-900 text-purple-300',
  revocation: 'bg-amber-900 text-amber-300',
  contract_dissolution: 'bg-gray-700 text-gray-300',
};

const borderColors: Record<string, string> = {
  commitment: 'border-l-green-500',
  failure: 'border-l-amber-500',
  delegation: 'border-l-blue-500',
  revocation: 'border-l-red-500',
  contract_dissolution: 'border-l-gray-400',
};

const eventColors: Record<string, string> = {
  contract_setup: 'bg-blue-900 text-blue-300',
  vote_opened: 'bg-blue-900 text-blue-300',
  vote_cast: 'bg-blue-900/50 text-blue-400',
};

function HashDisplay({ hash }: { hash: string }) {
  const [copied, setCopied] = useState(false);

  const copy = () => {
    navigator.clipboard.writeText(hash);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  return (
    <button
      onClick={copy}
      className="font-mono text-xs text-gray-500 hover:text-gray-300 transition-colors"
      title="Copy full hash"
    >
      {copied ? 'Copied!' : truncateHash(hash)}
    </button>
  );
}

export default function ReceiptCard({ event }: { event: WsEvent }) {
  const [expanded, setExpanded] = useState(false);

  if (event.event_type === 'receipt') {
    const border = borderColors[event.receipt_kind] ?? 'border-l-gray-600';
    const ns = event.detail?.namespace as string | undefined;

    return (
      <div className={`bg-gray-800/50 rounded px-3 py-2 text-sm border-l-2 ${border}`}>
        <div className="flex items-center gap-2 mb-1">
          <span
            className={`px-1.5 py-0.5 rounded text-xs font-medium ${
              kindColors[event.receipt_kind] ?? 'bg-gray-700 text-gray-300'
            }`}
          >
            {event.receipt_kind}
          </span>
          <span className={`text-xs ${event.outcome === 'success' ? 'text-green-400' : 'text-red-400'}`}>
            {event.outcome}
          </span>
          <span className="text-xs text-gray-600 ml-auto">
            {event.issued_at.split('T')[1]?.replace('Z', '') ?? ''}
          </span>
        </div>

        {/* Initiated by — human readable */}
        <div className="text-xs text-gray-500 mb-0.5">
          {displayName(event.initiated_by)}
          {ns && (
            <span className="text-gray-600">
              {' '}&middot; {displayNamespaceFull(ns)}
            </span>
          )}
        </div>

        <div className="text-gray-300 text-sm">{event.summary}</div>
        <div className="flex items-center gap-2 mt-1">
          <HashDisplay hash={event.receipt_hash} />
          <button
            onClick={() => setExpanded(!expanded)}
            className="text-xs text-gray-500 hover:text-gray-300"
          >
            {expanded ? 'collapse' : 'detail'}
          </button>
        </div>
        {expanded && (
          <pre className="mt-2 p-2 bg-gray-900 rounded text-xs text-gray-400 overflow-x-auto">
            {JSON.stringify(event.detail, null, 2)}
          </pre>
        )}
      </div>
    );
  }

  if (event.event_type === 'vote_cast') {
    return (
      <div className="bg-gray-800/30 rounded px-3 py-1.5 text-xs border-l-2 border-l-blue-500">
        <span className={`px-1.5 py-0.5 rounded font-medium ${eventColors.vote_cast}`}>
          vote
        </span>
        <span className="text-gray-400 ml-2">
          {principalName(event.principal)} voted ({event.votes_count} total)
          {event.resolved && <span className="text-green-400 ml-1">-- passed</span>}
        </span>
      </div>
    );
  }

  if (event.event_type === 'vote_opened') {
    return (
      <div className="bg-gray-800/50 rounded px-3 py-2 text-sm border-l-2 border-l-blue-500">
        <span className={`px-1.5 py-0.5 rounded text-xs font-medium ${eventColors.vote_opened}`}>
          vote opened
        </span>
        <span className="text-gray-300 ml-2">{event.request}</span>
      </div>
    );
  }

  if (event.event_type === 'contract_setup') {
    return (
      <div className="bg-gray-800/50 rounded px-3 py-2 text-sm border-l-2 border-l-blue-500">
        <span className={`px-1.5 py-0.5 rounded text-xs font-medium ${eventColors.contract_setup}`}>
          setup
        </span>
        <span className="text-gray-300 ml-2">Contract initialized</span>
      </div>
    );
  }

  return null;
}
