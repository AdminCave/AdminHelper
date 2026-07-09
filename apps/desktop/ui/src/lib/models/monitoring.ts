// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Monitoring model: sorting, filtering, grouping, formatting helpers (a few read
// the i18n language store for the "no server" label and the date/number locale).

import type { AlignedData } from 'uplot';
import type {
  MonCheckSummary,
  MonStatus,
  MonitorCheck,
  MonitorCheckType,
  MonitoringMetricSeries,
  Server,
} from '$lib/api/types';
import { tNow, currentLocale } from '$lib/i18n';

export const STATUS_PRIORITY: Record<MonStatus, number> = {
  critical: 4,
  warning: 3,
  unknown: 2,
  pending: 1,
  ok: 0,
};

export function worstStatus(checks: Array<{ state?: { status?: MonStatus } | null }>): MonStatus {
  let worst: MonStatus = 'ok';
  for (const c of checks) {
    const s: MonStatus = (c.state?.status ?? 'pending') as MonStatus;
    if ((STATUS_PRIORITY[s] ?? 0) > (STATUS_PRIORITY[worst] ?? 0)) {
      worst = s;
    }
  }
  return worst;
}

export interface ServerGroup {
  serverId: string | null;
  serverName: string;
  checks: MonitorCheck[];
}

export interface ServerGroupSummary extends ServerGroup {
  key: string;
  summary: MonitoringSummary;
  worst: MonStatus;
}

export function groupChecksByServerWithSummary(
  checks: MonitorCheck[],
  servers: Server[] = [],
  search = '',
): ServerGroupSummary[] {
  const base = groupChecksByServer(checks, servers);
  const q = search.trim().toLowerCase();
  const withSummary: ServerGroupSummary[] = base.map((g) => ({
    ...g,
    key: g.serverId ?? '__none',
    summary: computeSummary(g.checks),
    worst: worstStatus(g.checks),
  }));
  const filtered = q
    ? withSummary.filter((g) => g.serverName.toLowerCase().includes(q))
    : withSummary;
  filtered.sort((a, b) => {
    const pa = STATUS_PRIORITY[a.worst] ?? 0;
    const pb = STATUS_PRIORITY[b.worst] ?? 0;
    if (pa !== pb) return pb - pa;
    return a.serverName.localeCompare(b.serverName);
  });
  return filtered;
}

export function groupChecksByServer(checks: MonitorCheck[], servers: Server[] = []): ServerGroup[] {
  const serverMap: Record<string, Server> = {};
  for (const s of servers) serverMap[s.id] = s;
  const map = new Map<string, ServerGroup>();
  for (const c of checks) {
    const key = c.serverId || '__none';
    if (!map.has(key)) {
      const srv = c.serverId ? serverMap[c.serverId] : null;
      const serverName = srv
        ? srv.name || srv.hostname || c.serverId || ''
        : c.serverId || tNow('monitoring.server.noServer');
      map.set(key, { serverId: c.serverId ?? null, serverName, checks: [] });
    }
    map.get(key)!.checks.push(c);
  }
  const groups = Array.from(map.values());
  groups.sort((a, b) => (a.serverName || '').localeCompare(b.serverName || ''));
  return groups;
}

export interface MonitoringFilters {
  server: string;
  type: string;
  status: string;
  search: string;
}

export function filterChecks(checks: MonitorCheck[], filters: MonitoringFilters): MonitorCheck[] {
  const query = (filters.search || '').toLowerCase();
  return checks.filter((c) => {
    if (filters.server && c.serverId !== filters.server) return false;
    if (filters.type && c.checkType !== filters.type) return false;
    if (filters.status) {
      const s = (c.state?.status ?? 'pending') as string;
      if (s !== filters.status) return false;
    }
    if (query) {
      const hay =
        `${c.name} ${c.description || ''} ${c.checkType} ${c.state?.message || ''}`.toLowerCase();
      if (!hay.includes(query)) return false;
    }
    return true;
  });
}

export function statusClass(status: MonStatus | string | undefined | null): string {
  return `mon-${status || 'pending'}`;
}

export function formatCheckTime(isoStr: string | null | undefined): string {
  if (!isoStr) return '-';
  const d = new Date(isoStr);
  if (Number.isNaN(d.getTime())) return '-';
  return d.toLocaleString(currentLocale(), {
    day: '2-digit',
    month: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });
}

export function metricLabel(name: string): string {
  return name
    .replace('monitor_check_', '')
    .replace('monitor_agent_', '')
    .replace('monitor_', '')
    .replace(/_value$/, '')
    .replace(/_/g, ' ');
}

/**
 * Label a returned metric series. The agent-resources dimensional schema writes one series per
 * disk/sensor that all share the same __name__ (monitor_agent_disk_percent), distinguished only by
 * a `mount`/`sensor` tag — so appending that tag is what keeps the per-mount lines apart in the
 * chart legend and the current-values list, whose {#each} keys must be unique (1.18).
 */
export function metricSeriesLabel(metric: MonitoringMetricSeries['metric']): string {
  const base = metricLabel(metric?.__name__ || '');
  const dimension = metric?.mount ?? metric?.sensor;
  return dimension ? `${base} ${dimension}` : base;
}

export function checkTypeUnit(checkType: MonitorCheckType | string): string {
  if (['ping', 'tcp', 'http'].includes(checkType)) return 'ms';
  if (['agent_resources', 'zfs_health'].includes(checkType)) return '%';
  if (['service_process', 'proxmox_backup', 'docker_health'].includes(checkType)) return '';
  if (checkType === 'agent_ping') return 's';
  return '';
}

export function isPercentCheck(checkType: MonitorCheckType | string): boolean {
  return ['agent_resources', 'zfs_health'].includes(checkType);
}

export interface MonitoringSummary {
  total: number;
  ok: number;
  warning: number;
  critical: number;
  unknown: number;
  pending: number;
}

export function computeSummary(checks: MonCheckSummary[] | MonitorCheck[]): MonitoringSummary {
  const s: MonitoringSummary = { total: 0, ok: 0, warning: 0, critical: 0, unknown: 0, pending: 0 };
  for (const c of checks) {
    s.total += 1;
    const st = (c.state?.status ?? 'pending') as keyof MonitoringSummary;
    if (st in s && st !== 'total') s[st] += 1;
  }
  return s;
}

/**
 * Join metric series on the UNION of their timestamps so uPlot AlignedData stays correct even when
 * series have different-length or shifted point sets (a metric added later, gaps after an agent
 * restart). Returns [timestamps, ...perSeriesValues] with null where a series has no point for a
 * given timestamp (4.102).
 */
export function buildAlignedData(series: MonitoringMetricSeries[]): AlignedData {
  const timestamps = [...new Set(series.flatMap((s) => s.values.map((v) => Number(v[0]))))].sort(
    (a, b) => a - b,
  );
  const aligned: AlignedData = [timestamps];
  for (const s of series) {
    const byTs = new Map(s.values.map((v) => [Number(v[0]), parseFloat(v[1])]));
    aligned.push(
      timestamps.map((ts) => {
        const n = byTs.get(ts);
        return n === undefined || Number.isNaN(n) ? null : n;
      }),
    );
  }
  return aligned;
}
