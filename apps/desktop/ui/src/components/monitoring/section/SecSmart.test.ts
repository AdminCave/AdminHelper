// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// api-contracts T24 (R-0687): the section reads its details through
// smartDetails, so details of the wrong form render the empty section instead
// of throwing.

import { describe, it, expect, afterEach, vi } from 'vitest';

// SecSmart -> MonCheckLine -> ExpandChart -> MonChart -> uPlot, whose module init
// calls matchMedia (missing in jsdom); same stub as SecZfs.test.ts.
vi.mock('uplot', () => ({ default: class {} }));
import { render, cleanup } from '@testing-library/svelte';
import { tick } from 'svelte';
import { get } from 'svelte/store';
import type { MonitorCheck, MonitorCheckState } from '$lib/api/types';
import { monitoring, toggleExpanded } from '$lib/stores/monitoring';
import { t, currentLocale } from '$lib/i18n';
import SecSmart from './SecSmart.svelte';

function check(state: MonitorCheckState): MonitorCheck {
  return {
    id: 'chk-smart',
    serverId: 'srv-1',
    name: 'SMART',
    checkType: 'smart_health',
    interval: '1h',
    severity: 'critical',
    enabled: true,
    state,
  } as MonitorCheck;
}

function texts(el: HTMLElement, selector: string): string[] {
  return Array.from(el.querySelectorAll<HTMLElement>(selector)).map(
    (p) => p.textContent?.replace(/\s+/g, ' ').trim() ?? '',
  );
}

afterEach(() => {
  cleanup();
  if (get(monitoring).expandedCheckId === 'chk-smart') toggleExpanded('chk-smart');
});

describe('SecSmart', () => {
  it('shows the hottest disk and the disk count', () => {
    const disks = [
      { device: '/dev/sda', kind: 'HDD', category: 'ok', temp_c: 38 },
      { device: '/dev/nvme0', kind: 'NVMe', category: 'warning', temp_c: 51 },
    ];
    const { container: el } = render(SecSmart, {
      props: { checks: [check({ status: 'ok', details: { disks } })] },
    });
    expect(texts(el, '.mon-line-num')).toEqual(['51']);
    expect(texts(el, '.mon-line-pill')).toEqual(['2 Disks']);
  });

  it('shows a dash for a host without disks', () => {
    const { container: el } = render(SecSmart, {
      props: { checks: [check({ status: 'ok', details: { absent: 'no_devices' } })] },
    });
    expect(texts(el, '.mon-line-pill')).toEqual(['—']);
  });

  it('renders the empty section for details of the wrong form', () => {
    const { container: el } = render(SecSmart, {
      props: { checks: [check({ status: 'ok', details: { disks: { sda: { temp_c: 40 } } } })] },
    });
    expect(texts(el, '.mon-line-pill')).toEqual(['—']);
    expect(texts(el, '.mon-line-num')).toEqual([]);
  });

  // R-1568: a disk without a SMART verdict is rated unknown, which is not a pass.
  it('shows a disk without a SMART verdict with a neutral chip, not as OK', async () => {
    const disks = [
      { device: '/dev/sda', kind: 'HDD', category: 'ok', temp_c: 38 },
      { device: '/dev/sdb', kind: 'HDD', category: 'unknown', temp_c: 40 },
      { device: '/dev/sdc', kind: 'HDD', category: 'warning', temp_c: 41 },
      { device: '/dev/sdd', kind: 'HDD', category: 'critical', temp_c: 42 },
    ];
    const { container: el } = render(SecSmart, {
      props: { checks: [check({ status: 'unknown', details: { disks } })] },
    });
    toggleExpanded('chk-smart');
    await tick();
    const chips = Array.from(el.querySelectorAll<HTMLElement>('.mon-hero-bar-row .mon-chip')).map(
      (c) => `${c.textContent?.trim()}|${/chip-(\w+)/.exec(c.className)?.[1]}`,
    );
    expect(chips).toEqual(['OK|ok', 'N/A|muted', 'WARN|warn', 'CRIT|crit']);
  });

  // R-1569: the agent leaves a sleeping disk asleep; the section names it and the time of its
  // last read state, and a read disk gets no such line.
  it('says a disk sleeps and from when its values are', async () => {
    const readAt = '2026-11-19T04:00:00Z';
    const disks = [
      {
        device: '/dev/sda',
        kind: 'HDD',
        category: 'warning',
        temp_c: 38,
        standby: true,
        read_at: readAt,
      },
      { device: '/dev/sdb', kind: 'HDD', category: 'ok', standby: true },
      { device: '/dev/sdc', kind: 'HDD', category: 'ok', temp_c: 35, read_at: readAt },
      { device: '/dev/sdd', kind: 'HDD', category: 'ok', standby: true, read_at: 'not a date' },
    ];
    const { container: el } = render(SecSmart, {
      props: { checks: [check({ status: 'warning', details: { disks } })] },
    });
    toggleExpanded('chk-smart');
    await tick();
    const time = new Date(readAt).toLocaleString(currentLocale(), {
      dateStyle: 'short',
      timeStyle: 'short',
    });
    const rows = Array.from(el.querySelectorAll<HTMLElement>('.mon-hero-bar-row')).map(
      (r) => r.querySelector('.mon-sub-asleep')?.textContent?.trim() ?? null,
    );
    expect(rows).toEqual([
      get(t)('monitoring.smart.asleepSince', { time }),
      get(t)('monitoring.smart.asleepNever'),
      null,
      get(t)('monitoring.smart.asleepNever'),
    ]);
    expect(rows[0]).toContain(time);
  });

  it('drops a standby or read_at of the wrong type instead of the disk', async () => {
    const disks = [{ device: '/dev/sda', category: 'ok', temp_c: 30, standby: 'yes', read_at: 5 }];
    const { container: el } = render(SecSmart, {
      props: { checks: [check({ status: 'ok', details: { disks } })] },
    });
    expect(texts(el, '.mon-line-pill')).toEqual(['1 Disk']);
    toggleExpanded('chk-smart');
    await tick();
    expect(el.querySelectorAll('.mon-hero-bar-row')).toHaveLength(1);
    expect(el.querySelector('.mon-sub-asleep')).toBeNull();
  });
});
