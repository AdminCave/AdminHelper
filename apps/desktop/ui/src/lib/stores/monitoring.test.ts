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
}));

vi.mock('./session', () => ({ currentSession: () => h.session }));
vi.mock('$lib/api/monitoring', () => ({ monitoringApi: { fetchStatus: h.fetchStatus } }));
vi.mock('./statusBar', () => ({ reportError: vi.fn(), showStatus: vi.fn() }));
vi.mock('$lib/i18n', () => ({ tNow: (k: string) => k }));

import {
  loadMonitoring,
  selectedServerId,
  monitoringChecks,
  setSelectedServer,
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
