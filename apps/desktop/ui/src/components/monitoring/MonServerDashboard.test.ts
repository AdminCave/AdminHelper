// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// The server dashboard head (R-1064): worst-state dot, count pills, the maintenance and
// "+ Check" actions. The sections, history and modals are stubbed.
import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, cleanup, screen, fireEvent } from '@testing-library/svelte';
import { tick } from 'svelte';

const h = vi.hoisted(() => ({
  stub: vi.fn(),
  maint: vi.fn(),
  openCheckEditor: vi.fn(),
}));

vi.mock('$lib/stores/monitoring', async () => {
  const { writable } = await import('svelte/store');
  const checks = [
    { id: 'c1', serverId: 'srv-1', name: 'a', checkType: 'ping', state: { status: 'critical' } },
    { id: 'c2', serverId: 'srv-1', name: 'b', checkType: 'ping', state: { status: 'ok' } },
    { id: 'c3', serverId: 'srv-1', name: 'c', checkType: 'ping', state: { status: 'ok' } },
    { id: 'c4', serverId: 'srv-1', name: 'd', checkType: 'ping', state: { status: 'pending' } },
    { id: 'c5', serverId: null, name: 'e', checkType: 'ping', state: { status: 'ok' } },
  ];
  return {
    monitoringChecks: writable(checks),
    monitoringServers: writable([{ id: 'srv-1', name: 'web01', hostname: 'web01.example' }]),
    selectedServerId: writable<string | null>(null),
    checkEditor: writable({ open: false, target: null, serverId: '' }),
    openCheckEditor: h.openCheckEditor,
    closeCheckEditor: vi.fn(),
    loadMonitoring: vi.fn(),
    loadMaintenanceWindows: vi.fn(),
  };
});
vi.mock('./MaintenanceModal.svelte', () => ({ default: h.maint }));
vi.mock('./MonitorCheckModal.svelte', () => ({ default: h.stub }));
vi.mock('./MonHeartbeatBar.svelte', () => ({ default: h.stub }));
vi.mock('./HistoryPanel.svelte', () => ({ default: h.stub }));
vi.mock('./section/SecLive.svelte', () => ({ default: h.stub }));
vi.mock('./section/SecNetwork.svelte', () => ({ default: h.stub }));
vi.mock('./section/SecHeartbeat.svelte', () => ({ default: h.stub }));
vi.mock('./section/SecServices.svelte', () => ({ default: h.stub }));
vi.mock('./section/SecSystem.svelte', () => ({ default: h.stub }));
vi.mock('./section/SecDocker.svelte', () => ({ default: h.stub }));
vi.mock('./section/SecBackups.svelte', () => ({ default: h.stub }));
vi.mock('./section/SecZfs.svelte', () => ({ default: h.stub }));
vi.mock('./section/SecSmart.svelte', () => ({ default: h.stub }));
vi.mock('./section/SecForecast.svelte', () => ({ default: h.stub }));

import { setLanguage } from '$lib/i18n';
import { selectedServerId } from '$lib/stores/monitoring';
import MonServerDashboard from './MonServerDashboard.svelte';

setLanguage('de');
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

async function mount(selected: string): Promise<HTMLElement> {
  (selectedServerId as unknown as { set: (v: string) => void }).set(selected);
  const { container } = render(MonServerDashboard);
  await tick();
  return container;
}

describe('MonServerDashboard head (R-1064)', () => {
  it('shows the worst state as a labelled dot and the counts as pills', async () => {
    const el = await mount('srv-1');
    expect(el.querySelector('.mon-dashboard-name')?.textContent).toBe('web01');
    expect(el.querySelector('.mon-dashboard-host')?.textContent).toBe('web01.example');
    expect(screen.getByRole('img', { name: 'Kritisch' })).toBeTruthy();
    const pills = Array.from(el.querySelectorAll('.mon-dashboard-stats .pill')).map((p) => [
      p.textContent?.trim(),
      p.className.match(/pill-(\w+)/)?.[1],
    ]);
    expect(pills).toEqual([
      ['1 Kritisch', 'crit'],
      ['2 OK', 'ok'],
      ['1 Pending', 'muted'],
    ]);
    expect(el.querySelector('.mon-pill')).toBeNull();
  });

  it('"+ Check" opens the check editor for the selected server', async () => {
    const el = await mount('srv-1');
    await fireEvent.click(el.querySelector('[data-action="check-new"]') as HTMLElement);
    expect(h.openCheckEditor).toHaveBeenCalledWith(null, 'srv-1');
  });

  it('the maintenance button opens a new window for the selected server', async () => {
    const el = await mount('srv-1');
    const props = h.maint.mock.calls.at(-1)?.[1] as {
      open: boolean;
      editing: unknown;
      serverId: string;
    };
    expect(props.open).toBe(false);
    await fireEvent.click(el.querySelector('[data-action="maintenance-new"]') as HTMLElement);
    expect(props.open).toBe(true);
    expect(props.editing).toBeNull();
    expect(props.serverId).toBe('srv-1');
  });

  it('offers no actions for the checks without a server', async () => {
    const el = await mount('__none');
    expect(el.querySelector('[data-action="check-new"]')).toBeNull();
    expect(el.querySelector('[data-action="maintenance-new"]')).toBeNull();
    expect(h.maint).not.toHaveBeenCalled();
  });
});
