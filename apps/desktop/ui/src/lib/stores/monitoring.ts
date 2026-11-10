// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Monitoring store: holds checks, servers, filters, alert rules, alert log, and the
// module data of the server page (catalog, discovery, open findings).
// Auto-refresh via activate()/deactivate() from the monitoring page.

import { errMsg, isSessionExpired } from '$lib/utils/errors';
import { writable, derived, get } from 'svelte/store';
import { currentSession } from './session';
import { reportError, showStatus } from './statusBar';
import { monitoringApi } from '$lib/api/monitoring';
import {
  filterChecks,
  worstStatus,
  STATUS_PRIORITY,
  type MonitoringFilters,
} from '$lib/models/monitoring';
import { activeMaintenance } from '$lib/models/maintenance';
import { tNow } from '$lib/i18n';
import type {
  AlertLogEntry,
  AlertRule,
  AlertRuleInput,
  MaintenanceWindow,
  MonitorAdoptAllResult,
  MonitorAdoptResult,
  MonitorCatalog,
  MonitorCheck,
  MonitorDiscovery,
  MonitorFinding,
  MonitoringTemplateFull,
  MonitoringTemplateInput,
  Server,
} from '$lib/api/types';
import type { AuthSession } from '$lib/bridge/types';

export type MonitoringTab =
  | 'overview'
  | 'history'
  | 'certs'
  | 'backups'
  | 'updates'
  | 'findings'
  | 'alerts'
  | 'templates'
  | 'log';
export type OverviewView = 'list' | 'grid';

// Persisted view choice for the overview (list+detail vs tile grid).
const VIEW_STORAGE_KEY = 'ah.monitoring.view';

function initialOverviewView(): OverviewView {
  try {
    return localStorage.getItem(VIEW_STORAGE_KEY) === 'grid' ? 'grid' : 'list';
  } catch {
    return 'list';
  }
}

// Auto-refresh cadence for the monitoring page (same period as the notification poll).
const REFRESH_INTERVAL_MS = 30_000;
// Grace period after triggering a check so the server-side runner can persist the
// new state before the reload reads it back.
const RECHECK_DELAY_MS = 2000;
// pickWorstServerId's key for checks without a server: no discovery to load for it.
const NO_SERVER = '__none';

function pickWorstServerId(checks: MonitorCheck[]): string | null {
  const bySrv = new Map<string, MonitorCheck[]>();
  for (const c of checks) {
    const key = c.serverId || NO_SERVER;
    const list = bySrv.get(key);
    if (list) list.push(c);
    else bySrv.set(key, [c]);
  }
  let best: [string, number] | null = null;
  for (const [k, list] of bySrv) {
    const p = STATUS_PRIORITY[worstStatus(list)];
    if (!best || p > best[1]) best = [k, p];
  }
  return best?.[0] ?? null;
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
  // True once the FIRST status load resolved (success or failure) — the
  // overview's skeleton keys off this, not off `loading`, so the 30s refresh
  // can never flicker the empty/error states away.
  hasLoaded: boolean;
  error: string | null;
  expandedCheckId: string | null;
  selectedServerId: string | null;
  serverSearch: string;
  overviewView: OverviewView;
  maintenance: MaintenanceWindow[];
  // Static per monitoring version: loaded once per sign-in (catalogSession).
  catalog: MonitorCatalog | null;
  // Open findings of every server: the server page filters, the findings view lists all.
  findings: MonitorFinding[];
  // Like `error`: survives the refresh cycle until a load succeeds (T19).
  findingsError: string | null;
  discovery: Record<string, MonitorDiscovery>;
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
  hasLoaded: false,
  error: null,
  expandedCheckId: null,
  selectedServerId: null,
  serverSearch: '',
  overviewView: initialOverviewView(),
  maintenance: [],
  catalog: null,
  findings: [],
  findingsError: null,
  discovery: {},
};

const _state = writable<MonitoringState>(initial);
export const monitoring = { subscribe: _state.subscribe };

// Generation token guarding against out-of-order status loads: the auto-refresh
// interval, runCheck's delayed reload, toggleCheck and the initial load can all
// be in flight at once. Each fresh load bumps the token and captures its value;
// a load whose token is stale by the time it resolves must not overwrite the
// state a newer load already wrote.
let statusGen = 0;
// Same guard for the findings: the refresh and the reload after adopt/dismiss overlap.
let findingsGen = 0;
// The sign-in the catalog was loaded for; a new one loads it again.
let catalogSession: AuthSession | null = null;
export const monitoringTab = derived(_state, ($s) => $s.tab);
export const monitoringFilters = derived(_state, ($s) => $s.filters);
export const monitoringChecks = derived(_state, ($s) => $s.checks);
export const monitoringServers = derived(_state, ($s) => $s.servers);
export const monitoringAlerts = derived(_state, ($s) => $s.alerts);
export const monitoringTemplates = derived(_state, ($s) => $s.templates);
export const monitoringLog = derived(_state, ($s) => $s.log);
export const monitoringLoading = derived(_state, ($s) => $s.loading);
export const monitoringHasLoaded = derived(_state, ($s) => $s.hasLoaded);
export const monitoringError = derived(_state, ($s) => $s.error);
export const selectedServerId = derived(_state, ($s) => $s.selectedServerId);
export const monitoringServerSearch = derived(_state, ($s) => $s.serverSearch);
export const overviewView = derived(_state, ($s) => $s.overviewView);
// Servers the monitoring service knows nothing about yet — drives the
// overview's bulk-assign CTA (T32).
export const serversWithoutChecks = derived(_state, ($s) => {
  const covered = new Set($s.checks.map((c) => c.serverId).filter(Boolean));
  return $s.servers.filter((srv) => !covered.has(srv.id));
});
// Recomputed whenever the store updates — the 30s refresh cycle keeps the
// "active now" evaluation fresh enough for a badge.
export const maintenanceActive = derived(_state, ($s) =>
  activeMaintenance($s.maintenance, new Date()),
);
export const monitoringCatalog = derived(_state, ($s) => $s.catalog);
export const monitoringFindings = derived(_state, ($s) => $s.findings);
export const monitoringFindingsError = derived(_state, ($s) => $s.findingsError);
export const monitoringDiscovery = derived(_state, ($s) => $s.discovery);

export function setSelectedServer(id: string | null): void {
  _state.update((s) => ({ ...s, selectedServerId: id, expandedCheckId: null }));
  // Only while the page is active; activateMonitoring loads it for the first selection.
  if (refreshTimer && id) void loadDiscovery(id);
}

export function setServerSearch(v: string): void {
  _state.update((s) => ({ ...s, serverSearch: v }));
}

export function setOverviewView(view: OverviewView): void {
  _state.update((s) => ({ ...s, overviewView: view }));
  try {
    localStorage.setItem(VIEW_STORAGE_KEY, view);
  } catch {
    // Private mode / storage denied: the choice simply doesn't persist.
  }
}

export const filteredChecks = derived(_state, ($s) => filterChecks($s.checks, $s.filters));

export function setTab(tab: MonitoringTab): void {
  _state.update((s) => ({ ...s, tab, expandedCheckId: null }));
  if (tab === 'alerts') void loadAlerts();
  else if (tab === 'templates') void loadTemplates();
  else if (tab === 'log') void loadAlertLog();
}

/** A cross view's server link: that server's page on the overview tab. */
export function openServerPage(serverKey: string): void {
  setSelectedServer(serverKey);
  setOverviewView('list');
  setTab('overview');
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
  const session = currentSession();
  if (!session) return;
  try {
    const servers = await monitoringApi.fetchServers(session);
    _state.update((s) => ({ ...s, servers: Array.isArray(servers) ? servers : [] }));
  } catch (err) {
    _state.update((s) => ({ ...s, servers: [] }));
    const msg = errMsg(err);
    if (!isSessionExpired(err)) reportError(tNow('error.monitoring', { message: msg }));
  }
}

export async function loadMaintenanceWindows(): Promise<void> {
  const session = currentSession();
  if (!session) return;
  try {
    const windows = await monitoringApi.fetchMaintenance(session);
    _state.update((s) => ({ ...s, maintenance: Array.isArray(windows) ? windows : [] }));
  } catch {
    // Badge-only data: a failed fetch silently keeps the previous list.
  }
}

export async function loadMonitoring(): Promise<void> {
  const session = currentSession();
  if (!session) return;
  const gen = ++statusGen;
  try {
    // error is NOT cleared here: during an outage the banner must survive the
    // 30s refresh cycle instead of blinking away while the retry is in flight.
    _state.update((s) => ({ ...s, loading: true }));
    const checks = await monitoringApi.fetchStatus(session);
    if (gen !== statusGen) return;
    _state.update((s) => {
      // Auto-select: if nothing is selected yet, take the server with the worst status.
      let selected = s.selectedServerId;
      const ids = new Set(checks.map((c) => c.serverId || NO_SERVER));
      if (selected && !ids.has(selected)) selected = null;
      if (!selected && checks.length > 0) {
        selected = pickWorstServerId(checks);
      }
      return {
        ...s,
        checks,
        loading: false,
        hasLoaded: true,
        error: null,
        selectedServerId: selected,
      };
    });
  } catch (err) {
    if (gen !== statusGen) return;
    const msg = errMsg(err);
    // Inline error state instead of a toast (T19): the overview renders the
    // failure with a retry — a vanished toast is no help on the primary view.
    _state.update((s) => ({
      ...s,
      checks: [],
      loading: false,
      hasLoaded: true,
      error: isSessionExpired(err) ? null : msg,
    }));
  }
}

export async function loadCatalog(): Promise<void> {
  const session = currentSession();
  if (!session || catalogSession === session) return;
  try {
    const catalog = await monitoringApi.fetchCatalog(session);
    if (currentSession() !== session) return;
    catalogSession = session;
    _state.update((s) => ({ ...s, catalog }));
  } catch {
    // The cards fall back to their checks without figures; the next refresh tries again.
  }
}

export async function loadFindings(): Promise<void> {
  const session = currentSession();
  if (!session) return;
  const gen = ++findingsGen;
  try {
    const findings = await monitoringApi.fetchOpenFindings(session);
    if (gen !== findingsGen) return;
    _state.update((s) => ({ ...s, findings, findingsError: null }));
  } catch (err) {
    if (gen !== findingsGen) return;
    // The old list stays: an outage must not look like "nothing new found".
    _state.update((s) => ({ ...s, findingsError: isSessionExpired(err) ? null : errMsg(err) }));
  }
}

export async function loadDiscovery(serverId: string): Promise<void> {
  const session = currentSession();
  if (!session || serverId === NO_SERVER) return;
  try {
    const found = await monitoringApi.fetchDiscovery(session, serverId);
    _state.update((s) => ({ ...s, discovery: { ...s.discovery, [serverId]: found } }));
  } catch {
    // Header data (last scan, scan pending): the previous answer stays until one succeeds.
  }
}

// Scan now. The answer is the discovery with the request noted, so the button shows
// "requested" without waiting for the next load.
export async function requestScan(serverId: string): Promise<boolean> {
  const session = currentSession();
  if (!session) return false;
  try {
    const found = await monitoringApi.requestScan(session, serverId);
    _state.update((s) => ({ ...s, discovery: { ...s.discovery, [serverId]: found } }));
    return true;
  } catch (err) {
    reportError(errMsg(err));
    return false;
  }
}

// Adopting creates or switches the instance's checks: both lists change. The result
// (skipped checks and why) is for the caller to show; null after a reported failure.
export async function adoptFinding(findingId: string): Promise<MonitorAdoptResult | null> {
  const session = currentSession();
  if (!session) return null;
  try {
    const result = await monitoringApi.adoptFinding(session, findingId);
    await Promise.all([loadMonitoring(), loadFindings()]);
    return result;
  } catch (err) {
    reportError(errMsg(err));
    return null;
  }
}

// A finding that fails stays open and is named in `failed`; the others are adopted.
export async function adoptAllFindings(serverId: string): Promise<MonitorAdoptAllResult | null> {
  const session = currentSession();
  if (!session) return null;
  try {
    const result = await monitoringApi.adoptAllFindings(session, serverId);
    await Promise.all([loadMonitoring(), loadFindings()]);
    return result;
  } catch (err) {
    reportError(errMsg(err));
    return null;
  }
}

// Dismissing touches no check, only the finding.
export async function dismissFinding(findingId: string): Promise<boolean> {
  const session = currentSession();
  if (!session) return false;
  try {
    await monitoringApi.dismissFinding(session, findingId);
    await loadFindings();
    return true;
  } catch (err) {
    reportError(errMsg(err));
    return false;
  }
}

// The module data of the server page, after a status load picked the selection.
function loadModuleData(): void {
  void loadCatalog();
  void loadFindings();
  const selected = get(_state).selectedServerId;
  if (selected) void loadDiscovery(selected);
}

export async function loadAlerts(): Promise<void> {
  const session = currentSession();
  if (!session) return;
  try {
    const alerts = await monitoringApi.fetchAlerts(session);
    _state.update((s) => ({ ...s, alerts }));
  } catch (err) {
    _state.update((s) => ({ ...s, alerts: [] }));
    const msg = errMsg(err);
    if (!isSessionExpired(err)) reportError(tNow('error.monitoring', { message: msg }));
  }
}

export async function loadAlertLog(): Promise<void> {
  const session = currentSession();
  if (!session) return;
  try {
    const log = await monitoringApi.fetchAlertLog(session, 50);
    _state.update((s) => ({ ...s, log }));
  } catch (err) {
    _state.update((s) => ({ ...s, log: [] }));
    const msg = errMsg(err);
    if (!isSessionExpired(err)) reportError(tNow('error.monitoring', { message: msg }));
  }
}

export async function toggleCheck(checkId: string): Promise<void> {
  const session = currentSession();
  if (!session) return;
  try {
    await monitoringApi.toggleCheck(session, checkId);
    await loadMonitoring();
  } catch (err) {
    reportError(errMsg(err));
  }
}

export async function runCheck(checkId: string): Promise<void> {
  const session = currentSession();
  if (!session) return;
  try {
    await monitoringApi.runCheck(session, checkId);
    if (runReloadTimer) clearTimeout(runReloadTimer);
    runReloadTimer = setTimeout(() => void loadMonitoring(), RECHECK_DELAY_MS);
  } catch (err) {
    reportError(errMsg(err));
  }
}

// Drops the user's changes to a template check. The answer is the check as it is now,
// so its line shows the template's values without waiting for the next status load.
export async function resetCheck(checkId: string): Promise<void> {
  const session = currentSession();
  if (!session) return;
  try {
    const updated = await monitoringApi.resetCheck(session, checkId);
    _state.update((s) => ({
      ...s,
      checks: s.checks.map((c) => (c.id === updated.id ? updated : c)),
    }));
  } catch (err) {
    reportError(errMsg(err));
  }
}

export async function toggleAlert(ruleId: string): Promise<void> {
  const session = currentSession();
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
  const session = currentSession();
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
  const session = currentSession();
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

// ── Check editor modal (T18) ─────────────────────────────────────────────────
// Store-driven so MonCheckLine (nested in the type sections) can open the
// editor without threading callbacks through every section component.
interface CheckEditorState {
  open: boolean;
  target: MonitorCheck | null;
  serverId: string;
}
const _checkEditor = writable<CheckEditorState>({ open: false, target: null, serverId: '' });
export const checkEditor = { subscribe: _checkEditor.subscribe };

export function openCheckEditor(target: MonitorCheck | null, serverId: string): void {
  _checkEditor.set({ open: true, target, serverId });
}

export function closeCheckEditor(): void {
  _checkEditor.set({ open: false, target: null, serverId: '' });
}

// ── Monitoring template CRUD ─────────────────────────────────────────────────
export async function loadTemplates(): Promise<void> {
  const session = currentSession();
  if (!session) return;
  try {
    const templates = await monitoringApi.fetchTemplates(session);
    _state.update((s) => ({ ...s, templates: Array.isArray(templates) ? templates : [] }));
  } catch (err) {
    _state.update((s) => ({ ...s, templates: [] }));
    const msg = errMsg(err);
    if (!isSessionExpired(err)) reportError(tNow('error.monitoring', { message: msg }));
  }
}

export async function saveTemplate(
  input: MonitoringTemplateInput,
  id: string | null,
): Promise<boolean> {
  const session = currentSession();
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
  const session = currentSession();
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

// ── Template assignments (server, bulk, tag) ─────────────────────────────────
export async function assignTemplateToServers(
  templateId: string,
  servers: { id: string; hostname: string; name: string }[],
): Promise<boolean> {
  const session = currentSession();
  if (!session || servers.length === 0) return false;
  // Sequential on purpose: each assign materializes checks server-side; a
  // failed one is reported individually and must not abort the rest.
  let failed = 0;
  for (const srv of servers) {
    try {
      await monitoringApi.assignTemplate(session, templateId, srv.id, srv.hostname, srv.name);
    } catch (err) {
      failed += 1;
      reportError(errMsg(err));
    }
  }
  await loadTemplates();
  if (failed === 0) {
    showStatus(tNow('monitoring.tplEdit.assigned', { count: String(servers.length) }));
  }
  return failed === 0;
}

export async function unassignTemplateFromServer(
  templateId: string,
  serverId: string,
): Promise<boolean> {
  const session = currentSession();
  if (!session) return false;
  try {
    await monitoringApi.unassignTemplate(session, templateId, serverId);
    showStatus(tNow('monitoring.tplEdit.unassigned'));
    await loadTemplates();
    return true;
  } catch (err) {
    reportError(errMsg(err));
    return false;
  }
}

export async function assignTagToTemplate(templateId: string, tag: string): Promise<boolean> {
  const session = currentSession();
  if (!session) return false;
  try {
    await monitoringApi.assignTemplateTag(session, templateId, tag);
    showStatus(tNow('monitoring.tplEdit.tagAssigned', { tag }));
    await loadTemplates();
    return true;
  } catch (err) {
    reportError(errMsg(err));
    return false;
  }
}

export async function removeTagFromTemplate(templateId: string, tag: string): Promise<boolean> {
  const session = currentSession();
  if (!session) return false;
  try {
    await monitoringApi.unassignTemplateTag(session, templateId, tag);
    showStatus(tNow('monitoring.tplEdit.tagRemoved', { tag }));
    await loadTemplates();
    return true;
  } catch (err) {
    reportError(errMsg(err));
    return false;
  }
}

let refreshTimer: ReturnType<typeof setInterval> | null = null;
// The post-run reload timer (runCheck) — tracked so deactivateMonitoring can cancel it, else a
// full /status request fires ~2 s after the user already left the monitoring page (4.105).
let runReloadTimer: ReturnType<typeof setTimeout> | null = null;

export function activateMonitoring(): void {
  void loadServers()
    .then(() => loadMonitoring())
    .then(loadModuleData);
  void loadMaintenanceWindows();
  if (refreshTimer) clearInterval(refreshTimer);
  refreshTimer = setInterval(() => {
    void loadMonitoring().then(loadModuleData);
    void loadMaintenanceWindows();
  }, REFRESH_INTERVAL_MS);
}

export function deactivateMonitoring(): void {
  if (refreshTimer) {
    clearInterval(refreshTimer);
    refreshTimer = null;
  }
  if (runReloadTimer) {
    clearTimeout(runReloadTimer);
    runReloadTimer = null;
  }
  _state.update((s) => ({ ...s, expandedCheckId: null }));
}
