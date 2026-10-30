// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// monitoring-linux-base-v2 T17 (R-0423): agent_resources rates swap, inodes and
// load per CPU, and a disk only below its minimum free GB, with thresholds per
// mount and hysteresis. The live section showed none of the new values and
// coloured the rings and bars from the config, so a disk at 90 % with 600 GB
// free was yellow although the server rated it ok. Pins the swap ring, the load
// pill and the disk subtitles, the colour from details.problems, the rating from
// the config for details without problems, the grey ignored disk, and details
// without the new fields as before.

import { describe, it, expect, afterEach, vi } from 'vitest';

// SecLive -> MonCheckLine -> ExpandChart -> MonChart -> uPlot, whose module init
// calls matchMedia (missing in jsdom). Without a session the expanded chart only
// shows its placeholder — stub the lib away, same as SecServices.test.ts.
vi.mock('uplot', () => ({ default: class {} }));
import { render, cleanup } from '@testing-library/svelte';
import { tick } from 'svelte';
import { get } from 'svelte/store';
import type {
  MonitorCheck,
  MonitorCheckConfig,
  MonitorResourceDetails,
  MonitorResourceDisk,
} from '$lib/api/types';
import { setLanguage } from '$lib/i18n';
import { monitoring, toggleExpanded } from '$lib/stores/monitoring';
import SecLive from './SecLive.svelte';

const ID = 'chk-resources';

function check(details: MonitorResourceDetails, config: MonitorCheckConfig = {}): MonitorCheck {
  return {
    id: ID,
    serverId: 'srv-1',
    name: 'System Resources',
    checkType: 'agent_resources',
    interval: '5m',
    severity: 'warning',
    enabled: true,
    config,
    state: { status: 'ok', details },
  } as MonitorCheck;
}

function disk(mount: string, percent: number, more: Partial<MonitorResourceDisk> = {}) {
  return { mount, percent, total_gb: 50, used_gb: 12.3, ...more };
}

// Details as the checker writes them for an agent v3 on Linux.
function v3(more: Partial<MonitorResourceDetails> = {}): MonitorResourceDetails {
  return {
    cpu: 12,
    memory: 40,
    problems: {},
    memory_total_mb: 8000,
    memory_used_mb: 3200,
    swap: 5,
    swap_total_mb: 2048,
    swap_used_mb: 102,
    cpu_count: 4,
    load_per_cpu: 0.42,
    disks: [disk('/', 25, { free_gb: 37.7, inodes_percent: 4, ignored: false })],
    temperatures: [],
    ...more,
  };
}

function text(el: Element | null): string {
  return el?.textContent?.replace(/\s+/g, ' ').trim() ?? '';
}

function pills(el: HTMLElement): HTMLElement[] {
  return Array.from(el.querySelectorAll<HTMLElement>('.mon-live-pill'));
}

function levelOf(el: Element): string {
  return /\blevel-(\w+)\b/.exec(el.className.toString())?.[1] ?? '';
}

async function expand(el: HTMLElement) {
  toggleExpanded(ID);
  await tick();
  const rings = Array.from(el.querySelectorAll<HTMLElement>('.mon-ring')).map((r) => ({
    label: text(r.querySelector('.mon-ring-label')),
    pct: text(r.querySelector('.mon-ring-pct')),
    sub: text(r.querySelector('.mon-ring-sub')),
    level: levelOf(r),
  }));
  const bars = Array.from(el.querySelectorAll<HTMLElement>('.mon-hero-bar-row')).map((r) => ({
    mount: text(r.querySelector('.mon-hero-bar-label')),
    sub: text(r.querySelector('.mon-hero-bar-sub')),
    level: levelOf(r.querySelector('.mon-hero-bar-fill')!),
  }));
  return { rings, bars };
}

afterEach(() => {
  cleanup();
  if (get(monitoring).expandedCheckId === ID) toggleExpanded(ID);
  setLanguage('de');
});

describe('SecLive values', () => {
  it('shows swap, load per CPU, free GB and inodes from the details', async () => {
    setLanguage('de');
    const { container: el } = render(SecLive, { props: { checks: [check(v3())] } });
    expect(pills(el).map(text)).toEqual([
      'CPU 12%',
      'RAM 40%',
      'Swap 5%',
      'Load 0.42/CPU',
      '1 Disk',
    ]);
    const { rings, bars } = await expand(el);
    expect(rings).toEqual([
      { label: 'CPU', pct: '12%', sub: '', level: 'ok' },
      { label: 'RAM', pct: '40%', sub: '3200 / 8000 MB', level: 'ok' },
      { label: 'Swap', pct: '5%', sub: '102 / 2048 MB', level: 'ok' },
    ]);
    expect(bars).toEqual([
      { mount: '/', sub: '12.3 / 50.0 GB · 37.7 GB frei · Inodes 4%', level: 'ok' },
    ]);
  });

  it('shows no swap ring for a host without a swap device', async () => {
    setLanguage('de');
    const noSwap = v3({ swap: null, swap_total_mb: 0, swap_used_mb: 0 });
    const { container: el } = render(SecLive, { props: { checks: [check(noSwap)] } });
    expect(pills(el).map(text)).toEqual(['CPU 12%', 'RAM 40%', 'Load 0.42/CPU', '1 Disk']);
    const { rings } = await expand(el);
    expect(rings.map((r) => r.label)).toEqual(['CPU', 'RAM']);
  });

  it('shows details without the new fields as before', async () => {
    setLanguage('de');
    const old: MonitorResourceDetails = {
      cpu: 12,
      memory: 40,
      memory_total_mb: 8000,
      memory_used_mb: 3200,
      disks: [disk('/', 25)],
      temperatures: [],
    };
    const { container: el } = render(SecLive, { props: { checks: [check(old)] } });
    expect(pills(el).map(text)).toEqual(['CPU 12%', 'RAM 40%', '1 Disk']);
    const { rings, bars } = await expand(el);
    expect(rings.map((r) => r.label)).toEqual(['CPU', 'RAM']);
    expect(bars).toEqual([{ mount: '/', sub: '12.3 / 50.0 GB', level: 'ok' }]);
  });
});

describe('SecLive colours', () => {
  it('takes every colour from problems, also against the config', async () => {
    setLanguage('de');
    // Every value sits above the config's thresholds, the checker rates apart from it:
    // /data is ok by the free-GB gate, /srv only warns by its inodes.
    const details = v3({
      cpu: 50,
      memory: 99,
      swap: 3,
      load_per_cpu: 0.2,
      problems: {
        cpu: 'critical',
        swap: 'warning',
        load: 'critical',
        'disk:/': 'critical',
        'inode:/': 'warning',
        'inode:/srv': 'warning',
      },
      disks: [
        disk('/', 99, { free_gb: 0.5, inodes_percent: 85 }),
        disk('/data', 90, { free_gb: 600, inodes_percent: 1 }),
        disk('/srv', 10, { free_gb: 45, inodes_percent: 85 }),
      ],
    });
    const config: MonitorCheckConfig = { cpu_warn: 60, memory_warn: 80, disk_warn: 85 };
    const { container: el } = render(SecLive, { props: { checks: [check(details, config)] } });
    expect(pills(el).map((p) => [text(p), levelOf(p)])).toEqual([
      ['CPU 50%', 'crit'],
      ['RAM 99%', 'ok'],
      ['Swap 3%', 'warn'],
      ['Load 0.20/CPU', 'crit'],
      ['3 Disks', ''],
    ]);
    const { rings, bars } = await expand(el);
    expect(rings.map((r) => [r.label, r.level])).toEqual([
      ['CPU', 'crit'],
      ['RAM', 'ok'],
      ['Swap', 'warn'],
    ]);
    expect(bars.map((b) => [b.mount, b.level])).toEqual([
      ['/', 'crit'],
      ['/data', 'ok'],
      ['/srv', 'warn'],
    ]);
  });

  it('rates details without problems from the config as before', async () => {
    setLanguage('de');
    const old: MonitorResourceDetails = {
      cpu: 85,
      memory: 96,
      memory_total_mb: 8000,
      memory_used_mb: 7680,
      disks: [disk('/', 90), disk('/data', 90)],
      temperatures: [],
    };
    // Template thresholds without a config; then the check's own.
    const { container: el } = render(SecLive, { props: { checks: [check(old)] } });
    expect(pills(el).map((p) => [text(p), levelOf(p)])).toEqual([
      ['CPU 85%', 'warn'],
      ['RAM 96%', 'crit'],
      ['2 Disks', ''],
    ]);
    const { bars } = await expand(el);
    expect(bars.map((b) => b.level)).toEqual(['warn', 'warn']);
    cleanup();
    toggleExpanded(ID);

    const config: MonitorCheckConfig = { cpu_warn: 90, memory_crit: 99, disk_crit: 90 };
    const { container: el2 } = render(SecLive, { props: { checks: [check(old, config)] } });
    expect(pills(el2).map(levelOf)).toEqual(['ok', 'warn', '']);
    expect((await expand(el2)).bars.map((b) => b.level)).toEqual(['crit', 'crit']);
  });

  it('shows an ignored disk grey with its usage and the word ignored', async () => {
    setLanguage('de');
    const details = v3({
      problems: { 'disk:/': 'warning' },
      disks: [
        disk('/', 88, { free_gb: 6, inodes_percent: 4, ignored: false }),
        disk('/boot/efi', 99, { total_gb: 0.5, used_gb: 0.5, free_gb: 0, ignored: true }),
      ],
    });
    const { container: el } = render(SecLive, { props: { checks: [check(details)] } });
    const { bars } = await expand(el);
    expect(bars).toEqual([
      { mount: '/', sub: '12.3 / 50.0 GB · 6.0 GB frei · Inodes 4%', level: 'warn' },
      { mount: '/boot/efi', sub: 'ignoriert · 0.5 / 0.5 GB · 0.0 GB frei', level: 'ignored' },
    ]);
  });
});

describe('SecLive load in a container', () => {
  // T32: in a container load_5m is the host's and cpu_count may be the
  // container's, so the checker leaves the load unrated (load_rated false). The
  // pill keeps the value but goes grey with a hint, above any threshold too.
  function loadPill(el: HTMLElement): HTMLElement {
    return pills(el).find((p) => text(p).startsWith('Load'))!;
  }

  it('shows an unrated load grey with the hint, also above the thresholds', () => {
    setLanguage('de');
    // With the checker's problems and, rated from the config, without them.
    const variants: MonitorResourceDetails['problems'][] = [{}, undefined];
    for (const problems of variants) {
      const details = v3({ load_per_cpu: 4, load_rated: false, problems });
      const { container: el } = render(SecLive, { props: { checks: [check(details)] } });
      const p = loadPill(el);
      expect([text(p), levelOf(p), p.getAttribute('title')]).toEqual([
        'Load 4.00/CPU',
        'unrated',
        'im Container nicht bewertet',
      ]);
      cleanup();
    }
  });

  it('rates a load without load_rated as before, without the hint', () => {
    setLanguage('de');
    const details = v3({ load_per_cpu: 4, problems: undefined });
    const { container: el } = render(SecLive, { props: { checks: [check(details)] } });
    const p = loadPill(el);
    expect([text(p), levelOf(p), p.getAttribute('title')]).toEqual(['Load 4.00/CPU', 'crit', null]);
  });

  it('names the hint in English', () => {
    setLanguage('en');
    const details = v3({ load_rated: false });
    const { container: el } = render(SecLive, { props: { checks: [check(details)] } });
    expect(loadPill(el).getAttribute('title')).toBe('not rated in a container');
  });
});

describe('SecLive duplicate mounts', () => {
  // The bars were keyed by the mount alone: a report listing a mount twice made
  // Svelte throw and the disk list did not render.
  it('shows a mount listed twice as two bars, each rated', async () => {
    setLanguage('de');
    const details = v3({
      problems: { 'disk:/': 'warning' },
      disks: [
        disk('/', 88, { free_gb: 6 }),
        disk('/data', 10, { free_gb: 45 }),
        disk('/', 88, { free_gb: 6 }),
      ],
    });
    const { container: el } = render(SecLive, { props: { checks: [check(details)] } });
    expect(pills(el).map(text)).toContain('3 Disks');
    const { bars } = await expand(el);
    expect(bars).toEqual([
      { mount: '/', sub: '12.3 / 50.0 GB · 6.0 GB frei', level: 'warn' },
      { mount: '/data', sub: '12.3 / 50.0 GB · 45.0 GB frei', level: 'ok' },
      { mount: '/', sub: '12.3 / 50.0 GB · 6.0 GB frei', level: 'warn' },
    ]);
  });
});

describe('SecLive in English', () => {
  it('names free GB and an ignored disk in English', async () => {
    setLanguage('en');
    const details = v3({
      disks: [
        disk('/', 25, { free_gb: 37.7, inodes_percent: 4, ignored: false }),
        disk('/mnt/backup', 70, { free_gb: 15, ignored: true }),
      ],
    });
    const { container: el } = render(SecLive, { props: { checks: [check(details)] } });
    const { bars } = await expand(el);
    expect(bars.map((b) => b.sub)).toEqual([
      '12.3 / 50.0 GB · 37.7 GB free · Inodes 4%',
      'ignored · 12.3 / 50.0 GB · 15.0 GB free',
    ]);
  });
});

describe('SecLive details of the wrong form', () => {
  // A field of the wrong type counts as missing; a disk list that is no list
  // made the section throw.
  it('drops a field of the wrong type and keeps the others', () => {
    setLanguage('de');
    const wrong = { ...v3(), cpu: '12', disks: '/' } as unknown as MonitorResourceDetails;
    const { container: el } = render(SecLive, { props: { checks: [check(wrong)] } });
    expect(pills(el).map(text)).toEqual(['RAM 40%', 'Swap 5%', 'Load 0.42/CPU']);
  });
});
