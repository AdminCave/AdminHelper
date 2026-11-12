// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// The monitoring page head (R-1064): the tabs come from the ui library and count alerts and
// templates only once their lists hold something. The tab bodies are stubbed. Above the tabs
// the dead man's switch says how long monitoring has been without a result (T6, R-1225).
// The cross tabs for certificates and backups get the checks, the servers and the link to
// a server page (T7, R-1225), so does the one for updates and reboots; the findings tab
// gets the findings with their load error and counts a non-empty list (T8). Only an admin
// session gets the findings tab: the monitoring proxy answers everyone else 403 (R-1289).
import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, cleanup, screen, fireEvent } from '@testing-library/svelte';
import { tick } from 'svelte';

const h = vi.hoisted(() => ({
  setTab: vi.fn(),
  openServerPage: vi.fn(),
  stub: vi.fn(),
  certs: vi.fn(),
  backups: vi.fn(),
  updates: vi.fn(),
  findings: vi.fn(),
}));

vi.mock('$lib/stores/monitoring', async () => {
  const { writable } = await import('svelte/store');
  return {
    monitoring: writable({ tab: 'overview' }),
    monitoringAlerts: writable([{ id: 'a1' }, { id: 'a2' }]),
    monitoringTemplates: writable([]),
    monitoringChecks: writable([{ id: 'c1' }]),
    monitoringServers: writable([{ id: 'srv-1' }]),
    monitoringFindings: writable([{ id: 'f1' }, { id: 'f2' }, { id: 'f3' }]),
    monitoringFindingsError: writable('timeout'),
    activateMonitoring: vi.fn(),
    deactivateMonitoring: vi.fn(),
    openServerPage: h.openServerPage,
    setTab: h.setTab,
  };
});
vi.mock('$lib/stores/monitoringPulse', async () => {
  const { writable } = await import('svelte/store');
  return { monitoringSilentMinutes: writable<number | null>(null) };
});
vi.mock('../components/monitoring/MonitoringOverview.svelte', () => ({ default: h.stub }));
vi.mock('../components/monitoring/CompareView.svelte', () => ({ default: h.stub }));
vi.mock('../components/monitoring/MonitoringAlerts.svelte', () => ({ default: h.stub }));
vi.mock('../components/monitoring/MonitoringTemplates.svelte', () => ({ default: h.stub }));
vi.mock('../components/monitoring/MonitoringLog.svelte', () => ({ default: h.stub }));
vi.mock('../components/monitoring/cross/CertsView.svelte', () => ({ default: h.certs }));
vi.mock('../components/monitoring/cross/BackupsView.svelte', () => ({ default: h.backups }));
vi.mock('../components/monitoring/cross/UpdatesView.svelte', () => ({ default: h.updates }));
vi.mock('../components/monitoring/cross/FindingsView.svelte', () => ({ default: h.findings }));

vi.mock('$lib/stores/session', async () => {
  const { writable } = await import('svelte/store');
  return { session: writable<object | null>({ username: 'admin', isAdmin: true }) };
});

import type { Writable } from 'svelte/store';
import { setLanguage } from '$lib/i18n';
import * as store from '$lib/stores/monitoring';
import * as pulse from '$lib/stores/monitoringPulse';
import * as sessionMod from '$lib/stores/session';
import Monitoring from './Monitoring.svelte';

const silent = pulse.monitoringSilentMinutes as unknown as Writable<number | null>;
const state = store.monitoring as unknown as Writable<{ tab: string }>;
const findings = store.monitoringFindings as unknown as Writable<{ id: string }[]>;
const session = sessionMod.session as unknown as Writable<object | null>;

setLanguage('de');
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  silent.set(null);
  session.set({ username: 'admin', isAdmin: true });
  state.set({ tab: 'overview' });
  findings.set([{ id: 'f1' }, { id: 'f2' }, { id: 'f3' }]);
});

describe('Monitoring page', () => {
  it('counts a non-empty alert list, never a 0 for a not yet loaded one', async () => {
    render(Monitoring);
    await tick();
    const alerts = screen.getByRole('tab', { name: /Alerts/ });
    const templates = screen.getByRole('tab', { name: /Templates/ });
    expect(alerts.querySelector('.count')?.textContent).toBe('2');
    expect(templates.querySelector('.count')).toBeNull();
    expect(screen.getByRole('tab', { name: 'Uebersicht' }).getAttribute('aria-selected')).toBe(
      'true',
    );
  });

  it('switches the tab through the store', async () => {
    render(Monitoring);
    await tick();
    await fireEvent.click(screen.getByRole('tab', { name: 'Verlauf' }));
    expect(h.setTab).toHaveBeenCalledWith('history');
  });

  it('switches to the certificate and backup tabs through the store', async () => {
    render(Monitoring);
    await tick();
    await fireEvent.click(screen.getByRole('tab', { name: 'Zertifikate & Domains' }));
    expect(h.setTab).toHaveBeenCalledWith('certs');
    await fireEvent.click(screen.getByRole('tab', { name: 'Backups' }));
    expect(h.setTab).toHaveBeenCalledWith('backups');
    await fireEvent.click(screen.getByRole('tab', { name: 'Updates & Neustarts' }));
    expect(h.setTab).toHaveBeenCalledWith('updates');
    await fireEvent.click(screen.getByRole('tab', { name: /Funde/ }));
    expect(h.setTab).toHaveBeenCalledWith('findings');
  });

  it('shows the findings tab to an admin only', async () => {
    render(Monitoring);
    await tick();
    expect(screen.queryByRole('tab', { name: /Funde/ })).not.toBeNull();
    cleanup();
    session.set({ username: 'alice', isAdmin: false });
    render(Monitoring);
    await tick();
    expect(screen.queryByRole('tab', { name: /Funde/ })).toBeNull();
    expect(screen.getByRole('tab', { name: 'Uebersicht' })).toBeTruthy();
  });

  it('counts the open findings, never a 0', async () => {
    render(Monitoring);
    await tick();
    const tab = screen.getByRole('tab', { name: /Funde/ });
    expect(tab.querySelector('.count')?.textContent).toBe('3');
    findings.set([]);
    await tick();
    expect(tab.querySelector('.count')).toBeNull();
  });

  it('gives the findings tab the findings, their load error, the servers and the link', async () => {
    state.set({ tab: 'findings' });
    render(Monitoring);
    await tick();
    expect(h.updates).not.toHaveBeenCalled();
    expect(h.findings).toHaveBeenCalledTimes(1);
    const props = h.findings.mock.calls[0][1];
    expect(props.findings).toEqual([{ id: 'f1' }, { id: 'f2' }, { id: 'f3' }]);
    expect(props.error).toBe('timeout');
    expect(props.servers).toEqual([{ id: 'srv-1' }]);
    expect(props.onOpen).toBe(h.openServerPage);
  });

  it.each([
    ['certs', 'certs', 'backups'],
    ['backups', 'backups', 'certs'],
    ['updates', 'updates', 'findings'],
  ] as const)(
    'gives the %s tab the checks, the servers and the server link',
    async (tab, shown, hidden) => {
      state.set({ tab });
      render(Monitoring);
      await tick();
      expect(h[hidden]).not.toHaveBeenCalled();
      expect(h[shown]).toHaveBeenCalledTimes(1);
      const props = h[shown].mock.calls[0][1];
      expect(props.checks).toEqual([{ id: 'c1' }]);
      expect(props.servers).toEqual([{ id: 'srv-1' }]);
      expect(props.onOpen).toBe(h.openServerPage);
    },
  );

  it('warns above the tabs while monitoring is without a result, and drops it on recovery', async () => {
    render(Monitoring);
    await tick();
    expect(screen.queryByText(/ohne Ergebnis/)).toBeNull();
    silent.set(14);
    await tick();
    const warning = screen.getByRole('status');
    expect(warning.textContent).toContain('Monitoring seit 14 min ohne Ergebnis');
    expect(warning.textContent).toContain('Läuft der Monitoring-Dienst');
    silent.set(null);
    await tick();
    expect(screen.queryByRole('status')).toBeNull();
  });
});
