// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// monitoring-silent-outages T11 (R-0419): a zpool that hung or failed showed
// the same bare "—" as a host whose zpool answers without pools. Pins the
// translated error in a pill coloured by the check status (grey with the
// outage alert off), the general text for an unknown code, and the dash and
// pool pills of a zpool that answers.

import { describe, it, expect, afterEach, vi } from 'vitest';

// SecZfs -> MonCheckLine -> ExpandChart -> MonChart -> uPlot, whose module init
// calls matchMedia (missing in jsdom). SecZfs never renders a chart
// (showChart={false}) — stub the lib away, same as SecDocker.test.ts.
vi.mock('uplot', () => ({ default: class {} }));
import { render, cleanup } from '@testing-library/svelte';
import { tick } from 'svelte';
import { get } from 'svelte/store';
import type { MonitorCheck, MonitorCheckState } from '$lib/api/types';
import { setLanguage } from '$lib/i18n';
import { monitoring, toggleExpanded } from '$lib/stores/monitoring';
import SecZfs from './SecZfs.svelte';

function check(state: MonitorCheckState, id = 'chk-zfs'): MonitorCheck {
  return {
    id,
    serverId: 'srv-1',
    name: 'ZFS',
    checkType: 'zfs_health',
    interval: '5m',
    severity: 'critical',
    enabled: true,
    state,
  } as MonitorCheck;
}

function outage(error: string | null) {
  return { available: false, error, pools: [] };
}

function pills(container: HTMLElement): HTMLElement[] {
  return Array.from(container.querySelectorAll<HTMLElement>('.mon-line-pill'));
}

function texts(list: HTMLElement[]): string[] {
  return list.map((p) => p.textContent?.replace(/\s+/g, ' ').trim() ?? '');
}

function colored(list: HTMLElement[]): HTMLElement[] {
  return list.filter((p) => /\bpill-(ok|warn|crit)\b/.test(p.className));
}

setLanguage('de');
afterEach(() => {
  cleanup();
  if (get(monitoring).expandedCheckId === 'chk-zfs') toggleExpanded('chk-zfs');
  setLanguage('de');
});

describe('SecZfs outage', () => {
  it('shows the translated error in a pill coloured by the status instead of a dash', () => {
    const message = 'ZFS unavailable (timeout): zpool list timed out';
    const down = check({ status: 'warning', message, details: outage('timeout') });
    const { container: el } = render(SecZfs, { props: { checks: [down] } });
    const all = pills(el);
    expect(texts(all)).toEqual(['zpool antwortet nicht (Zeitüberschreitung)']);
    expect(all[0].classList.contains('pill-warn')).toBe(true);
    expect(all[0].title).toBe(message);
  });

  it('keeps the outage pill grey when the outage alert is off', () => {
    const quiet = check({
      status: 'unknown',
      message: 'ZFS unavailable (cli_failed)',
      details: outage('cli_failed'),
    });
    const { container: el } = render(SecZfs, { props: { checks: [quiet] } });
    const all = pills(el);
    expect(texts(all)).toEqual(['zpool-Befehl fehlgeschlagen']);
    expect(colored(all)).toEqual([]);
  });

  it('names each error code and falls back to a general text for an unknown one', () => {
    const codes = ['timeout', 'cli_failed', 'disk_full', null];
    const { container: el } = render(SecZfs, {
      props: {
        checks: codes.map((code, n) =>
          check({ status: 'warning', details: outage(code) }, `chk-${n}`),
        ),
      },
    });
    expect(texts(pills(el))).toEqual([
      'zpool antwortet nicht (Zeitüberschreitung)',
      'zpool-Befehl fehlgeschlagen',
      'ZFS nicht verfügbar',
      'ZFS nicht verfügbar',
    ]);
  });

  it('names the error in English', () => {
    setLanguage('en');
    const { container: el } = render(SecZfs, {
      props: {
        checks: ['timeout', 'cli_failed', null].map((code, n) =>
          check({ status: 'warning', details: outage(code) }, `chk-${n}`),
        ),
      },
    });
    expect(texts(pills(el))).toEqual([
      'zpool timed out',
      'zpool command failed',
      'ZFS unavailable',
    ]);
  });
});

describe('SecZfs with a zpool that answers', () => {
  it('shows a dash for a host without pools', () => {
    const none = check({
      status: 'ok',
      message: 'No ZFS pools found',
      details: { available: true, error: null, pools: [] },
    });
    const { container: el } = render(SecZfs, { props: { checks: [none] } });
    expect(texts(pills(el))).toEqual(['—']);
  });

  it('shows the pools of details written before R-0419 as before', () => {
    const old = check({
      status: 'ok',
      details: { pools: [{ name: 'tank', health: 'ONLINE', capacityPercent: 42 }] },
    });
    const { container: el } = render(SecZfs, { props: { checks: [old] } });
    const all = pills(el);
    expect(texts(all)).toEqual(['tank 42%']);
    expect(all[0].classList.contains('pill-ok')).toBe(true);
  });
});

// arch-monitoring-ui-2 T10 (R-1227): below each pool's bar the last scrub with its age and
// errors, the fragmentation and the vdevs with errors, each only as far as the agent knew it.
describe('SecZfs pool details', () => {
  const NOW = Date.parse('2026-11-12T12:00:00Z') / 1000;
  const DAY = 24 * 3600;

  function pool(name: string, more: object) {
    return { name, health: 'ONLINE', capacityPercent: 42, ...more };
  }

  const pools = [
    pool('tank', {
      fragmentationPercent: 12,
      scrub: { state: 'FINISHED', errors: 0, end: NOW - 3 * DAY },
    }),
    pool('backup', {
      health: 'DEGRADED',
      scrub: { state: 'FINISHED', errors: 2, end: NOW - 2 * 3600 },
      vdevErrors: [
        { name: 'sda', read: 0, write: 0, checksum: 3 },
        { name: 'sdb', read: 1, write: 2, checksum: 0 },
      ],
    }),
    pool('single', { scrub: { state: 'FINISHED', errors: 1, end: NOW - 2 * 3600 } }),
    pool('fast', { scrub: { state: 'SCANNING', errors: 0 } }),
    pool('cold', { scrub: { state: 'RESILVERING', errors: 0, end: NOW + DAY } }),
    pool('plain', {}),
    pool('odd', {
      fragmentationPercent: '12',
      scrub: { state: 'FINISHED' },
      vdevErrors: [{ name: 'sdc', read: 1 }],
    }),
  ];

  function line(el: HTMLElement, name: string): HTMLElement | null {
    return el.querySelector<HTMLElement>(`[data-pool="${name}"]`);
  }

  function chips(el: HTMLElement, name: string): string[] {
    return Array.from(line(el, name)?.querySelectorAll<HTMLElement>('.mon-chip') ?? []).map(
      (c) => `${c.textContent?.replace(/\s+/g, ' ').trim()}|${/chip-(\w+)/.exec(c.className)?.[1]}`,
    );
  }

  async function shown() {
    vi.useFakeTimers({ toFake: ['Date'] });
    vi.setSystemTime(NOW * 1000);
    const c = check({ status: 'warning', details: { available: true, error: null, pools } });
    const { container: el } = render(SecZfs, { props: { checks: [c] } });
    toggleExpanded('chk-zfs');
    await tick();
    return el;
  }

  afterEach(() => {
    vi.useRealTimers();
  });

  it('names the finished scrub with its age and the fragmentation', async () => {
    const el = await shown();
    expect(chips(el, 'tank')).toEqual([
      'Scrub abgeschlossen · vor 3 Tagen|ok',
      'Fragmentierung 12 %|muted',
    ]);
  });

  it('marks a scrub with errors and names each vdev with errors', async () => {
    const el = await shown();
    expect(chips(el, 'backup')).toEqual([
      'Scrub abgeschlossen · vor 2 h · 2 Fehler|warn',
      'sda: 0 Lesen · 0 Schreiben · 3 Prüfsumme|warn',
      'sdb: 1 Lesen · 2 Schreiben · 0 Prüfsumme|warn',
    ]);
  });

  it('names a single scrub error without a plural', async () => {
    const el = await shown();
    expect(chips(el, 'single')).toEqual(['Scrub abgeschlossen · vor 2 h · 1 Fehler|warn']);
  });

  it('shows a running scrub without age and an unknown state by its name', async () => {
    const el = await shown();
    expect(chips(el, 'fast')).toEqual(['Scrub läuft|muted']);
    // An end ahead of this clock counts as now.
    expect(chips(el, 'cold')).toEqual(['Scrub: RESILVERING · gerade eben|muted']);
  });

  it('adds no line for a pool without details or with fields of the wrong type', async () => {
    const el = await shown();
    expect(line(el, 'plain')).toBeNull();
    expect(line(el, 'odd')).toBeNull();
    // The bars themselves stay as they were.
    expect(el.querySelectorAll('.mon-hero-bar-row')).toHaveLength(pools.length);
  });

  it('renders the details in English', async () => {
    setLanguage('en');
    const el = await shown();
    expect(chips(el, 'tank')).toEqual([
      'Scrub finished · 3 days ago|ok',
      'Fragmentation 12 %|muted',
    ]);
    expect(chips(el, 'single')).toEqual(['Scrub finished · 2 h ago · errors: 1|warn']);
    expect(chips(el, 'backup')).toEqual([
      'Scrub finished · 2 h ago · errors: 2|warn',
      'sda: 0 read · 0 write · 3 checksum|warn',
      'sdb: 1 read · 2 write · 0 checksum|warn',
    ]);
  });
});
