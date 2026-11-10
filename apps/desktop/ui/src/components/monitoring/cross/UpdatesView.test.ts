// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// arch-monitoring-ui T8 (R-1225): reboots and security updates of all servers in one
// table. Pins the rows (one per enabled system_state check, other types and disabled
// checks left out, a check without a server under its own key), the loose reading of
// the details (only a boolean reboot, only an integer count, only the two problems of
// this view), the states with their order and tones by the check's status, the texts,
// the empty view and the click that opens a server page.

import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render } from '@testing-library/svelte';
import type { MonStatus, MonitorCheck, Server } from '$lib/api/types';
import { setLanguage } from '$lib/i18n';
import UpdatesView, { stateRank, updateRows } from './UpdatesView.svelte';

const SERVERS: Server[] = [
  { id: 'srv-web', name: 'web-1', hostname: 'web-1.example' },
  { id: 'srv-db', name: 'db-1', hostname: 'db-1.example' },
  { id: 'srv-mail', name: 'mail-1', hostname: 'mail-1.example' },
];

function system(
  id: string,
  serverId: string | null,
  status: MonStatus,
  details: unknown,
  over: Partial<MonitorCheck> = {},
): MonitorCheck {
  return {
    id,
    name: id,
    serverId,
    checkType: 'system_state',
    interval: '5m',
    severity: 'warning',
    enabled: true,
    state: details === undefined ? { status } : { status, details: details as never },
    ...over,
  };
}

function rows(container: HTMLElement): string[][] {
  return [...container.querySelectorAll('tbody tr')].map((tr) =>
    [...tr.querySelectorAll('td')].map((td) => td.textContent?.replace(/\s+/g, ' ').trim() ?? ''),
  );
}

beforeAll(() => setLanguage('de'));
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe('updateRows', () => {
  it('reads reboot, security updates and the two problems of this view', () => {
    const list = updateRows(
      [
        system('web', 'srv-web', 'warning', {
          reboot_required: true,
          security_updates: 3,
          problems: ['time_sync', 'security_updates', 'reboot'],
        }),
        system('db', 'srv-db', 'ok', {
          reboot_required: false,
          security_updates: 0,
          problems: [],
        }),
      ],
      SERVERS,
    );
    expect(list).toEqual([
      {
        key: 'db',
        serverKey: 'srv-db',
        serverName: 'db-1',
        reboot: false,
        securityUpdates: 0,
        problems: [],
        state: 'ok',
        checkStatus: 'ok',
      },
      {
        key: 'web',
        serverKey: 'srv-web',
        serverName: 'web-1',
        reboot: true,
        securityUpdates: 3,
        // In this view's order, the clock's problem left out.
        problems: ['reboot', 'security_updates'],
        state: 'action',
        checkStatus: 'warning',
      },
    ]);
  });

  it('reads the details loosely and leaves a point it cannot read open', () => {
    const list = updateRows(
      [
        // Only the clock is a problem: both points are clean, still nothing to do here.
        system('clock', 'srv-web', 'warning', {
          reboot_required: false,
          security_updates: 0,
          problems: ['time_sync'],
        }),
        // The agent could not determine the updates.
        system('unknown', 'srv-db', 'ok', { reboot_required: false, security_updates: null }),
        // Old details of another type, or values of the wrong kind.
        system('foreign', 'srv-mail', 'ok', {
          reboot_required: 'yes',
          security_updates: 2.5,
          problems: 'reboot',
        }),
        system('array', 'srv-mail', 'ok', ['reboot']),
        system('none', 'srv-mail', 'pending', undefined),
      ],
      SERVERS,
    );
    expect(list.map((r) => [r.key, r.reboot, r.securityUpdates, r.problems, r.state])).toEqual([
      ['unknown', false, null, [], 'open'],
      ['foreign', null, null, [], 'open'],
      ['array', null, null, [], 'nodata'],
      ['none', null, null, [], 'nodata'],
      ['clock', false, 0, [], 'ok'],
    ]);
  });

  it('leaves out disabled checks and other types, and files a check without a server', () => {
    const off = system('off', 'srv-web', 'ok', { reboot_required: true }, { enabled: false });
    const ping = system('ping', 'srv-web', 'ok', { reboot_required: true }, { checkType: 'ping' });
    const lost = system('lost', null, 'ok', { reboot_required: false, security_updates: 0 });
    const list = updateRows([off, ping, lost], SERVERS);
    expect(list.map((r) => [r.key, r.serverKey, r.serverName])).toEqual([
      ['lost', '__none', 'Ohne Server'],
    ]);
  });

  it('orders the states from action to ok', () => {
    const states = ['ok', 'nodata', 'action', 'open'] as const;
    expect([...states].sort((a, b) => stateRank(a) - stateRank(b))).toEqual([
      'action',
      'open',
      'nodata',
      'ok',
    ]);
  });
});

describe('UpdatesView', () => {
  it('says how to get rows while no server reports its system state', () => {
    const { container } = render(UpdatesView, { checks: [], servers: SERVERS, onOpen: () => {} });
    expect(container.querySelector('table')).toBeNull();
    expect(container.textContent).toContain('Kein Server meldet seinen Systemzustand.');
    expect(container.textContent).toContain('„Linux Server — Standard“');
  });

  it('lists what needs action first, with the texts and tones of the server page', () => {
    const checks = [
      system('ok', 'srv-db', 'ok', { reboot_required: false, security_updates: 0, problems: [] }),
      system('quiet', 'srv-mail', 'pending', undefined),
      system('crit', 'srv-web', 'critical', {
        reboot_required: true,
        security_updates: 7,
        problems: ['reboot', 'security_updates'],
      }),
      system('open', 'srv-mail', 'ok', { reboot_required: true, security_updates: null }),
      // A first, still damped problem leaves the check ok: grey, not red.
      system('damped', 'srv-db', 'ok', {
        reboot_required: false,
        security_updates: 2,
        problems: ['security_updates'],
      }),
    ];
    const { container } = render(UpdatesView, { checks, servers: SERVERS, onOpen: () => {} });
    expect(container.querySelector('table')?.getAttribute('aria-label')).toBe(
      'Updates und Neustarts aller Server',
    );
    // Equal states keep the order of the servers' names.
    expect(rows(container)).toEqual([
      ['db-1', 'nein', '2', 'Sicherheits-Updates: 2'],
      ['web-1', 'ja', '7', 'Neustart nötig · Sicherheits-Updates: 7'],
      ['mail-1', 'ja', '—', 'Nicht bewertet'],
      ['mail-1', '—', '—', 'Noch keine Daten'],
      ['db-1', 'nein', '0', 'Aktuell'],
    ]);
    const states = [...container.querySelectorAll('[data-state]')].map((el) => [
      el.getAttribute('data-state'),
      el.querySelector('.pill')?.className.match(/pill-(\w+)/)?.[1],
    ]);
    expect(states).toEqual([
      ['action', 'muted'],
      ['action', 'crit'],
      ['open', 'muted'],
      ['nodata', 'muted'],
      ['ok', 'ok'],
    ]);
  });

  it('colours a warned problem as a warning', () => {
    const checks = [
      system('warn', 'srv-web', 'warning', {
        reboot_required: true,
        security_updates: 0,
        problems: ['reboot'],
      }),
    ];
    const { container } = render(UpdatesView, { checks, servers: SERVERS, onOpen: () => {} });
    expect(container.querySelector('[data-state="action"] .pill')?.className).toContain(
      'pill-warn',
    );
    expect(rows(container)[0][3]).toBe('Neustart nötig');
  });

  it('opens the server page of a row', async () => {
    const onOpen = vi.fn();
    const { getByRole } = render(UpdatesView, {
      checks: [system('web', 'srv-web', 'ok', { reboot_required: false, security_updates: 0 })],
      servers: SERVERS,
      onOpen,
    });
    await fireEvent.click(getByRole('button', { name: 'web-1' }));
    expect(onOpen).toHaveBeenCalledWith('srv-web');
  });
});
