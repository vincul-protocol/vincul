import { useState } from 'react';
import { api } from '../api/client';
import type { ActionResult, VoteSessionResult } from '../api/types';
import { YAKI_ACCOMMODATION_ID } from '../api/types';
import FlowRunner from './FlowRunner';

interface Props {
  disabled: boolean;
  onComplete: () => void;
}

const VOTERS = ['principal:alice', 'principal:bob', 'principal:carol', 'principal:dan', 'principal:eve'];

type Step = 'idle' | 'voting' | 'voted' | 'rebooking' | 'done';

export default function FlowVoteWiden({ disabled, onComplete }: Props) {
  const [step, setStep] = useState<Step>('idle');
  const [voteSession, setVoteSession] = useState<VoteSessionResult | null>(null);
  const [votesCompleted, setVotesCompleted] = useState(0);
  const [rebookResult, setRebookResult] = useState<ActionResult | null>(null);

  const run = async () => {
    // Step 1: Open vote
    setStep('voting');
    const session = await api.openVote({
      scope_id: YAKI_ACCOMMODATION_ID,
      request: 'Widen Yaki accommodation scope to include COMMIT',
      requested_types: ['OBSERVE', 'PROPOSE', 'COMMIT'],
      requested_ceiling: 'action.params.cost <= 1500',
    });
    setVoteSession(session);

    // Step 2: Cast 5 votes sequentially
    let latest = session;
    for (let i = 0; i < VOTERS.length; i++) {
      latest = await api.castVote(session.vote_id, VOTERS[i]);
      setVoteSession(latest);
      setVotesCompleted(i + 1);
    }
    setStep('voted');

    // Step 3: Rebook with new scope
    if (latest.new_scope_id) {
      setStep('rebooking');
      const r = await api.performAction({
        principal: 'principal:yaki',
        scope_id: latest.new_scope_id,
        action: {
          type: 'COMMIT',
          namespace: 'travel.accommodation',
          resource: 'hotel:hilton-tlv',
          params: { cost: 450 },
        },
        budget_amounts: { EUR: '450.00' },
      });
      setRebookResult(r);
    }

    setStep('done');
    onComplete();
  };

  return (
    <FlowRunner
      number={4}
      title="Vote to Widen Scope + Rebook"
      description="Governance vote (5/8 threshold) grants Yaki COMMIT, then rebook succeeds"
      assertion="Bounded Delegation"
      disabled={disabled}
      onRun={run}
      result={
        step !== 'idle' && (
          <div className="space-y-3">
            {/* Vote progress */}
            <div className="bg-gray-800/50 rounded p-3">
              <div className="text-xs text-gray-500 mb-2">Governance Vote</div>
              <div className="flex items-center gap-2 mb-2">
                <div className="flex-1 bg-gray-700 rounded-full h-2">
                  <div
                    className="bg-blue-500 h-2 rounded-full transition-all duration-300"
                    style={{ width: `${(votesCompleted / 5) * 100}%` }}
                  />
                </div>
                <span className="text-sm text-gray-300">
                  {votesCompleted}/5
                </span>
              </div>
              <div className="flex flex-wrap gap-1">
                {VOTERS.map((v, i) => (
                  <span
                    key={v}
                    className={`px-2 py-0.5 rounded text-xs ${
                      i < votesCompleted
                        ? 'bg-blue-900 text-blue-300'
                        : 'bg-gray-700 text-gray-500'
                    }`}
                  >
                    {v.split(':')[1]}
                  </span>
                ))}
              </div>
              {voteSession?.resolved && (
                <div className="mt-2 text-xs text-green-400">
                  Vote passed -- new scope delegated
                </div>
              )}
            </div>

            {/* Delegation receipt */}
            {voteSession?.delegation_receipt && (
              <div className="bg-purple-900/20 border border-purple-800 rounded p-3">
                <div className="flex items-center gap-2 mb-1">
                  <span className="px-1.5 py-0.5 bg-purple-900 text-purple-300 rounded text-xs font-medium">
                    delegation
                  </span>
                  <span className="text-xs text-green-400">
                    {voteSession.delegation_receipt.outcome}
                  </span>
                </div>
                <div className="text-sm text-gray-300">
                  New scope:{' '}
                  <span className="font-mono text-xs">
                    {voteSession.new_scope_id}
                  </span>
                </div>
              </div>
            )}

            {/* Rebook result */}
            {rebookResult && (
              <div
                className={`rounded p-3 ${
                  rebookResult.outcome === 'success'
                    ? 'bg-green-900/20 border border-green-800'
                    : 'bg-red-900/20 border border-red-800'
                }`}
              >
                <div className="flex items-center gap-2 mb-1">
                  <span
                    className={`text-sm font-medium ${
                      rebookResult.outcome === 'success'
                        ? 'text-green-400'
                        : 'text-red-400'
                    }`}
                  >
                    {rebookResult.outcome === 'success'
                      ? 'Yaki Rebooked Successfully'
                      : 'Rebook Failed'}
                  </span>
                </div>
                <div className="text-sm text-gray-300">
                  {rebookResult.summary}
                </div>
                <div className="mt-1 text-xs text-gray-500 font-mono">
                  receipt: {rebookResult.receipt_hash.slice(0, 16)}...
                </div>
              </div>
            )}

            {step === 'voting' && (
              <div className="text-sm text-gray-400">Casting votes...</div>
            )}
            {step === 'rebooking' && (
              <div className="text-sm text-gray-400">Rebooking with widened scope...</div>
            )}
          </div>
        )
      }
    />
  );
}
