// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// monitoring-linux-base-v2 T24 (R-0492): since report version 3 an unreadable
// Proxmox is an outage with an error code, but the backups line showed the same
// bare "—" as a host without data. Pins the translated error in a pill coloured
// by the check status (grey with the outage alert off) instead of the VM list,
// the general text for an unknown code, the VMs of details written before the
// outage block as before, the dash after a missing block, details of another
// shape that do not break the section, and the English texts.

import { describe, it, expect, afterEach, vi } from 'vitest';

// SecBackups -> MonCheckLine -> ExpandChart -> MonChart -> uPlot, whose module
// init calls matchMedia (missing in jsdom). SecBackups never renders a chart
// (showChart={false}) — stub the lib away, same as SecZfs.test.ts.
vi.mock('uplot', () => ({ default: class {} }));
import { render, cleanup } from '@testing-library/svelte';
import { tick } from 'svelte';
import { get } from 'svelte/store';
import type { MonitorCheck, MonitorCheckState } from '$lib/api/types';
import { setLanguage } from '$lib/i18n';
import { monitoring, toggleExpanded } from '$lib/stores/monitoring';
import SecBackups from './SecBackups.svelte';

const ID = 'chk-backups';

function check(state: MonitorCheckState, id = ID): MonitorCheck {
  return {
    id,
    serverId: 'srv-1',
    name: 'Proxmox Backups',
    checkType: 'proxmox_backup',
    interval: '1h',
    severity: 'critical',
    enabled: true,
    state,
  } as MonitorCheck;
}

// What the checker writes for a block the agent could not read.
function outage(error: string | null) {
  return { available: false, error, vms: [] };
}

function vm(vmid: number, backupStatus: 'ok' | 'outdated' | 'missing', ageHours?: number) {
  return { vmid, name: `vm-${vmid}`, type: 'qemu', backupStatus, ageHours };
}

function pills(el: HTMLElement): HTMLElement[] {
  return Array.from(el.querySelectorAll<HTMLElement>('.mon-line-pill'));
}

function texts(list: HTMLElement[]): string[] {
  return list.map((p) => p.textContent?.replace(/\s+/g, ' ').trim() ?? '');
}

function colored(list: HTMLElement[]): HTMLElement[] {
  return list.filter((p) => /\bpill-(ok|warn|crit)\b/.test(p.className));
}

// The names of the expanded VM rows, sorted: the section's own order is not
// what these tests pin.
async function expand(el: HTMLElement): Promise<string[]> {
  toggleExpanded(ID);
  await tick();
  return Array.from(el.querySelectorAll<HTMLElement>('.mon-expand-row'))
    .map((r) => r.querySelector('.mon-expand-name')?.textContent?.replace(/\s+/g, ' ').trim() ?? '')
    .sort();
}

setLanguage('de');
afterEach(() => {
  cleanup();
  if (get(monitoring).expandedCheckId === ID) toggleExpanded(ID);
  setLanguage('de');
});

describe('SecBackups outage', () => {
  it('shows the translated error in a pill coloured by the status instead of the VMs', async () => {
    const message = 'Proxmox unavailable (backup_index_incomplete): backup storage nas not active';
    // A VM list next to the outage (never written by the checker) is not shown.
    const down = check({
      status: 'warning',
      message,
      details: { ...outage('backup_index_incomplete'), vms: [vm(100, 'missing')] },
    });
    const { container: el } = render(SecBackups, { props: { checks: [down] } });
    const all = pills(el);
    expect(texts(all)).toEqual(['Backup-Storage nicht aktiv']);
    expect(all[0].classList.contains('pill-warn')).toBe(true);
    expect(all[0].title).toBe(message);
    expect(await expand(el)).toEqual([]);
  });

  it('keeps the outage pill grey when the outage alert is off', () => {
    const quiet = check({
      status: 'unknown',
      message: 'Proxmox unavailable (timeout)',
      details: outage('timeout'),
    });
    const { container: el } = render(SecBackups, { props: { checks: [quiet] } });
    const all = pills(el);
    expect(texts(all)).toEqual(['Proxmox antwortet nicht (Zeitüberschreitung)']);
    expect(colored(all)).toEqual([]);
  });

  it('names each error code and falls back to a general text for an unknown one', () => {
    const codes = [
      'timeout',
      'cli_failed',
      'parse_failed',
      'backup_index_incomplete',
      'disk_full',
      null,
      7,
    ];
    const { container: el } = render(SecBackups, {
      props: {
        checks: codes.map((code, n) =>
          check({ status: 'warning', details: outage(code as string | null) }, `chk-${n}`),
        ),
      },
    });
    expect(texts(pills(el))).toEqual([
      'Proxmox antwortet nicht (Zeitüberschreitung)',
      'Proxmox-Abfrage fehlgeschlagen',
      'Proxmox-Ausgabe nicht lesbar',
      'Backup-Storage nicht aktiv',
      'Proxmox nicht verfügbar',
      'Proxmox nicht verfügbar',
      'Proxmox nicht verfügbar',
    ]);
  });

  it('names the error in English', () => {
    setLanguage('en');
    const codes = ['timeout', 'cli_failed', 'parse_failed', 'backup_index_incomplete', null];
    const { container: el } = render(SecBackups, {
      props: {
        checks: codes.map((code, n) =>
          check({ status: 'warning', details: outage(code) }, `chk-${n}`),
        ),
      },
    });
    expect(texts(pills(el))).toEqual([
      'Proxmox timed out',
      'Proxmox query failed',
      'Proxmox output unreadable',
      'Backup storage not active',
      'Proxmox unavailable',
    ]);
  });
});

describe('SecBackups with a Proxmox that answers', () => {
  it('shows the VMs of details written before R-0492 as before', async () => {
    const old = check({
      status: 'critical',
      details: { vms: [vm(100, 'ok'), vm(101, 'missing'), vm(102, 'ok')] },
    });
    const { container: el } = render(SecBackups, { props: { checks: [old] } });
    const all = pills(el);
    expect(texts(all)).toEqual(['1 Kein Backup', '2/3']);
    expect(all[0].classList.contains('pill-crit')).toBe(true);
    expect(await expand(el)).toEqual(['vm-100 (100)', 'vm-101 (101)', 'vm-102 (102)']);
  });

  it('shows all VMs ok with available true', () => {
    const fine = check({
      status: 'ok',
      details: { available: true, error: null, vms: [vm(100, 'ok'), vm(101, 'ok')] },
    });
    const { container: el } = render(SecBackups, { props: { checks: [fine] } });
    const all = pills(el);
    expect(texts(all)).toEqual(['Alle 2 VMs/CTs haben aktuelle Backups']);
    expect(all[0].classList.contains('pill-ok')).toBe(true);
  });

  it('shows a dash for the empty list after a missing block and for a host without VMs', () => {
    const missing = check(
      { status: 'unknown', message: 'No Proxmox data in report', details: { vms: [] } },
      'chk-missing',
    );
    const none = check(
      {
        status: 'ok',
        message: 'No VMs/CTs found',
        details: { available: true, error: null, vms: [] },
      },
      'chk-none',
    );
    const { container: el } = render(SecBackups, { props: { checks: [missing, none] } });
    const all = pills(el);
    expect(texts(all)).toEqual(['—', '—']);
    expect(colored(all)).toEqual([]);
  });
});

// A check switched to proxmox_backup in the form keeps its state, and with it
// the details of its old type, until the next push.
describe('SecBackups with details of another shape', () => {
  it('renders the details of an agent_resources check as a dash', () => {
    const switched = check({
      status: 'ok',
      message: 'All resources OK',
      details: { cpu: 3, memory: 40, problems: {} },
    });
    const { container: el } = render(SecBackups, { props: { checks: [switched] } });
    expect(texts(pills(el))).toEqual(['—']);
  });

  it('reads only a list of VM objects and a real false as an outage', () => {
    const odd = [
      { available: 'false', vms: { 100: vm(100, 'ok') } },
      { available: 0, vms: ['vm-101', null, 7, vm(100, 'ok')] },
    ];
    const { container: el } = render(SecBackups, {
      props: { checks: odd.map((details, n) => check({ status: 'ok', details }, `chk-${n}`)) },
    });
    expect(texts(pills(el))).toEqual(['—', 'Alle 1 VMs/CTs haben aktuelle Backups']);
  });

  it('shows a VM reported twice once', async () => {
    const twice = check({
      status: 'critical',
      details: { vms: [vm(100, 'missing'), vm(100, 'ok'), vm(101, 'ok')] },
    });
    const { container: el } = render(SecBackups, { props: { checks: [twice] } });
    expect(texts(pills(el))).toEqual(['1 Kein Backup', '1/2']);
    expect(await expand(el)).toEqual(['vm-100 (100)', 'vm-101 (101)']);
  });
});
