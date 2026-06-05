// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Monitoring store: holds checks, servers, filters, alert rules, alert log.
// Auto-refresh via activate()/deactivate() from the monitoring page.

import { writable, derived, get } from 'svelte/store';
import { sessionStore } from './session';
import { reportError } from './statusBar';
import { monitoringApi } from '$lib/api/monitoring';
import { filterChecks, type MonitoringFilters } from '$lib/models/monitoring';
import { tNow } from '$lib/i18n';
import type { AlertLogEntry, AlertRule, MonitorCheck, Server } from '$lib/api/types';

export type MonitoringTab = 'overview' | 'alerts' | 'log';

const STATUS_PRIO: Record<string, number> = {
  critical: 4,
  warning: 3,
  unknown: 2,
  pending: 1,
  ok: 0,
};

function pickWorstServerId(checks: MonitorCheck[]): string | null {
  const bySrv = new Map<string, number>();
  for (const c of checks) {
    const key = c.serverId || '__none';
    const st = (c.state?.status ?? 'pending') as string;
    const p = STATUS_PRIO[st] ?? 0;
    const cur = bySrv.get(key) ?? -1;
    if (p > cur) bySrv.set(key, p);
  }
  let bestKey: string | null = null;
  let bestP = -1;
  for (const [k, p] of bySrv) {
    if (p > bestP) {
      bestP = p;
      bestKey = k;
    }
  }
  return bestKey;
}

interface MonitoringState {
  tab: MonitoringTab;
  servers: Server[];
  checks: MonitorCheck[];
  alerts: AlertRule[];
  log: AlertLogEntry[];
  filters: MonitoringFilters;
  loading: boolean;
  expandedCheckId: string | null;
  selectedServerId: string | null;
  serverSearch: string;
}

const initial: MonitoringState = {
  tab: 'overview',
  servers: [],
  checks: [],
  alerts: [],
  log: [],
  filters: { server: '', type: '', status: '', search: '' },
  loading: false,
  expandedCheckId: null,
  selectedServerId: null,
  serverSearch: '',
};

const _state = writable<MonitoringState>(initial);
export const monitoring = { subscribe: _state.subscribe };
export const monitoringTab = derived(_state, ($s) => $s.tab);
export const monitoringFilters = derived(_state, ($s) => $s.filters);
export const monitoringChecks = derived(_state, ($s) => $s.checks);
export const monitoringServers = derived(_state, ($s) => $s.servers);
export const monitoringAlerts = derived(_state, ($s) => $s.alerts);
export const monitoringLog = derived(_state, ($s) => $s.log);
export const selectedServerId = derived(_state, ($s) => $s.selectedServerId);
export const monitoringServerSearch = derived(_state, ($s) => $s.serverSearch);

export function setSelectedServer(id: string | null): void {
  _state.update((s) => ({ ...s, selectedServerId: id, expandedCheckId: null }));
}

export function setServerSearch(v: string): void {
  _state.update((s) => ({ ...s, serverSearch: v }));
}

export const filteredChecks = derived(_state, ($s) => filterChecks($s.checks, $s.filters));

function requireSession() {
  const { session } = get(sessionStore);
  return session;
}

export function setTab(tab: MonitoringTab): void {
  _state.update((s) => ({ ...s, tab, expandedCheckId: null }));
  if (tab === 'alerts') void loadAlerts();
  else if (tab === 'log') void loadAlertLog();
}

export function setFilter<K extends keyof MonitoringFilters>(
  key: K,
  value: MonitoringFilters[K],
): void {
  _state.update((s) => ({ ...s, filters: { ...s.filters, [key]: value } }));
}

export function setExpanded(id: string | null): void {
  _state.update((s) => ({ ...s, expandedCheckId: id }));
}

export function toggleExpanded(id: string): void {
  _state.update((s) => ({
    ...s,
    expandedCheckId: s.expandedCheckId === id ? null : id,
  }));
}

export async function loadServers(): Promise<void> {
  const session = requireSession();
  if (!session) return;
  try {
    const servers = await monitoringApi.fetchServers(session);
    _state.update((s) => ({ ...s, servers: Array.isArray(servers) ? servers : [] }));
  } catch {
    _state.update((s) => ({ ...s, servers: [] }));
  }
}

export async function loadMonitoring(): Promise<void> {
  const session = requireSession();
  if (!session) return;
  try {
    _state.update((s) => ({ ...s, loading: true }));
    const checks = await monitoringApi.fetchStatus(session);
    _state.update((s) => {
      // Auto-select: if nothing is selected yet, take the server with the worst status.
      let selected = s.selectedServerId;
      const ids = new Set(checks.map((c) => c.serverId || '__none'));
      if (selected && !ids.has(selected)) selected = null;
      if (!selected && checks.length > 0) {
        selected = pickWorstServerId(checks);
      }
      return { ...s, checks, loading: false, selectedServerId: selected };
    });
  } catch (err) {
    _state.update((s) => ({ ...s, checks: [], loading: false }));
    const msg = err instanceof Error ? err.message : String(err);
    if (msg !== 'SESSION_EXPIRED') reportError(tNow('error.monitoring', { message: msg }));
  }
}

export async function loadAlerts(): Promise<void> {
  const session = requireSession();
  if (!session) return;
  try {
    const alerts = await monitoringApi.fetchAlerts(session);
    _state.update((s) => ({ ...s, alerts }));
  } catch {
    _state.update((s) => ({ ...s, alerts: [] }));
  }
}

export async function loadAlertLog(): Promise<void> {
  const session = requireSession();
  if (!session) return;
  try {
    const log = await monitoringApi.fetchAlertLog(session, 50);
    _state.update((s) => ({ ...s, log }));
  } catch {
    _state.update((s) => ({ ...s, log: [] }));
  }
}

export async function toggleCheck(checkId: string): Promise<void> {
  const session = requireSession();
  if (!session) return;
  try {
    await monitoringApi.toggleCheck(session, checkId);
    await loadMonitoring();
  } catch (err) {
    reportError(err instanceof Error ? err.message : String(err));
  }
}

export async function runCheck(checkId: string): Promise<void> {
  const session = requireSession();
  if (!session) return;
  try {
    await monitoringApi.runCheck(session, checkId);
    setTimeout(() => void loadMonitoring(), 2000);
  } catch (err) {
    reportError(err instanceof Error ? err.message : String(err));
  }
}

export async function toggleAlert(ruleId: string): Promise<void> {
  const session = requireSession();
  if (!session) return;
  try {
    await monitoringApi.toggleAlert(session, ruleId);
    await loadAlerts();
  } catch (err) {
    reportError(err instanceof Error ? err.message : String(err));
  }
}

let refreshTimer: ReturnType<typeof setInterval> | null = null;

export function activateMonitoring(): void {
  void loadServers().then(() => loadMonitoring());
  if (refreshTimer) clearInterval(refreshTimer);
  refreshTimer = setInterval(() => void loadMonitoring(), 30_000);
}

export function deactivateMonitoring(): void {
  if (refreshTimer) {
    clearInterval(refreshTimer);
    refreshTimer = null;
  }
  _state.update((s) => ({ ...s, expandedCheckId: null }));
}
