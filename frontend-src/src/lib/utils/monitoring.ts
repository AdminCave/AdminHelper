import type { MonCheckSummary, MonStatus } from '$lib/api/types';

const ORDER: Record<MonStatus, number> = {
  critical: 4,
  warning: 3,
  unknown: 2,
  pending: 1,
  ok: 0,
};

export function worstStatusForServer(
  checks: MonCheckSummary[],
  serverId: string,
): MonStatus | null {
  const matching = checks.filter((c) => c.serverId === serverId);
  if (matching.length === 0) return null;
  let worst: MonStatus = 'ok';
  for (const c of matching) {
    const s: MonStatus = c.state?.status ?? 'pending';
    if (ORDER[s] > ORDER[worst]) worst = s;
  }
  return worst;
}
