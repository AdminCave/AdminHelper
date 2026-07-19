// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// T21: fleet tile grid — worst-state accent per server, sorted worst-first,
// tile click drills into the list+detail view with the server selected. The
// view choice persists via localStorage.

import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, cleanup, fireEvent } from '@testing-library/svelte';
import { tick } from 'svelte';
import { get } from 'svelte/store';

const mocks = vi.hoisted(() => ({
  setSelectedServer: vi.fn(),
  setOverviewView: vi.fn(),
}));

vi.mock('$lib/stores/monitoring', async () => {
  const { writable } = await import('svelte/store');
  const checks = [
    { id: 'c1', serverId: 'srv-ok', name: 'a', checkType: 'ping', state: { status: 'ok' } },
    { id: 'c2', serverId: 'srv-bad', name: 'b', checkType: 'ping', state: { status: 'critical' } },
    { id: 'c3', serverId: 'srv-bad', name: 'c', checkType: 'ping', state: { status: 'ok' } },
    { id: 'c4', serverId: 'srv-new', name: 'd', checkType: 'ping', state: { status: 'pending' } },
  ];
  const servers = [
    { id: 'srv-ok', name: 'okay', hostname: 'ok.example' },
    { id: 'srv-bad', name: 'burning', hostname: 'bad.example' },
    { id: 'srv-new', name: 'fresh', hostname: 'new.example' },
  ];
  return {
    monitoringChecks: writable(checks),
    monitoringServers: writable(servers),
    monitoringServerSearch: writable(''),
    setSelectedServer: mocks.setSelectedServer,
    setOverviewView: mocks.setOverviewView,
  };
});

import { setLanguage } from '$lib/i18n';
import MonServerGrid from './MonServerGrid.svelte';

setLanguage('de');
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe('MonServerGrid (T21)', () => {
  it('renders tiles worst-first with the worst-state accent class', async () => {
    const { container } = render(MonServerGrid);
    await tick();
    const tiles = Array.from(container.querySelectorAll('.mon-tile'));
    expect(tiles).toHaveLength(3);
    expect(tiles[0].textContent).toContain('burning'); // critical sorts first
    expect(tiles[0].classList.contains('worst-critical')).toBe(true);
  });

  it('a pending-only server gets a muted pill and no global mon-* class on the root', async () => {
    const { container } = render(MonServerGrid);
    await tick();
    const fresh = Array.from(container.querySelectorAll('.mon-tile')).find((tile) =>
      tile.textContent?.includes('fresh'),
    ) as HTMLElement;
    // Global .mon-pending would set opacity:.5 on the whole tile — must not leak here.
    expect(fresh.classList.contains('mon-pending')).toBe(false);
    expect(fresh.classList.contains('worst-pending')).toBe(true);
    // Pending counts into the muted pill (parity with the list item), ok pill hidden at 0.
    expect(fresh.querySelector('.pill-muted')?.textContent).toBe('1');
    expect(fresh.querySelector('.pill-ok')).toBeNull();
  });

  it('tile click selects the server and switches to the list view', async () => {
    const { container } = render(MonServerGrid);
    await tick();
    const first = container.querySelector('.mon-tile') as HTMLButtonElement;
    await fireEvent.click(first);
    expect(mocks.setSelectedServer).toHaveBeenCalledWith('srv-bad');
    expect(mocks.setOverviewView).toHaveBeenCalledWith('list');
  });
});

describe('overview view persistence (T21)', () => {
  it('setOverviewView writes localStorage and the derived store', async () => {
    // Real store module (unmocked) via dynamic import under a fresh registry.
    const real =
      await vi.importActual<typeof import('$lib/stores/monitoring')>('$lib/stores/monitoring');
    real.setOverviewView('grid');
    expect(get(real.overviewView)).toBe('grid');
    expect(localStorage.getItem('ah.monitoring.view')).toBe('grid');
    real.setOverviewView('list');
  });
});
