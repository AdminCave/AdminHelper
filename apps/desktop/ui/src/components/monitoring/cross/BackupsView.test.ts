// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// arch-monitoring-ui T7 (R-1225): the Proxmox backups of all servers in one table. Pins
// one row per VM/CT (the first entry winning), one row for a check that names no VM (an
// outage with its error text, no data yet, no VM), the limit from the check or the
// checker's default, disabled and other checks left out, the order by severity, the
// texts of the last backup, the outage's colour by check status, the empty view and the
// click that opens a server page.

import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render } from '@testing-library/svelte';
import type { MonStatus, MonitorCheck, Server } from '$lib/api/types';
import { setLanguage } from '$lib/i18n';
import BackupsView, { backupRows, stateRank } from './BackupsView.svelte';

const SERVERS: Server[] = [
  { id: 'srv-a', name: 'pve-a', hostname: 'pve-a.example' },
  { id: 'srv-b', name: 'pve-b', hostname: 'pve-b.example' },
];

function backups(
  id: string,
  status: MonStatus,
  details: Record<string, unknown> | null,
  over: Partial<MonitorCheck> = {},
): MonitorCheck {
  return {
    id,
    name: `Backups ${id}`,
    serverId: 'srv-a',
    checkType: 'proxmox_backup',
    interval: '1h',
    severity: 'critical',
    enabled: true,
    state: { status, details },
    ...over,
  };
}

function vm(vmid: number, backupStatus: string, extra: Record<string, unknown> = {}) {
  return { vmid, name: `vm-${vmid}`, type: 'qemu', backupStatus, ...extra };
}

function rows(container: HTMLElement): string[][] {
  return [...container.querySelectorAll('tbody tr')].map((tr) =>
    [...tr.querySelectorAll('td')].map((td) => td.textContent?.replace(/\s+/g, ' ').trim() ?? ''),
  );
}

beforeAll(() => setLanguage('de'));
afterEach(() => cleanup());

describe('backupRows', () => {
  it('makes one row per VM/CT, the first entry of a VM winning', () => {
    const list = backupRows(
      [
        backups('c1', 'critical', {
          available: true,
          vms: [
            vm(101, 'ok', { ageHours: 3 }),
            vm(102, 'outdated', { ageHours: 30 }),
            vm(200, 'missing', { type: 'lxc', name: 'mail' }),
            vm(101, 'missing'),
            { vmid: 300 },
            { vmid: '400', backupStatus: 'missing' },
            'garbage',
          ],
        }),
      ],
      SERVERS,
    );
    expect(list.map((r) => [r.key, r.vmid, r.what, r.state, r.ageHours])).toEqual([
      ['c1:101', 101, 'QEMU 101 (vm-101)', 'ok', null],
      ['c1:102', 102, 'QEMU 102 (vm-102)', 'outdated', 30],
      ['c1:200', 200, 'LXC 200 (mail)', 'missing', null],
      ['c1:300', 300, 'VM 300 (?)', 'ok', null],
    ]);
    expect(list[0]).toMatchObject({
      serverKey: 'srv-a',
      serverName: 'pve-a',
      maxAgeHours: 26,
      errorKey: null,
      checkStatus: 'critical',
    });
  });

  it('takes the limit of the check', () => {
    const c = backups(
      'c1',
      'ok',
      { vms: [vm(101, 'ok')] },
      {
        config: { max_backup_age_hours: 48 },
      },
    );
    expect(backupRows([c], SERVERS)[0].maxAgeHours).toBe(48);
  });

  it('keeps one row for a check that names no VM', () => {
    const list = backupRows(
      [
        backups('down', 'warning', { available: false, error: 'timeout', vms: [vm(101, 'ok')] }),
        backups('odd', 'unknown', { available: false, error: 'something_new' }),
        backups('fresh', 'pending', null),
        backups('none', 'ok', { available: true, vms: [] }),
      ],
      SERVERS,
    );
    expect(list.map((r) => [r.key, r.vmid, r.what, r.state, r.errorKey])).toEqual([
      ['down', null, 'Backups down', 'unavailable', 'monitoring.proxmox.error.timeout'],
      ['odd', null, 'Backups odd', 'unavailable', 'monitoring.proxmox.error.unknown'],
      ['fresh', null, 'Backups fresh', 'empty', null],
      ['none', null, 'Backups none', 'empty', null],
    ]);
  });

  it('leaves out disabled backup checks and checks of other types', () => {
    const off = backups('off', 'ok', { vms: [vm(101, 'missing')] }, { enabled: false });
    const zfs = backups('zfs', 'ok', { vms: [vm(101, 'missing')] }, { checkType: 'zfs_health' });
    expect(backupRows([off, zfs], SERVERS)).toEqual([]);
  });

  it('orders the states from missing to ok', () => {
    const states = ['ok', 'empty', 'outdated', 'unavailable', 'missing'] as const;
    expect([...states].sort((a, b) => stateRank(a) - stateRank(b))).toEqual([
      'missing',
      'outdated',
      'unavailable',
      'empty',
      'ok',
    ]);
  });
});

describe('BackupsView', () => {
  it('points to the template while no server has a backup check', () => {
    const { container } = render(BackupsView, { checks: [], servers: SERVERS, onOpen: () => {} });
    expect(container.querySelector('table')).toBeNull();
    expect(container.textContent).toContain('mit dem Template „Proxmox Host“');
  });

  it('lists the worst first and says when the last backup ran', () => {
    const checks = [
      backups('a', 'critical', {
        vms: [
          vm(101, 'ok', { name: 'web' }),
          vm(102, 'outdated', { ageHours: 30 }),
          vm(103, 'outdated', { ageHours: 75 }),
          vm(104, 'missing'),
        ],
      }),
      backups('b', 'critical', { available: false, error: 'cli_failed' }, { serverId: 'srv-b' }),
      backups('c', 'ok', { vms: [] }, { serverId: 'srv-b', config: { max_backup_age_hours: 48 } }),
    ];
    const { container } = render(BackupsView, { checks, servers: SERVERS, onOpen: () => {} });
    expect(container.querySelector('table')?.getAttribute('aria-label')).toBe(
      'Proxmox-Backups aller Server',
    );
    expect(rows(container)).toEqual([
      ['pve-a', 'QEMU 104 (vm-104)', 'keins gefunden', 'Kein Backup'],
      ['pve-a', 'QEMU 102 (vm-102)', 'vor 30 h', 'Veraltet'],
      ['pve-a', 'QEMU 103 (vm-103)', 'vor 3 Tagen', 'Veraltet'],
      ['pve-b', 'Backups b', '—', 'Proxmox-Abfrage fehlgeschlagen'],
      ['pve-b', 'Backups c', '—', 'Keine VMs/CTs'],
      ['pve-a', 'QEMU 101 (web)', 'in den letzten 26 h', 'Aktuell'],
    ]);
    const tones = [...container.querySelectorAll('[data-state]')].map(
      (el) => el.querySelector('.pill')?.className.match(/pill-(\w+)/)?.[1],
    );
    expect(tones).toEqual(['crit', 'warn', 'warn', 'crit', 'muted', 'ok']);
  });

  it('colours an outage by its check status and says when there is no data yet', () => {
    const checks = [
      backups('w', 'warning', { available: false, error: 'timeout' }),
      backups('u', 'unknown', { available: false, error: 'timeout' }),
      backups('p', 'pending', null),
    ];
    const { container } = render(BackupsView, { checks, servers: SERVERS, onOpen: () => {} });
    const cells = [...container.querySelectorAll('[data-state]')].map((el) => [
      el.textContent?.trim(),
      el.querySelector('.pill')?.className.match(/pill-(\w+)/)?.[1],
    ]);
    expect(cells).toEqual([
      ['Proxmox antwortet nicht (Zeitüberschreitung)', 'warn'],
      ['Proxmox antwortet nicht (Zeitüberschreitung)', 'muted'],
      ['Noch keine Daten', 'muted'],
    ]);
  });

  it('opens the server page of a row', async () => {
    const onOpen = vi.fn();
    const { getByRole } = render(BackupsView, {
      checks: [backups('b', 'ok', { vms: [vm(101, 'ok')] }, { serverId: 'srv-b' })],
      servers: SERVERS,
      onOpen,
    });
    await fireEvent.click(getByRole('button', { name: 'pve-b' }));
    expect(onOpen).toHaveBeenCalledWith('srv-b');
  });
});
