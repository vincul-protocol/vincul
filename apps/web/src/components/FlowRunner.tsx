import { useState, type ReactNode } from 'react';

interface Props {
  number: number;
  title: string;
  description: string;
  assertion: string;
  disabled: boolean;
  onRun: () => Promise<void>;
  children?: ReactNode;
  result?: ReactNode;
}

const assertionColors: Record<string, string> = {
  'Bounded Delegation': 'bg-purple-900/50 text-purple-300 border-purple-800',
  'Scope Enforcement': 'bg-red-900/50 text-red-300 border-red-800',
  'Real Revocation': 'bg-amber-900/50 text-amber-300 border-amber-800',
  'Verifiable Receipts': 'bg-green-900/50 text-green-300 border-green-800',
  'Cross-Vendor Identity': 'bg-cyan-900/50 text-cyan-300 border-cyan-800',
  'Contract Integrity': 'bg-blue-900/50 text-blue-300 border-blue-800',
  'Tool Attestation': 'bg-emerald-900/50 text-emerald-300 border-emerald-800',
};

export default function FlowRunner({
  number,
  title,
  description,
  assertion,
  disabled,
  onRun,
  children,
  result,
}: Props) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [hasRun, setHasRun] = useState(false);

  const handleRun = async () => {
    setLoading(true);
    setError(null);
    try {
      await onRun();
      setHasRun(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Unknown error');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div
      className={`bg-gray-900 rounded-lg border transition-colors ${
        hasRun
          ? 'border-gray-700'
          : disabled
            ? 'border-gray-800 opacity-60'
            : 'border-gray-800 hover:border-gray-700'
      }`}
    >
      <div className="p-4">
        <div className="flex items-start justify-between mb-2">
          <div className="flex items-center gap-3">
            <span className="flex items-center justify-center w-7 h-7 rounded-full bg-gray-800 text-sm font-bold text-gray-400">
              {number}
            </span>
            <div>
              <h3 className="font-semibold text-gray-100">{title}</h3>
              <p className="text-sm text-gray-400">{description}</p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <span
              className={`text-xs px-2 py-0.5 rounded border ${
                assertionColors[assertion] ?? 'bg-gray-800 text-gray-400 border-gray-700'
              }`}
            >
              {assertion}
            </span>
            {!hasRun && (
              <button
                onClick={handleRun}
                disabled={disabled || loading}
                className="px-4 py-1.5 text-sm font-medium bg-blue-600 hover:bg-blue-500 disabled:bg-gray-700 disabled:text-gray-500 rounded transition-colors"
              >
                {loading ? 'Running...' : 'Run'}
              </button>
            )}
            {hasRun && (
              <span className="text-xs text-green-400 px-2">Done</span>
            )}
          </div>
        </div>

        {children}

        {error && (
          <div className="mt-3 p-3 bg-red-900/30 border border-red-800 rounded text-sm text-red-300">
            {error}
          </div>
        )}

        {result && (
          <div className="mt-3">{result}</div>
        )}
      </div>
    </div>
  );
}
