import type { DemoStatus } from '../api/types';

const statusColors: Record<string, string> = {
  active: 'bg-green-600',
  draft: 'bg-yellow-600',
  dissolved: 'bg-gray-600',
};

interface Props {
  status: DemoStatus | null;
  onReset: () => void;
}

export default function Header({ status, onReset }: Props) {
  const contractStatus = status?.contract.status ?? 'none';

  return (
    <header className="bg-gray-900 border-b border-gray-800 px-6 py-4 flex items-center justify-between">
      <div className="flex items-center gap-4">
        <h1 className="text-xl font-bold text-white tracking-tight">
          Pact Protocol Demo
        </h1>
        <span className="text-sm text-gray-400">8-Friends Trip to Italy</span>
      </div>

      <div className="flex items-center gap-4">
        {status && (
          <div className="flex items-center gap-2 text-sm">
            <span className="text-gray-400">Contract:</span>
            <span
              className={`px-2 py-0.5 rounded text-xs font-medium text-white ${
                statusColors[contractStatus] ?? 'bg-gray-700'
              }`}
            >
              {contractStatus}
            </span>
            <span className="text-gray-500">
              | {status.receipt_count} receipts
            </span>
          </div>
        )}
        <button
          onClick={onReset}
          className="px-3 py-1.5 text-sm bg-gray-800 hover:bg-gray-700 rounded border border-gray-700 transition-colors"
        >
          Reset Demo
        </button>
      </div>
    </header>
  );
}
