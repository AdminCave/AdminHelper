// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// T19: the overview finally consumes the store's loading flag and the new
// error state — first-load skeleton, inline error banner with retry, and an
// EmptyState with a CTA to the templates tab instead of a blank split view.

import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, cleanup, fireEvent, waitFor } from '@testing-library/svelte';
import { tick } from 'svelte';
import { get } from 'svelte/store';

// MonServerDashboard -> ExpandChart -> uPlot needs matchMedia; never rendered here.
vi.mock('uplot', () => ({ default: class {} }));

const h = vi.hoisted(() => ({
  fetchStatus: vi.fn(),
  fetchServers: vi.fn(),
  fetchTemplates: vi.fn(),
  assignTemplate: vi.fn(),
}));

vi.mock('$lib/api/monitoring', () => ({
  monitoringApi: {
    fetchStatus: h.fetchStatus,
    fetchServers: h.fetchServers,
    fetchTemplates: h.fetchTemplates,
    assignTemplate: h.assignTemplate,
  },
}));
vi.mock('$lib/stores/session', async () => {
  const { writable } = await import('svelte/store');
  return {
    currentSession: () => ({ session: {}, settings: {} }),
    session: writable({ session: {}, settings: {} }),
  };
});

import { setLanguage } from '$lib/i18n';
import {
  loadMonitoring,
  loadServers,
  loadTemplates,
  monitoringTab,
  setTab,
} from '$lib/stores/monitoring';
import MonitoringOverview from './MonitoringOverview.svelte';

setLanguage('de');

function _check(id: string, serverId: string) {
  return {
    id,
    serverId,
    name: 'Backups',
    checkType: 'proxmox_backup',
    enabled: true,
    config: {},
    state: { status: 'ok' },
  };
}

afterEach(async () => {
  cleanup();
  // Reset store to a clean, resolved-empty state, THEN zero the call counts —
  // the reset load itself must not leak into the next test's assertions.
  h.fetchStatus.mockReset();
  h.fetchServers.mockReset();
  h.fetchTemplates.mockReset();
  h.assignTemplate.mockReset();
  h.fetchStatus.mockResolvedValueOnce([]);
  h.fetchServers.mockResolvedValueOnce([]);
  h.fetchTemplates.mockResolvedValueOnce([]);
  await Promise.all([loadMonitoring(), loadServers(), loadTemplates()]);
  h.fetchStatus.mockReset();
  h.fetchServers.mockReset();
  h.fetchTemplates.mockReset();
  setTab('overview');
});

describe('MonitoringOverview states (T19)', () => {
  // NOTE: order matters — hasLoaded is module-sticky, so the first-load
  // skeleton can only be observed in the FIRST test of this file.
  it('shows the skeleton from first paint until the first load resolved', async () => {
    // Cold start: rendered BEFORE any load — must be the skeleton, not a false
    // "no checks configured" EmptyState flash.
    const { container, queryByText } = render(MonitoringOverview);
    await tick();
    expect(container.querySelector('.mon-skeleton')).toBeTruthy();
    expect(queryByText('Noch keine Checks konfiguriert')).toBeNull();

    let resolve!: (v: unknown[]) => void;
    h.fetchStatus.mockReturnValueOnce(
      new Promise((r) => {
        resolve = r;
      }),
    );
    const pending = loadMonitoring();
    await tick();
    expect(container.querySelector('.mon-skeleton')).toBeTruthy();

    resolve([]);
    await pending;
    await tick();
    expect(container.querySelector('.mon-skeleton')).toBeNull();
  });

  it('shows the inline error banner with a working retry', async () => {
    h.fetchStatus.mockRejectedValueOnce(new Error('proxy down'));
    await loadMonitoring();
    const { getByRole, getByText } = render(MonitoringOverview);
    await tick();
    expect(getByRole('alert').textContent).toContain('proxy down');

    h.fetchStatus.mockResolvedValueOnce([]);
    await fireEvent.click(getByText('Erneut versuchen'));
    // 1st call = the failing load above, 2nd = the retry.
    await waitFor(() => expect(h.fetchStatus).toHaveBeenCalledTimes(2));
  });

  it('shows the EmptyState with a CTA that jumps to the templates tab', async () => {
    h.fetchStatus.mockResolvedValueOnce([]);
    await loadMonitoring();
    const { getByText } = render(MonitoringOverview);
    await tick();
    expect(getByText('Noch keine Checks konfiguriert')).toBeTruthy();

    await fireEvent.click(getByText('Standard-Template zuweisen'));
    expect(get(monitoringTab)).toBe('templates');
  });

  it('a refresh in the empty state keeps the EmptyState (no flicker)', async () => {
    h.fetchStatus.mockResolvedValueOnce([]);
    await loadMonitoring();
    // Simulated 30s auto-refresh: load hangs, view must not swap to skeleton.
    h.fetchStatus.mockReturnValueOnce(new Promise(() => {}));
    void loadMonitoring();
    const { container, getByText } = render(MonitoringOverview);
    await tick();
    expect(container.querySelector('.mon-skeleton')).toBeNull();
    expect(getByText('Noch keine Checks konfiguriert')).toBeTruthy();
  });

  it('shows no bulk banner when every server has checks', async () => {
    h.fetchServers.mockResolvedValueOnce([{ id: 'srv-1', name: 'web01', hostname: 'web01' }]);
    await loadServers();
    h.fetchStatus.mockResolvedValueOnce([_check('c1', 'srv-1')]);
    await loadMonitoring();
    const { queryByText } = render(MonitoringOverview);
    await tick();
    expect(queryByText('1 Server ohne Monitoring')).toBeNull();
  });

  it('bulk banner opens the assign dialog preselected, built-ins first (T32)', async () => {
    h.fetchServers.mockResolvedValueOnce([
      { id: 'srv-1', name: 'web01', hostname: 'web01' },
      { id: 'srv-2', name: 'db01', hostname: 'db01' },
    ]);
    await loadServers();
    const templates = [
      { id: 'tpl-user', name: 'Aaa Custom' },
      { id: 'tpl-builtin', name: 'Linux Server', builtinSlug: 'linux-base' },
    ];
    h.fetchTemplates.mockResolvedValueOnce(templates);
    await loadTemplates();
    h.fetchStatus.mockResolvedValueOnce([_check('c1', 'srv-1')]);
    await loadMonitoring();

    const { container, getByText } = render(MonitoringOverview);
    await tick();
    expect(getByText('1 Server ohne Monitoring')).toBeTruthy();

    // openBulkAssign refreshes the template list in the background.
    h.fetchTemplates.mockResolvedValueOnce(templates);
    await fireEvent.click(getByText('Template zuweisen'));
    await tick();
    expect(getByText('Server ohne Monitoring')).toBeTruthy();

    // The uncovered server is listed and preselected.
    const cb = container.querySelector('.mon-bulk-server input') as HTMLInputElement;
    expect(cb.value).toBe('srv-2');
    expect(cb.checked).toBe(true);
    expect(getByText('db01')).toBeTruthy();

    // Built-in template leads the picker despite sorting after 'Aaa' by name.
    const select = container.querySelector('.field select') as HTMLSelectElement;
    expect(select.options[0].text).toBe('Linux Server');
    expect(select.value).toBe('tpl-builtin');
  });

  it('bulk submit assigns the template to the selected servers and closes (T32)', async () => {
    h.fetchServers.mockResolvedValueOnce([
      { id: 'srv-1', name: 'web01', hostname: 'web01' },
      { id: 'srv-2', name: 'db01', hostname: 'db01.lan' },
    ]);
    await loadServers();
    const templates = [{ id: 'tpl-1', name: 'Linux Server', builtinSlug: 'linux-base' }];
    h.fetchTemplates.mockResolvedValueOnce(templates);
    await loadTemplates();
    h.fetchStatus.mockResolvedValueOnce([_check('c1', 'srv-1')]);
    await loadMonitoring();

    const { container, getByText, queryByText } = render(MonitoringOverview);
    await tick();
    h.fetchTemplates.mockResolvedValue(templates);
    await fireEvent.click(getByText('Template zuweisen'));
    await tick();

    // assignTemplateToServers reloads templates after the assigns; the status
    // reload after closing is the component's own refresh.
    h.assignTemplate.mockResolvedValueOnce({});
    h.fetchStatus.mockResolvedValue([_check('c1', 'srv-1'), _check('c2', 'srv-2')]);
    await fireEvent.click(getByText('Zuweisen (1)'));
    await waitFor(() => expect(h.assignTemplate).toHaveBeenCalledTimes(1));
    const [, tplId, srvId, hostname, name] = h.assignTemplate.mock.calls[0];
    expect([tplId, srvId, hostname, name]).toEqual(['tpl-1', 'srv-2', 'db01.lan', 'db01']);
    await waitFor(() => expect(queryByText('Zuweisen (1)')).toBeNull());
    expect(container.querySelector('.mon-bulk-servers')).toBeNull();
  });

  it('a refresh with existing data keeps the dashboard (no skeleton)', async () => {
    h.fetchStatus.mockResolvedValueOnce([
      {
        id: 'c1',
        serverId: 'srv-1',
        name: 'Backups',
        checkType: 'proxmox_backup',
        enabled: true,
        config: {},
        state: { status: 'ok' },
      },
    ]);
    await loadMonitoring();
    h.fetchStatus.mockReturnValueOnce(new Promise(() => {}));
    void loadMonitoring();
    const { container } = render(MonitoringOverview);
    await tick();
    expect(container.querySelector('.mon-skeleton')).toBeNull();
    expect(container.querySelector('.mon-split')).toBeTruthy();
  });
});
