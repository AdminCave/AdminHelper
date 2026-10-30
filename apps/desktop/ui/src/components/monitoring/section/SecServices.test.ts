// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// monitoring-services T6 (R-0418): a clean box showed a red "0 Probleme" pill
// without any data and "0/17 laufen" with only problems counted — no backend
// sent active_count. The pill took its colour from the raw details, not from
// the damped status the dot shows, and the list mode read watched[].running
// alone, so a name without data looked down. Pins the honest numbers, the
// neutral states and the translated notes.

import { describe, it, expect, afterEach, vi } from 'vitest';

// SecServices -> MonCheckLine -> ExpandChart -> MonChart -> uPlot, whose module
// init calls matchMedia (missing in jsdom). SecServices never renders a chart
// (showChart={false}) — stub the lib away, same as SecDocker.test.ts.
vi.mock('uplot', () => ({ default: class {} }));
import { render, cleanup } from '@testing-library/svelte';
import { tick } from 'svelte';
import { get } from 'svelte/store';
import type { MonitorCheck, MonitorCheckState } from '$lib/api/types';
import { setLanguage } from '$lib/i18n';
import { monitoring, toggleExpanded } from '$lib/stores/monitoring';
import SecServices from './SecServices.svelte';

const ID = 'chk-services';

function check(state: MonitorCheckState | null): MonitorCheck {
  return {
    id: ID,
    serverId: 'srv-1',
    name: 'Dienste',
    checkType: 'service_process',
    interval: '5m',
    severity: 'critical',
    enabled: true,
    state,
  } as MonitorCheck;
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

async function expand(el: HTMLElement): Promise<HTMLElement[]> {
  toggleExpanded(ID);
  await tick();
  return Array.from(el.querySelectorAll<HTMLElement>('.mon-expand-row'));
}

function row(r: HTMLElement): { name: string; note: string } {
  return {
    name: r.querySelector('.mon-expand-name')?.textContent?.trim() ?? '',
    note: r.querySelector('.mon-expand-note')?.textContent?.trim() ?? '',
  };
}

afterEach(() => {
  cleanup();
  if (get(monitoring).expandedCheckId === ID) toggleExpanded(ID);
  setLanguage('de');
});

describe('SecServices without data', () => {
  it('shows a neutral "Noch keine Daten" pill with the message, not a red one', () => {
    setLanguage('de');
    const waiting = check({ status: 'unknown', message: 'Waiting for agent data' });
    const { container: el } = render(SecServices, { props: { checks: [waiting] } });
    const all = pills(el);
    expect(texts(all)).toEqual(['Noch keine Daten']);
    expect(colored(all)).toEqual([]);
    expect(all[0].title).toBe('Waiting for agent data');
  });

  it('shows the neutral pill for a check that never ran', () => {
    setLanguage('de');
    const { container: el } = render(SecServices, { props: { checks: [check(null)] } });
    const all = pills(el);
    expect(texts(all)).toEqual(['Noch keine Daten']);
    expect(colored(all)).toEqual([]);
  });
});

describe('SecServices auto mode', () => {
  it('shows x/y active from the agent counts', async () => {
    setLanguage('de');
    const healthy = check({
      status: 'ok',
      message: 'All services OK',
      details: {
        mode: 'auto',
        failed: [],
        enabled_inactive: [],
        active_count: 41,
        total: 63,
      },
    });
    const { container: el } = render(SecServices, { props: { checks: [healthy] } });
    const all = pills(el);
    expect(texts(all)).toEqual(['Alle OK', '41/63 aktiv']);
    expect(all[0].classList.contains('pill-ok')).toBe(true);

    expect(await expand(el)).toEqual([]);
    expect(el.querySelector('.mon-expand-hint')?.textContent?.trim()).toBe(
      'Keine Probleme gefunden',
    );
  });

  it('shows the problem count beside the counts, coloured by the status', () => {
    setLanguage('de');
    const warn = check({
      status: 'warning',
      details: {
        mode: 'auto',
        failed: [],
        enabled_inactive: ['foo.service', 'bar.service'],
        active_count: 41,
        total: 63,
      },
    });
    const { container: el } = render(SecServices, { props: { checks: [warn] } });
    const all = pills(el);
    expect(texts(all)).toEqual(['2 Probleme', '41/63 aktiv']);
    expect(all[0].classList.contains('pill-warn')).toBe(true);
    expect(colored(all)).toEqual([all[0]]);
  });

  it('shows only the problem count without counts (agents before R-0418)', () => {
    setLanguage('de');
    const crit = check({
      status: 'critical',
      details: {
        mode: 'auto',
        failed: ['nginx.service'],
        enabled_inactive: ['foo.service'],
      },
    });
    const { container: el } = render(SecServices, { props: { checks: [crit] } });
    const all = pills(el);
    expect(texts(all)).toEqual(['2 Probleme']);
    expect(all[0].classList.contains('pill-crit')).toBe(true);
    expect(el.textContent).not.toMatch(/\d+\/\d+/);
  });

  it('says all OK without counts instead of "Alle 0 OK"', () => {
    setLanguage('de');
    const ok = check({
      status: 'ok',
      details: { mode: 'auto', failed: [], enabled_inactive: [] },
    });
    const { container: el } = render(SecServices, { props: { checks: [ok] } });
    const all = pills(el);
    expect(texts(all)).toEqual(['Alle OK']);
    expect(all[0].classList.contains('pill-ok')).toBe(true);
  });

  it('keeps the pill from turning red while the status is still ok (damped first failure)', async () => {
    setLanguage('de');
    const damped = check({
      status: 'ok',
      message: 'Failed: nginx.service (failure 1/2)',
      details: {
        mode: 'auto',
        failed: ['nginx.service'],
        enabled_inactive: [],
        active_count: 40,
        total: 63,
      },
    });
    const { container: el } = render(SecServices, { props: { checks: [damped] } });
    const all = pills(el);
    expect(texts(all)).toEqual(['1 Probleme', '40/63 aktiv']);
    expect(colored(all)).toEqual([]);
    // The dot and the pill share the effective status.
    expect(el.querySelector('.mon-line .mon-dot')?.classList.contains('mon-ok')).toBe(true);

    // The list below still comes from the details.
    const rows = await expand(el);
    expect(rows.map(row)).toEqual([{ name: 'nginx.service', note: 'fehlgeschlagen' }]);
  });

  it('shows a neutral "Keine Daten" pill when systemctl failed and the status is unknown', async () => {
    setLanguage('de');
    const err = check({
      status: 'unknown',
      message: 'Services not queryable: systemctl list-units failed: exit status 1',
      details: { mode: 'auto', failed: [], enabled_inactive: [] },
    });
    const { container: el } = render(SecServices, { props: { checks: [err] } });
    const all = pills(el);
    expect(texts(all)).toEqual(['Keine Daten']);
    expect(colored(all)).toEqual([]);
    expect(all[0].title).toBe('Services not queryable: systemctl list-units failed: exit status 1');

    // Neither rows nor the all-clear hint: the empty lists prove nothing.
    expect(await expand(el)).toEqual([]);
    expect(el.querySelector('.mon-expand-hint')).toBeNull();
  });
});

describe('SecServices list mode', () => {
  it('reads old details that carry running alone', async () => {
    setLanguage('de');
    const old = check({
      status: 'critical',
      details: {
        mode: 'list',
        watched: [
          { name: 'nginx', running: true },
          { name: 'sshd', running: false },
        ],
      },
    });
    const { container: el } = render(SecServices, { props: { checks: [old] } });
    const all = pills(el);
    expect(texts(all)).toEqual(['1 Probleme', '1/2 laufen']);
    expect(all[0].classList.contains('pill-crit')).toBe(true);

    const rows = await expand(el);
    expect(rows.map(row)).toEqual([{ name: 'sshd', note: 'läuft nicht' }]);
    expect(rows[0].classList.contains('level-crit')).toBe(true);
  });

  it('reads state and shows nodata neutrally as "nicht gefunden", never as down', async () => {
    setLanguage('de');
    const fresh = check({
      status: 'ok',
      details: {
        mode: 'list',
        watched: [
          { name: 'nginx', state: 'running', running: true },
          { name: 'firewalldd', state: 'nodata', running: false },
        ],
      },
    });
    const { container: el } = render(SecServices, { props: { checks: [fresh] } });
    const all = pills(el);
    expect(texts(all)).toEqual(['Alle OK', '1/2 laufen']);
    expect(all[0].classList.contains('pill-ok')).toBe(true);
    expect(el.querySelector('.pill-crit')).toBeNull();

    const rows = await expand(el);
    expect(rows.map(row)).toEqual([{ name: 'firewalldd', note: 'nicht gefunden' }]);
    expect(rows[0].className).not.toMatch(/level-(crit|warn)/);
    expect(rows[0].querySelector('.mon-dot')?.classList.contains('mon-unknown')).toBe(true);
    expect(el.querySelector('.mon-expand-hint')).toBeNull();
  });

  it('lists down before nodata and colours only the down row', async () => {
    setLanguage('de');
    const mixed = check({
      status: 'critical',
      details: {
        mode: 'list',
        watched: [
          { name: 'ghost', state: 'nodata', running: false },
          { name: 'nginx', state: 'down', running: false },
          { name: 'sshd', state: 'running', running: true },
        ],
      },
    });
    const { container: el } = render(SecServices, { props: { checks: [mixed] } });
    expect(texts(pills(el))).toEqual(['1 Probleme', '1/3 laufen']);

    const rows = await expand(el);
    expect(rows.map(row)).toEqual([
      { name: 'nginx', note: 'läuft nicht' },
      { name: 'ghost', note: 'nicht gefunden' },
    ]);
    expect(rows[0].classList.contains('level-crit')).toBe(true);
    expect(rows[1].className).not.toMatch(/level-(crit|warn)/);
  });

  it('shows a neutral "Keine Daten" pill when no name has data', async () => {
    setLanguage('de');
    const none = check({
      status: 'unknown',
      message: 'Services without data: nginx',
      details: { mode: 'list', watched: [{ name: 'nginx', state: 'nodata', running: false }] },
    });
    const { container: el } = render(SecServices, { props: { checks: [none] } });
    const all = pills(el);
    expect(texts(all)).toEqual(['Keine Daten']);
    expect(colored(all)).toEqual([]);
    expect(all[0].title).toBe('Services without data: nginx');

    const rows = await expand(el);
    expect(rows.map(row)).toEqual([{ name: 'nginx', note: 'nicht gefunden' }]);
  });

  // monitoring-services T7: a configuration saved before the editor dropped
  // duplicates still carries them, and the server copies them into watched; a
  // duplicate {#each} key made Svelte throw and the list did not render.
  it('shows a name watched twice once and counts it once', async () => {
    setLanguage('de');
    const twice = check({
      status: 'critical',
      details: {
        mode: 'list',
        watched: [
          { name: 'sshd', state: 'down', running: false },
          { name: 'nginx', state: 'running', running: true },
          { name: 'sshd', state: 'down', running: false },
        ],
      },
    });
    const { container: el } = render(SecServices, { props: { checks: [twice] } });
    const rows = await expand(el);
    expect(rows.map(row)).toEqual([{ name: 'sshd', note: 'läuft nicht' }]);
    // The pill counts what the list shows.
    expect(texts(pills(el))).toEqual(['1 Probleme', '1/2 laufen']);
  });
});

describe('SecServices auto mode duplicates', () => {
  // failed and enabled_inactive come from two systemctl calls in the agent: a
  // unit that fails in between stands in both. The first entry, failed, wins.
  it('shows a unit in failed and enabled_inactive once, as failed', async () => {
    setLanguage('de');
    const both = check({
      status: 'critical',
      details: {
        mode: 'auto',
        failed: ['foo.service'],
        enabled_inactive: ['foo.service', 'bar.service'],
      },
    });
    const { container: el } = render(SecServices, { props: { checks: [both] } });
    const rows = await expand(el);
    expect(rows.map(row)).toEqual([
      { name: 'foo.service', note: 'fehlgeschlagen' },
      { name: 'bar.service', note: 'inaktiv (Autostart)' },
    ]);
    expect(rows[0].classList.contains('level-crit')).toBe(true);
    expect(texts(pills(el))).toEqual(['2 Probleme']);
  });
});

// monitoring-linux-base-v2 T22: the checker rates only a failed .service (or a
// Windows service, a name without a unit suffix) critical, any other failed
// unit warning. Every failed row was red, so a failed data.mount looked as bad
// as a failed nginx.service.
describe('SecServices auto mode failed units', () => {
  function levels(rows: HTMLElement[]): (string | undefined)[] {
    return rows.map((r) => /\blevel-(\w+)\b/.exec(r.className)?.[1]);
  }

  function dots(rows: HTMLElement[]): (string | undefined)[] {
    return rows.map((r) => r.querySelector('.mon-dot')?.className);
  }

  it('colours a failed mount yellow, a failed service and a Windows service red', async () => {
    setLanguage('de');
    const mixed = check({
      status: 'critical',
      details: {
        mode: 'auto',
        failed: ['nginx.service', 'data.mount', 'Spooler'],
        enabled_inactive: ['foo.service'],
        active_count: 40,
        total: 63,
      },
    });
    const { container: el } = render(SecServices, { props: { checks: [mixed] } });
    // Order and count as before: failed in the agent's order, then inactive.
    expect(texts(pills(el))).toEqual(['4 Probleme', '40/63 aktiv']);

    const rows = await expand(el);
    expect(rows.map(row)).toEqual([
      { name: 'nginx.service', note: 'fehlgeschlagen' },
      { name: 'data.mount', note: 'fehlgeschlagen' },
      { name: 'Spooler', note: 'fehlgeschlagen' },
      { name: 'foo.service', note: 'inaktiv (Autostart)' },
    ]);
    expect(levels(rows)).toEqual(['crit', 'warn', 'crit', 'warn']);
    expect(dots(rows)).toEqual([
      'mon-dot mon-critical',
      'mon-dot mon-warning',
      'mon-dot mon-critical',
      'mon-dot mon-warning',
    ]);
  });

  it('colours every unit type of the checker other than .service yellow', async () => {
    setLanguage('de');
    // _UNIT_TYPES in apps/monitoring/app/checkers/agent.py without .service.
    const others = [
      'a.socket',
      'b.device',
      'c.mount',
      'd.automount',
      'e.swap',
      'f.target',
      'g.path',
      'h.timer',
      'i.slice',
      'j.scope',
    ];
    const units = check({
      status: 'warning',
      details: { mode: 'auto', failed: others, enabled_inactive: [] },
    });
    const { container: el } = render(SecServices, { props: { checks: [units] } });
    const all = pills(el);
    expect(texts(all)).toEqual(['10 Probleme']);
    expect(all[0].classList.contains('pill-warn')).toBe(true);

    const rows = await expand(el);
    expect(rows.map((r) => row(r).name)).toEqual(others);
    expect(levels(rows)).toEqual(others.map(() => 'warn'));
    expect(rows.map((r) => row(r).note)).toEqual(others.map(() => 'fehlgeschlagen'));
  });
});

describe('SecServices translations', () => {
  it('renders every note in English', async () => {
    setLanguage('en');
    const auto = check({
      status: 'critical',
      details: {
        mode: 'auto',
        failed: ['nginx.service'],
        enabled_inactive: ['foo.service'],
        active_count: 41,
        total: 63,
      },
    });
    const { container: el, unmount } = render(SecServices, { props: { checks: [auto] } });
    expect(texts(pills(el))).toEqual(['2 problems', '41/63 active']);
    expect((await expand(el)).map(row)).toEqual([
      { name: 'nginx.service', note: 'failed' },
      { name: 'foo.service', note: 'inactive (autostart)' },
    ]);
    toggleExpanded(ID);
    unmount();

    const list = check({
      status: 'critical',
      details: {
        mode: 'list',
        watched: [
          { name: 'sshd', state: 'down', running: false },
          { name: 'ghost', state: 'nodata', running: false },
        ],
      },
    });
    const { container: el2 } = render(SecServices, { props: { checks: [list] } });
    expect(texts(pills(el2))).toEqual(['1 problems', '0/2 running']);
    expect((await expand(el2)).map(row)).toEqual([
      { name: 'sshd', note: 'not running' },
      { name: 'ghost', note: 'not found' },
    ]);
  });

  it('renders the neutral and the all-OK pills in English', () => {
    setLanguage('en');
    const { container: el } = render(SecServices, {
      props: {
        checks: [
          check(null),
          {
            ...check({
              status: 'unknown',
              details: { mode: 'auto', failed: [], enabled_inactive: [] },
            }),
            id: 'chk-2',
          },
          {
            ...check({ status: 'ok', details: { mode: 'auto', failed: [], enabled_inactive: [] } }),
            id: 'chk-3',
          },
        ],
      },
    });
    expect(texts(pills(el))).toEqual(['No data yet', 'No data', 'All OK']);
  });

  it('renders the notes in German', async () => {
    setLanguage('de');
    const auto = check({
      status: 'critical',
      details: {
        mode: 'auto',
        failed: ['nginx.service'],
        enabled_inactive: ['foo.service'],
      },
    });
    const { container: el } = render(SecServices, { props: { checks: [auto] } });
    expect((await expand(el)).map(row)).toEqual([
      { name: 'nginx.service', note: 'fehlgeschlagen' },
      { name: 'foo.service', note: 'inaktiv (Autostart)' },
    ]);
  });
});

describe('SecServices details of the wrong form', () => {
  // A field of the wrong type counts as missing; a failed list that is no list
  // made the section throw.
  it('drops a field of the wrong type and keeps the others', async () => {
    setLanguage('de');
    const wrong = check({
      status: 'warning',
      details: {
        mode: 'auto',
        failed: 'nginx.service',
        enabled_inactive: ['foo.service', 'bar.service'],
        active_count: '41',
        total: 63,
      },
    });
    const { container: el } = render(SecServices, { props: { checks: [wrong] } });
    expect(texts(pills(el))).toEqual(['2 Probleme']);
    expect((await expand(el)).map(row).map((r) => r.name)).toEqual(['foo.service', 'bar.service']);
  });
});
