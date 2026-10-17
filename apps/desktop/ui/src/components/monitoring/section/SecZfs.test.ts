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
import type { MonitorCheck, MonitorCheckState } from '$lib/api/types';
import { setLanguage } from '$lib/i18n';
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
      message: 'Keine ZFS-Pools gefunden',
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
