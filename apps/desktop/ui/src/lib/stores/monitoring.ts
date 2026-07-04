// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Monitoring store: holds checks, servers, filters, alert rules, alert log.
// Auto-refresh via activate()/deactivate() from the monitoring page.

import { errMsg, SESSION_EXPIRED } from '$lib/utils/errors';
import { writable, derived, get } from 'svelte/store';
import { sessionStore } from './session';
import { reportError, showStatus } from './statusBar';
import { monitoringApi } from '$lib/api/monitoring';
import { filterChecks, type MonitoringFilters } from '$lib/models/monitoring';
import { tNow } from '$lib/i18n';
import type {
  AlertLogEntry,
  AlertRule,
  AlertRuleInput,
  MonitorCheck,
  MonitoringTemplateFull,
  MonitoringTemplateInput,
  Server,
} from '$lib/api/types';

export type MonitoringTab = 'overview' | 'alerts' | 'templates' | 'log';

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
  templates: MonitoringTemplateFull[];
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
  templates: [],
  log: [],
  filters: { server: '', type: '', status: '', search: '' },
  loading: false,
  expandedCheckId: null,
  selectedServerId: null,
  serverSearch: '',
};

const _state = writable<MonitoringState>(initial);
export const monitoring = { subscribe: _state.subscribe };

// Generation token guarding against out-of-order status loads: the auto-refresh
// interval, runCheck's delayed reload, toggleCheck and the initial load can all
// be in flight at once. Each fresh load bumps the token and captures its value;
// a load whose token is stale by the time it resolves must not overwrite the
// state a newer load already wrote.
let statusGen = 0;
export const monitoringTab = derived(_state, ($s) => $s.tab);
export const monitoringFilters = derived(_state, ($s) => $s.filters);
export const monitoringChecks = derived(_state, ($s) => $s.checks);
export const monitoringServers = derived(_state, ($s) => $s.servers);
export const monitoringAlerts = derived(_state, ($s) => $s.alerts);
export const monitoringTemplates = derived(_state, ($s) => $s.templates);
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
  else if (tab === 'templates') void loadTemplates();
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
  } catch (err) {
    _state.update((s) => ({ ...s, servers: [] }));
    const msg = errMsg(err);
    if (msg !== SESSION_EXPIRED) reportError(tNow('error.monitoring', { message: msg }));
  }
}

export async function loadMonitoring(): Promise<void> {
  const session = requireSession();
  if (!session) return;
  const gen = ++statusGen;
  try {
    _state.update((s) => ({ ...s, loading: true }));
    const checks = await monitoringApi.fetchStatus(session);
    if (gen !== statusGen) return;
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
    if (gen !== statusGen) return;
    _state.update((s) => ({ ...s, checks: [], loading: false }));
    const msg = errMsg(err);
    if (msg !== SESSION_EXPIRED) reportError(tNow('error.monitoring', { message: msg }));
  }
}

export async function loadAlerts(): Promise<void> {
  const session = requireSession();
  if (!session) return;
  try {
    const alerts = await monitoringApi.fetchAlerts(session);
    _state.update((s) => ({ ...s, alerts }));
  } catch (err) {
    _state.update((s) => ({ ...s, alerts: [] }));
    const msg = errMsg(err);
    if (msg !== SESSION_EXPIRED) reportError(tNow('error.monitoring', { message: msg }));
  }
}

export async function loadAlertLog(): Promise<void> {
  const session = requireSession();
  if (!session) return;
  try {
    const log = await monitoringApi.fetchAlertLog(session, 50);
    _state.update((s) => ({ ...s, log }));
  } catch (err) {
    _state.update((s) => ({ ...s, log: [] }));
    const msg = errMsg(err);
    if (msg !== SESSION_EXPIRED) reportError(tNow('error.monitoring', { message: msg }));
  }
}

export async function toggleCheck(checkId: string): Promise<void> {
  const session = requireSession();
  if (!session) return;
  try {
    await monitoringApi.toggleCheck(session, checkId);
    await loadMonitoring();
  } catch (err) {
    reportError(errMsg(err));
  }
}

export async function runCheck(checkId: string): Promise<void> {
  const session = requireSession();
  if (!session) return;
  try {
    await monitoringApi.runCheck(session, checkId);
    setTimeout(() => void loadMonitoring(), 2000);
  } catch (err) {
    reportError(errMsg(err));
  }
}

export async function toggleAlert(ruleId: string): Promise<void> {
  const session = requireSession();
  if (!session) return;
  try {
    await monitoringApi.toggleAlert(session, ruleId);
    await loadAlerts();
  } catch (err) {
    reportError(errMsg(err));
  }
}

// ── Alert rule CRUD ──────────────────────────────────────────────────────────
export async function saveAlert(input: AlertRuleInput, id: string | null): Promise<boolean> {
  const session = requireSession();
  if (!session) return false;
  try {
    if (id) await monitoringApi.updateAlert(session, id, input);
    else await monitoringApi.createAlert(session, input);
    showStatus(tNow(id ? 'monitoring.alertEdit.updated' : 'monitoring.alertEdit.created'));
    await loadAlerts();
    return true;
  } catch (err) {
    reportError(errMsg(err));
    return false;
  }
}

export async function deleteAlert(id: string): Promise<boolean> {
  const session = requireSession();
  if (!session) return false;
  try {
    await monitoringApi.removeAlert(session, id);
    showStatus(tNow('monitoring.alertEdit.deleted'));
    await loadAlerts();
    return true;
  } catch (err) {
    reportError(errMsg(err));
    return false;
  }
}

// ── Monitoring template CRUD ─────────────────────────────────────────────────
export async function loadTemplates(): Promise<void> {
  const session = requireSession();
  if (!session) return;
  try {
    const templates = await monitoringApi.fetchTemplates(session);
    _state.update((s) => ({ ...s, templates: Array.isArray(templates) ? templates : [] }));
  } catch (err) {
    _state.update((s) => ({ ...s, templates: [] }));
    const msg = errMsg(err);
    if (msg !== SESSION_EXPIRED) reportError(tNow('error.monitoring', { message: msg }));
  }
}

export async function saveTemplate(
  input: MonitoringTemplateInput,
  id: string | null,
): Promise<boolean> {
  const session = requireSession();
  if (!session) return false;
  try {
    if (id) await monitoringApi.updateTemplate(session, id, input);
    else await monitoringApi.createTemplate(session, input);
    showStatus(tNow(id ? 'monitoring.tplEdit.updated' : 'monitoring.tplEdit.created'));
    await loadTemplates();
    return true;
  } catch (err) {
    reportError(errMsg(err));
    return false;
  }
}

export async function deleteTemplate(id: string): Promise<boolean> {
  const session = requireSession();
  if (!session) return false;
  try {
    await monitoringApi.removeTemplate(session, id);
    showStatus(tNow('monitoring.tplEdit.deleted'));
    await loadTemplates();
    return true;
  } catch (err) {
    reportError(errMsg(err));
    return false;
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
