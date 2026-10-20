// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// monitoring-linux-base-v2 T21 (R-0423): the system_state check rates reboot
// required, clock sync, pending security updates and OOM kills, but the server
// dashboard had no section for it. Pins a pill per problem from
// details.problems coloured by the status (grey while damped), the four points
// with their value or "nicht ermittelt" when expanded, "Nicht bewertet" for the
// details of an agent without the block, and the English texts.

import { describe, it, expect, afterEach, vi } from 'vitest';

// SecSystem -> MonCheckLine -> ExpandChart -> MonChart -> uPlot, whose module
// init calls matchMedia (missing in jsdom). SecSystem never renders a chart
// (showChart={false}) — stub the lib away, same as SecZfs.test.ts.
vi.mock('uplot', () => ({ default: class {} }));
import { render, cleanup } from '@testing-library/svelte';
import { tick } from 'svelte';
import { get } from 'svelte/store';
import type { MonitorCheck, MonitorCheckState, MonitorSystemStateDetails } from '$lib/api/types';
import { setLanguage } from '$lib/i18n';
import { monitoring, toggleExpanded } from '$lib/stores/monitoring';
import SecSystem from './SecSystem.svelte';

const ID = 'chk-system';

function check(state: MonitorCheckState | null): MonitorCheck {
  return {
    id: ID,
    serverId: 'srv-1',
    name: 'System State',
    checkType: 'system_state',
    interval: '5m',
    severity: 'warning',
    enabled: true,
    state,
  } as MonitorCheck;
}

function details(over: Partial<MonitorSystemStateDetails>): MonitorSystemStateDetails {
  return {
    reboot_required: false,
    time_synchronized: true,
    security_updates: 0,
    oom_kills: 0,
    problems: [],
    ...over,
  };
}

const ALL_BAD = details({
  reboot_required: true,
  time_synchronized: false,
  security_updates: 3,
  oom_kills: 2,
  problems: ['reboot', 'time_sync', 'security_updates', 'oom'],
});

// What the checker writes without the block (agent before report version 3, Windows).
const NOT_EVALUATED = details({
  reboot_required: null,
  time_synchronized: null,
  security_updates: null,
  oom_kills: null,
});

function pills(el: HTMLElement): HTMLElement[] {
  return Array.from(el.querySelectorAll<HTMLElement>('.mon-line-pill'));
}

function texts(list: HTMLElement[]): string[] {
  return list.map((p) => p.textContent?.replace(/\s+/g, ' ').trim() ?? '');
}

function colored(list: HTMLElement[]): HTMLElement[] {
  return list.filter((p) => /\bpill-(ok|warn|crit)\b/.test(p.className));
}

async function expand(el: HTMLElement): Promise<HTMLElement[]> {
  toggleExpanded(ID);
  await tick();
  return Array.from(el.querySelectorAll<HTMLElement>('.mon-expand-row'));
}

function row(r: HTMLElement): { name: string; note: string; level: string; dot: string } {
  return {
    name: r.querySelector('.mon-expand-name')?.textContent?.trim() ?? '',
    note: r.querySelector('.mon-expand-note')?.textContent?.trim() ?? '',
    level: /\blevel-(\w+)/.exec(r.className)?.[1] ?? '',
    dot: r.querySelector('.mon-dot')?.className.replace('mon-dot', '').trim() ?? '',
  };
}

setLanguage('de');
afterEach(() => {
  cleanup();
  if (get(monitoring).expandedCheckId === ID) toggleExpanded(ID);
  setLanguage('de');
});

describe('SecSystem with a problem', () => {
  it('shows a pill per problem coloured by the status and each point with its value', async () => {
    const warn = check({ status: 'warning', message: 'Reboot required', details: ALL_BAD });
    const { container: el } = render(SecSystem, { props: { checks: [warn] } });
    expect(el.querySelector('.mon-section-title')?.textContent?.trim()).toBe('Systemzustand');
    const all = pills(el);
    expect(texts(all)).toEqual([
      'Neustart nötig',
      'Uhr nicht synchronisiert',
      'Sicherheits-Updates: 3',
      'OOM-Kills: 2',
    ]);
    expect(all.every((p) => p.classList.contains('pill-warn'))).toBe(true);

    expect((await expand(el)).map(row)).toEqual([
      { name: 'Neustart nötig', note: 'ja', level: 'warn', dot: 'mon-warning' },
      { name: 'Uhr synchronisiert', note: 'nein', level: 'warn', dot: 'mon-warning' },
      { name: 'Offene Sicherheits-Updates', note: '3', level: 'warn', dot: 'mon-warning' },
      { name: 'OOM-Kills seit dem letzten Report', note: '2', level: 'warn', dot: 'mon-warning' },
    ]);
  });

  it('keeps the pill grey while the status is still ok (damped first failure)', () => {
    const damped = check({
      status: 'ok',
      details: details({ oom_kills: 1, problems: ['oom'] }),
    });
    const { container: el } = render(SecSystem, { props: { checks: [damped] } });
    const all = pills(el);
    expect(texts(all)).toEqual(['OOM-Kills: 1']);
    expect(colored(all)).toEqual([]);
  });

  it('shows a problem name once and one this UI does not know by its raw name', () => {
    const odd = check({
      status: 'warning',
      details: details({ reboot_required: true, problems: ['reboot', 'reboot', 'kernel_taint'] }),
    });
    const { container: el } = render(SecSystem, { props: { checks: [odd] } });
    expect(texts(pills(el))).toEqual(['Neustart nötig', 'kernel_taint']);
  });
});

describe('SecSystem without a problem', () => {
  it('shows a green "Alles OK" pill and each point with its value', async () => {
    const ok = check({ status: 'ok', message: 'System state OK', details: details({}) });
    const { container: el } = render(SecSystem, { props: { checks: [ok] } });
    const all = pills(el);
    expect(texts(all)).toEqual(['Alles OK']);
    expect(all[0].classList.contains('pill-ok')).toBe(true);

    expect((await expand(el)).map(row)).toEqual([
      { name: 'Neustart nötig', note: 'nein', level: 'ok', dot: 'mon-ok' },
      { name: 'Uhr synchronisiert', note: 'ja', level: 'ok', dot: 'mon-ok' },
      { name: 'Offene Sicherheits-Updates', note: '0', level: 'ok', dot: 'mon-ok' },
      { name: 'OOM-Kills seit dem letzten Report', note: '0', level: 'ok', dot: 'mon-ok' },
    ]);
  });

  it('greys a bad value the checker does not name (switched off, clock after boot)', async () => {
    const quiet = check({
      status: 'ok',
      details: details({ reboot_required: true, time_synchronized: false }),
    });
    const { container: el } = render(SecSystem, { props: { checks: [quiet] } });
    expect(texts(pills(el))).toEqual(['Alles OK']);
    const rows = (await expand(el)).map(row);
    expect(rows.slice(0, 2)).toEqual([
      { name: 'Neustart nötig', note: 'ja', level: 'none', dot: 'mon-unknown' },
      { name: 'Uhr synchronisiert', note: 'nein', level: 'none', dot: 'mon-unknown' },
    ]);
  });
});

describe('SecSystem with a point not determined', () => {
  it('names each point the agent could not determine', async () => {
    const partial = check({
      status: 'ok',
      details: details({ reboot_required: null, security_updates: null }),
    });
    const { container: el } = render(SecSystem, { props: { checks: [partial] } });
    expect(texts(pills(el))).toEqual(['Alles OK']);
    expect((await expand(el)).map(row)).toEqual([
      { name: 'Neustart nötig', note: 'nicht ermittelt', level: 'none', dot: 'mon-unknown' },
      { name: 'Uhr synchronisiert', note: 'ja', level: 'ok', dot: 'mon-ok' },
      {
        name: 'Offene Sicherheits-Updates',
        note: 'nicht ermittelt',
        level: 'none',
        dot: 'mon-unknown',
      },
      { name: 'OOM-Kills seit dem letzten Report', note: '0', level: 'ok', dot: 'mon-ok' },
    ]);
  });

  it('shows a grey "Nicht bewertet" pill for the details of an agent without the block', async () => {
    const message = 'Not evaluated: no system state in report';
    const old = check({ status: 'ok', message, details: NOT_EVALUATED });
    const { container: el } = render(SecSystem, { props: { checks: [old] } });
    const all = pills(el);
    expect(texts(all)).toEqual(['Nicht bewertet']);
    expect(colored(all)).toEqual([]);
    expect(all[0].title).toBe(message);
    expect(await expand(el)).toEqual([]);
  });

  it('shows a dash before the first report', () => {
    const waiting = check({ status: 'unknown', message: 'Waiting for agent data' });
    const { container: el } = render(SecSystem, { props: { checks: [waiting] } });
    const all = pills(el);
    expect(texts(all)).toEqual(['—']);
    expect(colored(all)).toEqual([]);
  });
});

// A check switched to system_state in the form keeps its state, and with it the
// details of its old type, until the next push.
describe('SecSystem with details of another shape', () => {
  it('renders the details of an agent_resources check as "Nicht bewertet"', async () => {
    const switched = check({
      status: 'ok',
      message: 'All resources OK',
      details: { cpu: 3, memory: 40, problems: {} },
    });
    const { container: el } = render(SecSystem, { props: { checks: [switched] } });
    const all = pills(el);
    expect(texts(all)).toEqual(['Nicht bewertet']);
    expect(colored(all)).toEqual([]);
    expect(await expand(el)).toEqual([]);
  });

  it('counts only the types the checker writes and names the rest not determined', async () => {
    const odd = check({
      status: 'warning',
      details: {
        reboot_required: 'yes',
        time_synchronized: true,
        security_updates: 2.5,
        oom_kills: '1',
        problems: { cpu: 'warning' },
      },
    });
    const { container: el } = render(SecSystem, { props: { checks: [odd] } });
    const all = pills(el);
    expect(texts(all)).toEqual(['Alles OK']);
    expect(colored(all)).toEqual([]);
    expect((await expand(el)).map((r) => row(r).note)).toEqual([
      'nicht ermittelt',
      'ja',
      'nicht ermittelt',
      'nicht ermittelt',
    ]);
  });

  it('skips a problem entry that is not a name', () => {
    const odd = check({
      status: 'warning',
      details: details({ oom_kills: 1, problems: ['oom', 7, null] as unknown as string[] }),
    });
    const { container: el } = render(SecSystem, { props: { checks: [odd] } });
    expect(texts(pills(el))).toEqual(['OOM-Kills: 1']);
  });
});

describe('SecSystem in English', () => {
  it('names the problems, the points and their values in English', async () => {
    setLanguage('en');
    const warn = check({
      status: 'warning',
      details: { ...ALL_BAD, security_updates: null, problems: ['reboot', 'time_sync', 'oom'] },
    });
    const { container: el } = render(SecSystem, { props: { checks: [warn] } });
    expect(el.querySelector('.mon-section-title')?.textContent?.trim()).toBe('System state');
    expect(texts(pills(el))).toEqual(['Reboot required', 'Clock not synchronized', 'OOM kills: 2']);
    expect((await expand(el)).map((r) => [row(r).name, row(r).note])).toEqual([
      ['Reboot required', 'yes'],
      ['Clock synchronized', 'no'],
      ['Pending security updates', 'not determined'],
      ['OOM kills since the last report', '2'],
    ]);
  });

  it('says "Not evaluated", "All OK" and the security update count in English', () => {
    setLanguage('en');
    const { container: el } = render(SecSystem, {
      props: {
        checks: [
          check({ status: 'ok', details: NOT_EVALUATED }),
          { ...check({ status: 'ok', details: details({}) }), id: 'chk-ok' },
          {
            ...check({
              status: 'warning',
              details: details({ security_updates: 4, problems: ['security_updates'] }),
            }),
            id: 'chk-updates',
          },
        ],
      },
    });
    expect(texts(pills(el))).toEqual(['Not evaluated', 'All OK', 'Security updates: 4']);
  });
});
