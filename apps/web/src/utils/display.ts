/**
 * Display translation utilities.
 *
 * All formatting of protocol identifiers into human-readable
 * strings lives here. Components import from this file —
 * no inline formatting in JSX.
 */

/** "principal:raanan" → "Raanan" */
export function principalName(principalId: string): string {
  const raw = principalId.split(':')[1] ?? principalId;
  return raw.charAt(0).toUpperCase() + raw.slice(1);
}

/** "principal:raanan" → "Raanan's agent" */
export function displayName(principalId: string): string {
  return `${principalName(principalId)}'s agent`;
}

/** "travel.flights" → "travel flights" */
export function displayNamespace(namespace: string): string {
  return namespace.replace(/\./g, ' ');
}

/** "travel.flights" → "flights scope · travel.flights" */
export function displayNamespaceFull(namespace: string): string {
  const parts = namespace.split('.');
  const last = parts[parts.length - 1];
  return `${last} scope \u00b7 ${namespace}`;
}

/**
 * Human-readable ceiling.
 * "TOP" → "No ceiling (full authority)"
 * "action.params.cost <= 1500" → "\u2264 \u20ac1,500 EUR per booking"
 * "BOTTOM" → "No actions permitted"
 */
export function displayCeiling(ceiling: string): string {
  if (ceiling === 'TOP') return 'No ceiling (full authority)';
  if (ceiling === 'BOTTOM') return 'No actions permitted';
  const match = ceiling.match(/action\.params\.(\w+)\s*<=\s*(\d+)/);
  if (match) {
    const value = Number(match[2]);
    return `\u2264 \u20ac${value.toLocaleString()} EUR`;
  }
  return ceiling;
}

/**
 * Truncated hash: first 4 + "..." + last 4.
 * "abcdef1234567890abcdef" → "abcd\u2026cdef"
 */
export function truncateHash(hash: string): string {
  if (hash.length <= 12) return hash;
  return `${hash.slice(0, 4)}\u2026${hash.slice(-4)}`;
}

/** Scope ID to human label for receipt cards */
export function displayScopeLabel(scopeId: string | null | undefined, namespace?: string): string {
  if (!scopeId) return 'unknown scope';
  if (namespace) return displayNamespaceFull(namespace);
  return `scope ${truncateHash(scopeId)}`;
}

/** Receipt summary one-liner for timeline */
export function receiptSummary(
  receiptKind: string,
  initiatedBy: string,
  outcome: string,
  detail: Record<string, unknown>,
): string {
  const who = displayName(initiatedBy);
  switch (receiptKind) {
    case 'commitment':
      return `${who} committed successfully`;
    case 'failure': {
      const code = detail?.error_code;
      return `${who} denied${code ? `: ${String(code)}` : ''}`;
    }
    case 'delegation':
      return `${who} delegated a new scope`;
    case 'revocation':
      return `${who} revoked scope`;
    case 'contract_dissolution':
      return `${who} dissolved the contract`;
    default:
      return `${who}: ${outcome}`;
  }
}
