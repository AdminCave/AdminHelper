// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Monitoring model: pure functions for sorting, filtering, grouping, formatting.

import type {
  MonCheckSummary,
  MonStatus,
  MonitorCheck,
  MonitorCheckConfig,
  MonitorCheckType,
  Server,
} from '$lib/api/types';

const STATUS_PRIORITY: Record<MonStatus, number> = {
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
        : c.serverId || 'Ohne Server';
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
  return d.toLocaleString('de-DE', {
    day: '2-digit',
    month: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });
}

type KV = [string, string | number];

export function formatCheckConfig(check: MonitorCheck): KV[] {
  const c = (check.config ?? {}) as MonitorCheckConfig & Record<string, unknown>;
  const type = check.checkType;
  const kv: KV[] = [];

  if (type === 'ping') {
    kv.push(['Ziel', String(c.target ?? '')], ['Timeout', `${(c.timeout as number) || 5}s`]);
  } else if (type === 'tcp') {
    kv.push(
      ['Ziel', `${c.target ?? ''}:${c.port ?? ''}`],
      ['Timeout', `${(c.timeout as number) || 5}s`],
    );
  } else if (type === 'http') {
    kv.push(
      ['URL', String(c.url ?? '')],
      ['Methode', String(c.method ?? 'GET')],
      ['Expected', (c.expected_status as number) ?? 200],
    );
    if ((c as Record<string, unknown>).verify_ssl === false) kv.push(['SSL', 'deaktiviert']);
    if (c.search_string) kv.push(['Suchtext', String(c.search_string)]);
  } else if (type === 'agent_ping') {
    kv.push(['Stale-Schwelle', `${(c.stale_minutes as number) || 5} min`]);
  } else if (type === 'agent_resources') {
    kv.push(
      ['CPU', `Warn ${(c.cpu_warn as number) || 80}% / Crit ${(c.cpu_crit as number) || 95}%`],
      [
        'RAM',
        `Warn ${(c.memory_warn as number) || 80}% / Crit ${(c.memory_crit as number) || 95}%`,
      ],
      ['Disk', `Warn ${(c.disk_warn as number) || 85}% / Crit ${(c.disk_crit as number) || 95}%`],
    );
  } else if (type === 'service_process') {
    kv.push(['Modus', String(c.mode ?? 'auto')]);
    const services = c.services as string[] | undefined;
    const ignore = c.ignore as string[] | undefined;
    if (services?.length) kv.push(['Services', services.join(', ')]);
    if (ignore?.length) kv.push(['Ignoriert', ignore.join(', ')]);
  } else if (type === 'proxmox_backup') {
    kv.push(['Max. Alter', `${(c.max_backup_age_hours as number) || 26}h`]);
    const excl = c.exclude_vmids as Array<string | number> | undefined;
    if (excl?.length) kv.push(['Exclude VMIDs', excl.join(', ')]);
  } else if (type === 'zfs_health') {
    kv.push([
      'Kapazität',
      `Warn ${(c.capacity_warn as number) || 80}% / Crit ${(c.capacity_crit as number) || 90}%`,
    ]);
  } else if (type === 'docker_health') {
    const ign = c.ignore_containers as string[] | undefined;
    if (ign?.length) kv.push(['Ignoriert', ign.join(', ')]);
    kv.push([
      'Restart-Check',
      (c as Record<string, unknown>).check_restarts !== false ? 'aktiv' : 'aus',
    ]);
  } else if (type === 'smart_health') {
    kv.push(
      [
        'Realloc',
        `Warn ${(c.reallocated_warn as number) ?? 1} / Crit ${(c.reallocated_crit as number) ?? 10}`,
      ],
      [
        'Pending',
        `Warn ${(c.pending_warn as number) ?? 1} / Crit ${(c.pending_crit as number) ?? 5}`,
      ],
      [
        'NVMe Spare',
        `Warn <${(c.nvme_spare_warn as number) ?? 20}% / Crit <${(c.nvme_spare_crit as number) ?? 10}%`,
      ],
      [
        'NVMe Wear',
        `Warn ${(c.nvme_used_warn as number) ?? 90}% / Crit ${(c.nvme_used_crit as number) ?? 100}%`,
      ],
      [
        'Temp HDD',
        `Warn ${(c.temp_hdd_warn as number) ?? 55}\u00b0C / Crit ${(c.temp_hdd_crit as number) ?? 60}\u00b0C`,
      ],
      [
        'Temp SSD',
        `Warn ${(c.temp_ssd_warn as number) ?? 60}\u00b0C / Crit ${(c.temp_ssd_crit as number) ?? 70}\u00b0C`,
      ],
      [
        'Temp NVMe',
        `Warn ${(c.temp_nvme_warn as number) ?? 65}\u00b0C / Crit ${(c.temp_nvme_crit as number) ?? 75}\u00b0C`,
      ],
    );
    const ignd = c.ignore_devices as string[] | undefined;
    if (ignd?.length) kv.push(['Ignoriert', ignd.join(', ')]);
  }

  return kv;
}

export function metricLabel(name: string): string {
  return name
    .replace('monitor_check_', '')
    .replace('monitor_agent_', '')
    .replace('monitor_', '')
    .replace(/_value$/, '')
    .replace(/_/g, ' ');
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
