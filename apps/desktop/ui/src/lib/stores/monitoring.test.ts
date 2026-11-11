// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Monitoring store (6.42): the auto-select picks the worst-status server (pickWorstServerId /
// STATUS_PRIORITY), drops a selection whose server disappears, and the statusGen generation-token
// guard discards an out-of-order load result — a broken guard would show stale check status, the one
// thing a monitoring view must never do.

import { describe, it, expect, beforeEach, vi } from 'vitest';
import { get } from 'svelte/store';
import type { MonitorCheck, MonitorDiscovery, MonitorFinding } from '$lib/api/types';

// Hoisted mock state so the vi.mock factories (which run before imports) can close over it.
const h = vi.hoisted(() => ({
  session: { session: {}, settings: {} } as unknown,
  fetchStatus: vi.fn(),
  fetchTemplates: vi.fn(),
  assignTemplate: vi.fn(),
  unassignTemplate: vi.fn(),
  assignTemplateTag: vi.fn(),
  unassignTemplateTag: vi.fn(),
  fetchCatalog: vi.fn(),
  fetchOpenFindings: vi.fn(),
  fetchDiscovery: vi.fn(),
  requestScan: vi.fn(),
  adoptFinding: vi.fn(),
  adoptAllFindings: vi.fn(),
  dismissFinding: vi.fn(),
  reportError: vi.fn(),
  showStatus: vi.fn(),
}));

vi.mock('./session', () => ({ currentSession: () => h.session }));
vi.mock('$lib/api/monitoring', () => ({
  monitoringApi: {
    fetchStatus: h.fetchStatus,
    fetchTemplates: h.fetchTemplates,
    assignTemplate: h.assignTemplate,
    unassignTemplate: h.unassignTemplate,
    assignTemplateTag: h.assignTemplateTag,
    unassignTemplateTag: h.unassignTemplateTag,
    fetchCatalog: h.fetchCatalog,
    fetchOpenFindings: h.fetchOpenFindings,
    fetchDiscovery: h.fetchDiscovery,
    requestScan: h.requestScan,
    adoptFinding: h.adoptFinding,
    adoptAllFindings: h.adoptAllFindings,
    dismissFinding: h.dismissFinding,
  },
}));
vi.mock('./statusBar', () => ({ reportError: h.reportError, showStatus: h.showStatus }));
vi.mock('$lib/i18n', () => ({ tNow: (k: string) => k }));

import {
  loadMonitoring,
  selectedServerId,
  monitoringChecks,
  setSelectedServer,
  assignTemplateToServers,
  unassignTemplateFromServer,
  assignTagToTemplate,
  monitoringError,
  loadCatalog,
  loadFindings,
  loadDiscovery,
  requestScan,
  adoptFinding,
  adoptAllFindings,
  dismissFinding,
  monitoringCatalog,
  monitoringFindings,
  monitoringFindingsError,
  monitoringDiscovery,
  monitoring,
  overviewView,
  openServerPage,
  setOverviewView,
  setTab,
} from './monitoring';
import { IpcError, SESSION_EXPIRED } from '$lib/utils/errors';

function check(serverId: string, status: string): MonitorCheck {
  return { id: `${serverId}-${status}`, serverId, state: { status } } as unknown as MonitorCheck;
}

describe('monitoring store (6.42)', () => {
  beforeEach(() => {
    h.fetchStatus.mockReset();
    setSelectedServer(null);
  });

  it('auto-selects the worst-status server when nothing is selected', async () => {
    h.fetchStatus.mockResolvedValue([check('srv-ok', 'ok'), check('srv-crit', 'critical')]);
    await loadMonitoring();
    expect(get(selectedServerId)).toBe('srv-crit'); // critical (prio 4) beats ok (prio 0)
  });

  it('drops the selection when its server disappears, then re-selects the worst', async () => {
    setSelectedServer('srv-gone');
    h.fetchStatus.mockResolvedValue([check('srv-a', 'warning')]);
    await loadMonitoring();
    expect(get(selectedServerId)).toBe('srv-a'); // srv-gone absent -> dropped -> auto-select
  });

  it('discards an out-of-order load result (statusGen guard)', async () => {
    // First load is slow, second is fast; the stale first result must not overwrite the newer one.
    let resolveSlow!: (v: MonitorCheck[]) => void;
    const slow = new Promise<MonitorCheck[]>((r) => {
      resolveSlow = r;
    });
    h.fetchStatus.mockReturnValueOnce(slow); // gen 1
    h.fetchStatus.mockResolvedValueOnce([check('srv-fast', 'ok')]); // gen 2

    const p1 = loadMonitoring();
    const p2 = loadMonitoring();
    await p2; // the newer load wins
    resolveSlow([check('srv-stale', 'critical')]); // the stale load resolves late
    await p1;

    // gen 2's result stands; the stale gen 1 result was discarded by the guard.
    expect(get(monitoringChecks).map((c) => c.serverId)).toEqual(['srv-fast']);
  });
});

describe('template assignment store actions (T13)', () => {
  const three = [
    { id: 's1', hostname: 'h1', name: 'n1' },
    { id: 's2', hostname: 'h2', name: 'n2' },
    { id: 's3', hostname: 'h3', name: 'n3' },
  ];

  beforeEach(() => {
    for (const fn of [
      h.assignTemplate,
      h.unassignTemplate,
      h.assignTemplateTag,
      h.fetchTemplates,
      h.reportError,
      h.showStatus,
    ]) {
      fn.mockReset();
    }
    h.fetchTemplates.mockResolvedValue([]);
  });

  it('bulk assign reports each failure individually without aborting', async () => {
    h.assignTemplate
      .mockResolvedValueOnce({})
      .mockRejectedValueOnce(new Error('409'))
      .mockResolvedValueOnce({});
    const ok = await assignTemplateToServers('tpl-1', three);
    expect(h.assignTemplate).toHaveBeenCalledTimes(3); // no abort after the failure
    expect(h.reportError).toHaveBeenCalledTimes(1);
    expect(h.fetchTemplates).toHaveBeenCalled(); // reload runs regardless
    expect(ok).toBe(false);
    expect(h.showStatus).not.toHaveBeenCalled(); // no success toast on partial failure
  });

  it('bulk assign success reloads and reports success', async () => {
    h.assignTemplate.mockResolvedValue({});
    const ok = await assignTemplateToServers('tpl-1', three);
    expect(ok).toBe(true);
    expect(h.showStatus).toHaveBeenCalledTimes(1);
  });

  it('unassign failure reports and returns false', async () => {
    h.unassignTemplate.mockRejectedValue(new Error('boom'));
    expect(await unassignTemplateFromServer('tpl-1', 's1')).toBe(false);
    expect(h.reportError).toHaveBeenCalledTimes(1);
  });

  it('tag assign failure reports and returns false', async () => {
    h.assignTemplateTag.mockRejectedValue(new Error('409'));
    expect(await assignTagToTemplate('tpl-1', 'web')).toBe(false);
    expect(h.reportError).toHaveBeenCalledTimes(1);
  });
});

// R-0261: a network error from the backend carries the ERR_* codes in its source chain
// (error.rs); they are for the code, the page shows the prose.
const PIN_MISMATCH =
  'error sending request: client error (Connect): ' +
  'ERR_TOFU_PIN_MISMATCH: AdminHelper TOFU: Das Server-Zertifikat für x hat sich geändert';
const PROSE =
  'error sending request: client error (Connect): ' +
  'AdminHelper TOFU: Das Server-Zertifikat für x hat sich geändert';

describe('monitoring store: a failed load without the machine codes (R-0261)', () => {
  beforeEach(() => h.fetchStatus.mockReset());

  it('keeps the prose for the overview', async () => {
    h.fetchStatus.mockRejectedValueOnce(PIN_MISMATCH);
    await loadMonitoring();
    expect(get(monitoringError)).toBe(PROSE);
  });

  it('still shows no error for an expired session', async () => {
    h.reportError.mockClear();
    h.fetchStatus.mockRejectedValueOnce(
      new IpcError('Session expired, please sign in again', SESSION_EXPIRED),
    );
    await loadMonitoring();
    expect(get(monitoringError)).toBeNull();
    expect(h.reportError).not.toHaveBeenCalled();
  });

  it('shows a text that only names the code', async () => {
    h.fetchStatus.mockRejectedValueOnce(new Error(SESSION_EXPIRED));
    await loadMonitoring();
    expect(get(monitoringError)).toBe(SESSION_EXPIRED);
  });
});

describe('module data of the server page (arch-monitoring-ui T3)', () => {
  const finding = (id: string) => ({ id, serverId: 'srv-1' }) as unknown as MonitorFinding;
  const discovery = (serverId: string, scanRequestedAt: string | null) =>
    ({ serverId, scanRequestedAt }) as unknown as MonitorDiscovery;

  beforeEach(() => {
    for (const fn of [
      h.fetchStatus,
      h.fetchCatalog,
      h.fetchOpenFindings,
      h.fetchDiscovery,
      h.requestScan,
      h.adoptFinding,
      h.adoptAllFindings,
      h.dismissFinding,
      h.reportError,
    ]) {
      fn.mockReset();
    }
    h.fetchStatus.mockResolvedValue([check('srv-1', 'ok')]);
  });

  it('adopting a finding reloads the checks and the open findings', async () => {
    const result = {
      finding: finding('f1'),
      enabledChecks: ['c1'],
      disabledChecks: [],
      skippedChecks: [],
    };
    h.adoptFinding.mockResolvedValue(result);
    h.fetchOpenFindings.mockResolvedValue([]);

    expect(await adoptFinding('f1')).toBe(result);
    expect(h.adoptFinding).toHaveBeenCalledWith(h.session, 'f1');
    expect(h.fetchStatus).toHaveBeenCalledTimes(1);
    expect(h.fetchOpenFindings).toHaveBeenCalledTimes(1);
    expect(get(monitoringFindings)).toEqual([]);
  });

  it('a failed adoption is reported, returns null and reloads nothing', async () => {
    h.adoptFinding.mockRejectedValue(new Error('module not in catalog'));

    expect(await adoptFinding('f1')).toBeNull();
    expect(h.reportError).toHaveBeenCalledWith('module not in catalog');
    expect(h.fetchStatus).not.toHaveBeenCalled();
    expect(h.fetchOpenFindings).not.toHaveBeenCalled();
  });

  it('adopt all hands the partial failures to the caller and reloads both lists', async () => {
    const result = { adopted: [], failed: [{ findingId: 'f2', reason: 'gone' }] };
    h.adoptAllFindings.mockResolvedValue(result);
    h.fetchOpenFindings.mockResolvedValue([finding('f2')]);

    expect(await adoptAllFindings('srv-1')).toBe(result);
    expect(h.adoptAllFindings).toHaveBeenCalledWith(h.session, 'srv-1');
    expect(h.fetchStatus).toHaveBeenCalledTimes(1);
    expect(get(monitoringFindings).map((f) => f.id)).toEqual(['f2']);
  });

  it('dismissing reloads only the findings', async () => {
    h.dismissFinding.mockResolvedValue(finding('f1'));
    h.fetchOpenFindings.mockResolvedValue([]);

    expect(await dismissFinding('f1')).toBe(true);
    expect(h.fetchOpenFindings).toHaveBeenCalledTimes(1);
    expect(h.fetchStatus).not.toHaveBeenCalled();
  });

  it('a failed findings load keeps the list and its error until a load succeeds', async () => {
    h.fetchOpenFindings.mockResolvedValueOnce([finding('f1')]);
    await loadFindings();
    h.fetchOpenFindings.mockRejectedValueOnce(new Error('monitoring unreachable'));
    await loadFindings();

    // An outage must not read as "nothing new found".
    expect(get(monitoringFindings).map((f) => f.id)).toEqual(['f1']);
    expect(get(monitoringFindingsError)).toBe('monitoring unreachable');

    h.fetchOpenFindings.mockResolvedValueOnce([]);
    await loadFindings();
    expect(get(monitoringFindingsError)).toBeNull();
    expect(get(monitoringFindings)).toEqual([]);
  });

  it('an expired session leaves no findings error behind', async () => {
    h.fetchOpenFindings.mockRejectedValue(
      new IpcError('Session expired, please sign in again', SESSION_EXPIRED),
    );
    await loadFindings();
    expect(get(monitoringFindingsError)).toBeNull();
  });

  it('discards an out-of-order findings result (findingsGen guard)', async () => {
    let resolveSlow!: (v: MonitorFinding[]) => void;
    h.fetchOpenFindings.mockReturnValueOnce(
      new Promise<MonitorFinding[]>((r) => {
        resolveSlow = r;
      }),
    );
    h.fetchOpenFindings.mockResolvedValueOnce([finding('fresh')]);

    const p1 = loadFindings();
    await loadFindings();
    resolveSlow([finding('stale')]);
    await p1;

    expect(get(monitoringFindings).map((f) => f.id)).toEqual(['fresh']);
  });

  it('loads the catalog once per sign-in and again after a new one', async () => {
    const before = h.session;
    try {
      h.session = { session: { token: 'a' }, settings: {} };
      h.fetchCatalog.mockResolvedValue({ version: '1', modules: [] });
      await loadCatalog();
      await loadCatalog();
      expect(h.fetchCatalog).toHaveBeenCalledTimes(1);
      expect(get(monitoringCatalog)?.version).toBe('1');

      h.session = { session: { token: 'b' }, settings: {} };
      h.fetchCatalog.mockResolvedValue({ version: '2', modules: [] });
      await loadCatalog();
      expect(h.fetchCatalog).toHaveBeenCalledTimes(2);
      expect(get(monitoringCatalog)?.version).toBe('2');
    } finally {
      h.session = before;
    }
  });

  it('retries a failed catalog load on the next call', async () => {
    const before = h.session;
    try {
      h.session = { session: { token: 'c' }, settings: {} };
      h.fetchCatalog.mockRejectedValueOnce(new Error('down'));
      await loadCatalog();
      h.fetchCatalog.mockResolvedValueOnce({ version: '3', modules: [] });
      await loadCatalog();
      expect(h.fetchCatalog).toHaveBeenCalledTimes(2);
      expect(get(monitoringCatalog)?.version).toBe('3');
      expect(h.reportError).not.toHaveBeenCalled();
    } finally {
      h.session = before;
    }
  });

  it('stores the discovery a scan request answers with', async () => {
    h.requestScan.mockResolvedValue(discovery('srv-1', '2026-11-10T10:00:00Z'));

    expect(await requestScan('srv-1')).toBe(true);
    expect(get(monitoringDiscovery)['srv-1']?.scanRequestedAt).toBe('2026-11-10T10:00:00Z');
  });

  it('keeps the last discovery when a reload fails and skips the no-server key', async () => {
    h.fetchDiscovery.mockResolvedValueOnce(discovery('srv-2', null));
    await loadDiscovery('srv-2');
    h.fetchDiscovery.mockRejectedValueOnce(new Error('down'));
    await loadDiscovery('srv-2');
    await loadDiscovery('__none');

    expect(h.fetchDiscovery).toHaveBeenCalledTimes(2);
    expect(get(monitoringDiscovery)['srv-2']?.serverId).toBe('srv-2');
    expect(h.reportError).not.toHaveBeenCalled();
  });
});

describe('server link of the cross views (arch-monitoring-ui T7)', () => {
  it('opens the server page in the list view of the overview tab', () => {
    setTab('certs');
    setOverviewView('grid');
    setSelectedServer('srv-a');

    openServerPage('srv-b');

    expect(get(monitoring).tab).toBe('overview');
    expect(get(overviewView)).toBe('list');
    expect(get(selectedServerId)).toBe('srv-b');
  });
});
