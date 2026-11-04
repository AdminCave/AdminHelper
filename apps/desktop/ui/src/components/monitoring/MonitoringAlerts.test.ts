// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// The alert rules panel (R-1064): one row per rule with a switch for its state, the
// "+ Alert" action and the edit button. The rule modal is stubbed.
import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, cleanup, screen, fireEvent } from '@testing-library/svelte';
import { tick } from 'svelte';

const h = vi.hoisted(() => ({ modal: vi.fn(), toggleAlert: vi.fn() }));

vi.mock('$lib/stores/monitoring', async () => {
  const { writable } = await import('svelte/store');
  return {
    monitoringAlerts: writable([
      {
        id: 'r1',
        name: 'cpu-high',
        channel: 'webhook',
        matchSeverity: 'critical',
        cooldownMinutes: 15,
        enabled: true,
      },
      { id: 'r2', name: 'disk-full', channel: 'email', cooldownMinutes: 60, enabled: false },
    ]),
    monitoringServers: writable([]),
    toggleAlert: h.toggleAlert,
  };
});
vi.mock('./AlertRuleModal.svelte', () => ({ default: h.modal }));

import { setLanguage } from '$lib/i18n';
import { monitoringAlerts } from '$lib/stores/monitoring';
import MonitoringAlerts from './MonitoringAlerts.svelte';

setLanguage('de');
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

type ModalProps = { open: boolean; editing: { id: string } | null };
const modalProps = (): ModalProps => h.modal.mock.calls.at(-1)?.[1] as ModalProps;

describe('MonitoringAlerts (R-1064)', () => {
  it('lists every rule with its state on a switch', async () => {
    const { container } = render(MonitoringAlerts);
    await tick();
    const names = [...container.querySelectorAll('.mon-alert-name')].map((n) => n.textContent);
    expect(names).toEqual(['cpu-high', 'disk-full']);
    expect(container.querySelector('.mon-alert-meta')?.textContent).toContain('Cooldown: 15m');
    const switches = screen.getAllByRole('switch', { name: 'Aktiv' });
    expect(switches.map((s) => s.getAttribute('aria-checked'))).toEqual(['true', 'false']);
  });

  it('the switch toggles that rule', async () => {
    render(MonitoringAlerts);
    await tick();
    await fireEvent.click(screen.getAllByRole('switch')[1]);
    expect(h.toggleAlert).toHaveBeenCalledWith('r2');
  });

  it('"+ Alert" opens an empty rule, edit opens the rule', async () => {
    const { container } = render(MonitoringAlerts);
    await tick();
    expect(modalProps().open).toBe(false);
    await fireEvent.click(container.querySelector('[data-action="alert-new"]') as HTMLElement);
    expect(modalProps().open).toBe(true);
    expect(modalProps().editing).toBeNull();
    await fireEvent.click(screen.getAllByRole('button', { name: 'Bearbeiten' })[0]);
    expect(modalProps().editing?.id).toBe('r1');
  });

  it('shows the empty state without rules', async () => {
    (monitoringAlerts as unknown as { set: (v: unknown[]) => void }).set([]);
    const { container } = render(MonitoringAlerts);
    await tick();
    expect(container.querySelector('.mon-empty')?.textContent).toBe('Keine Alert-Regeln');
    expect(screen.queryAllByRole('switch')).toHaveLength(0);
  });
});
