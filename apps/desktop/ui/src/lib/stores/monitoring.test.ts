// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Monitoring store (6.42): the auto-select picks the worst-status server (pickWorstServerId /
// STATUS_PRIORITY), drops a selection whose server disappears, and the statusGen generation-token
// guard discards an out-of-order load result — a broken guard would show stale check status, the one
// thing a monitoring view must never do.

import { describe, it, expect, beforeEach, vi } from 'vitest';
import { get } from 'svelte/store';
import type { MonitorCheck } from '$lib/api/types';

// Hoisted mock state so the vi.mock factories (which run before imports) can close over it.
const h = vi.hoisted(() => ({
  session: { session: {}, settings: {} } as unknown,
  fetchStatus: vi.fn(),
  fetchTemplates: vi.fn(),
  assignTemplate: vi.fn(),
  unassignTemplate: vi.fn(),
  assignTemplateTag: vi.fn(),
  unassignTemplateTag: vi.fn(),
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
} from './monitoring';

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
