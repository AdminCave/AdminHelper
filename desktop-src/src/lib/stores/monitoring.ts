// Monitoring-Store: haelt Checks, Server, Filter, Alert-Rules, Alert-Log.
// Auto-Refresh via activate()/deactivate() aus der Monitoring-Seite.

import { writable, derived, get } from 'svelte/store';
import { sessionStore } from './session';
import { reportError } from './statusBar';
import { monitoringApi } from '$lib/api/monitoring';
import { filterChecks, type MonitoringFilters } from '$lib/models/monitoring';
import type { AlertLogEntry, AlertRule, MonitorCheck, Server } from '$lib/api/types';

export type MonitoringTab = 'overview' | 'alerts' | 'log';

interface MonitoringState {
  tab: MonitoringTab;
  servers: Server[];
  checks: MonitorCheck[];
  alerts: AlertRule[];
  log: AlertLogEntry[];
  filters: MonitoringFilters;
  loading: boolean;
  expandedCheckId: string | null;
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
};

const _state = writable<MonitoringState>(initial);
export const monitoring = { subscribe: _state.subscribe };
export const monitoringTab = derived(_state, ($s) => $s.tab);
export const monitoringFilters = derived(_state, ($s) => $s.filters);
export const monitoringChecks = derived(_state, ($s) => $s.checks);
export const monitoringServers = derived(_state, ($s) => $s.servers);
export const monitoringAlerts = derived(_state, ($s) => $s.alerts);
export const monitoringLog = derived(_state, ($s) => $s.log);

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

export function setFilter<K extends keyof MonitoringFilters>(key: K, value: MonitoringFilters[K]): void {
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
    _state.update((s) => ({ ...s, checks, loading: false }));
  } catch (err) {
    _state.update((s) => ({ ...s, checks: [], loading: false }));
    const msg = err instanceof Error ? err.message : String(err);
    if (msg !== 'SESSION_EXPIRED') reportError(`Monitoring: ${msg}`);
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
