// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// The monitoring page head (R-1064): the tabs come from the ui library and count alerts and
// templates only once their lists hold something. The tab bodies are stubbed.
import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, cleanup, screen, fireEvent } from '@testing-library/svelte';
import { tick } from 'svelte';

const h = vi.hoisted(() => ({ setTab: vi.fn(), stub: vi.fn() }));

vi.mock('$lib/stores/monitoring', async () => {
  const { writable } = await import('svelte/store');
  return {
    monitoring: writable({ tab: 'overview' }),
    monitoringAlerts: writable([{ id: 'a1' }, { id: 'a2' }]),
    monitoringTemplates: writable([]),
    activateMonitoring: vi.fn(),
    deactivateMonitoring: vi.fn(),
    setTab: h.setTab,
  };
});
vi.mock('../components/monitoring/MonitoringOverview.svelte', () => ({ default: h.stub }));
vi.mock('../components/monitoring/CompareView.svelte', () => ({ default: h.stub }));
vi.mock('../components/monitoring/MonitoringAlerts.svelte', () => ({ default: h.stub }));
vi.mock('../components/monitoring/MonitoringTemplates.svelte', () => ({ default: h.stub }));
vi.mock('../components/monitoring/MonitoringLog.svelte', () => ({ default: h.stub }));

import { setLanguage } from '$lib/i18n';
import Monitoring from './Monitoring.svelte';

setLanguage('de');
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
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
});
