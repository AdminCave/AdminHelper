// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// monitoring-docker-parse T2 (R-0417): the docker pill said "Alle 4 Container
// laufen" while only one ran — exited/created/paused containers are rated ok,
// and the pill labelled the rating as "running". Without any docker data it
// showed a bare "—". Pins the label against the container states and the
// "keine Daten" pill with the check message as tooltip.

import { describe, it, expect, afterEach, vi } from 'vitest';

// SecDocker -> MonCheckLine -> ExpandChart -> MonChart -> uPlot, whose module
// init calls matchMedia (missing in jsdom). SecDocker never renders a chart
// (showChart={false}) — stub the lib away, same as MonCheckLine.edit.test.ts.
vi.mock('uplot', () => ({ default: class {} }));
import { render, cleanup } from '@testing-library/svelte';
import { tick } from 'svelte';
import { get } from 'svelte/store';
import type { MonitorCheck, MonitorCheckState } from '$lib/api/types';
import { setLanguage } from '$lib/i18n';
import { monitoring, toggleExpanded } from '$lib/stores/monitoring';
import SecDocker from './SecDocker.svelte';

const ID = 'chk-docker';

type Container = { name: string; image?: string; state: string; category: 'ok' };

function container(name: string, state: string): Container {
  return { name, image: 'example/app:1.0', state, category: 'ok' };
}

function check(state: MonitorCheckState): MonitorCheck {
  return {
    id: ID,
    serverId: 'srv-1',
    name: 'Docker',
    checkType: 'docker_health',
    interval: '5m',
    severity: 'critical',
    enabled: true,
    state,
  } as MonitorCheck;
}

function pills(container: HTMLElement): HTMLElement[] {
  return Array.from(container.querySelectorAll<HTMLElement>('.mon-line-pill'));
}

// Containers as the server rates them from R-0419 on.
type Category = 'ok' | 'warning' | 'critical' | 'stopped';
interface Rated {
  id: string;
  name: string;
  image: string;
  state: string;
  category: Category;
  reason: string | null;
  exit_code: number | null;
  restart_count: number | null;
}

function rated(
  name: string,
  state: string,
  category: Category,
  reason: string | null = null,
  more: Partial<Rated> = {},
): Rated {
  return {
    id: `${name}-id`,
    name,
    image: 'example/app:1.0',
    state,
    category,
    reason,
    exit_code: null,
    restart_count: 0,
    ...more,
  };
}

function details(containers: Rated[]) {
  return { available: true, error: null, containers };
}

function outage(error: string | null) {
  return { available: false, error, containers: [] };
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

setLanguage('de');
afterEach(() => {
  cleanup();
  if (get(monitoring).expandedCheckId === ID) toggleExpanded(ID);
  setLanguage('de');
});

describe('SecDocker pill', () => {
  it('counts only running containers as running', async () => {
    const mixed = check({
      status: 'ok',
      details: {
        containers: [
          container('demo-app-1', 'running'),
          container('demo-job-1', 'exited'),
          container('demo-init-1', 'created'),
          container('demo-cache-1', 'paused'),
        ],
      },
    });
    const { container: el } = render(SecDocker, { props: { checks: [mixed] } });
    const [pill, ...rest] = pills(el);
    expect(rest).toEqual([]);
    expect(pill.textContent?.trim()).toBe('1 von 4 laufen');
    expect(el.textContent).not.toContain('Alle 4 Container laufen');

    // The expanded hint follows the same count.
    toggleExpanded(ID);
    await tick();
    const hint = el.querySelector('.mon-expand-hint');
    expect(hint?.textContent?.trim()).toBe('1 von 4 laufen');
  });

  it('says all are running when every container runs', async () => {
    const running = check({
      status: 'ok',
      details: {
        containers: [container('demo-app-1', 'running'), container('demo-db-1', 'running')],
      },
    });
    const { container: el } = render(SecDocker, { props: { checks: [running] } });
    const [pill] = pills(el);
    expect(pill.textContent?.trim()).toBe('Alle 2 Container laufen');

    toggleExpanded(ID);
    await tick();
    expect(el.querySelector('.mon-expand-hint')?.textContent?.trim()).toBe(
      'Alle 2 Container laufen',
    );
  });

  it('shows "keine Daten" with the check message when docker data is missing', () => {
    const noData = check({ status: 'unknown', message: 'No Docker data in report' });
    const { container: el } = render(SecDocker, { props: { checks: [noData] } });
    const [pill, ...rest] = pills(el);
    expect(rest).toEqual([]);
    expect(pill.textContent?.trim()).toBe('keine Daten');
    expect(pill.title).toBe('No Docker data in report');
  });

  it('keeps the dash for an empty list that is not unknown', () => {
    const empty = check({ status: 'ok', message: 'No containers found' });
    const { container: el } = render(SecDocker, { props: { checks: [empty] } });
    const [pill, ...rest] = pills(el);
    expect(rest).toEqual([]);
    expect(pill.textContent?.trim()).toBe('—');
    expect(pill.title).toBe('');
  });
});

// monitoring-silent-outages T10 (R-0419): a docker daemon the agent could not
// read showed a bare "—", stopped containers vanished into the running count,
// and a row named the raw state instead of why a container is a problem. Pins
// the outage pill, the separate count of stopped containers, the translated
// reason per category, and the colours from the effective status, not from the
// details alone.

describe('SecDocker outage', () => {
  it('shows the translated error in a pill coloured by the status instead of a dash', async () => {
    const message = 'Docker unavailable (daemon_unreachable): cannot connect to the daemon';
    const down = check({
      status: 'warning',
      message,
      details: outage('daemon_unreachable'),
    });
    const { container: el } = render(SecDocker, { props: { checks: [down] } });
    const all = pills(el);
    expect(texts(all)).toEqual(['Docker-Daemon nicht erreichbar']);
    expect(all[0].classList.contains('pill-warn')).toBe(true);
    expect(all[0].title).toBe(message);

    expect(await expand(el)).toEqual([]);
    expect(el.querySelector('.mon-expand-hint')).toBeNull();
  });

  it('keeps the outage pill grey when the outage alert is off', () => {
    const quiet = check({
      status: 'unknown',
      message: 'Docker unavailable (timeout)',
      details: outage('timeout'),
    });
    const { container: el } = render(SecDocker, { props: { checks: [quiet] } });
    const all = pills(el);
    expect(texts(all)).toEqual(['Docker antwortet nicht (Zeitüberschreitung)']);
    expect(colored(all)).toEqual([]);
  });

  it('names each error code and falls back to a general text for an unknown one', () => {
    const codes = ['cli_failed', 'parse_failed', 'disk_full', null];
    const { container: el } = render(SecDocker, {
      props: {
        checks: codes.map((code, n) => ({
          ...check({ status: 'warning', details: outage(code) }),
          id: `chk-${n}`,
        })),
      },
    });
    expect(texts(pills(el))).toEqual([
      'Docker-Befehl fehlgeschlagen',
      'Docker-Ausgabe nicht lesbar',
      'Docker nicht verfügbar',
      'Docker nicht verfügbar',
    ]);
  });
});

describe('SecDocker counts stopped containers apart', () => {
  it('says "3 laufen · 1 gestoppt" instead of all running', async () => {
    const mixed = check({
      status: 'ok',
      message: '3 running, 1 stopped',
      details: details([
        rated('web', 'running', 'ok'),
        rated('db', 'running', 'ok'),
        rated('job', 'exited', 'stopped', 'stopped', { exit_code: 0 }),
        rated('cache', 'running', 'ok'),
      ]),
    });
    const { container: el } = render(SecDocker, { props: { checks: [mixed] } });
    const all = pills(el);
    expect(texts(all)).toEqual(['3 laufen · 1 gestoppt']);
    expect(all[0].classList.contains('pill-ok')).toBe(true);
    expect(el.textContent).not.toContain('Alle 4 Container laufen');

    const rows = await expand(el);
    expect(el.querySelector('.mon-expand-hint')?.textContent?.trim()).toBe('3 laufen · 1 gestoppt');
    // The stopped container last and neutral: neither green nor a problem.
    expect(rows.map(row)).toEqual([
      { name: 'web', note: 'running' },
      { name: 'db', note: 'running' },
      { name: 'cache', note: 'running' },
      { name: 'job', note: 'gestoppt' },
    ]);
    expect(rows[3].className).not.toMatch(/level-(ok|warn|crit)/);
    expect(rows[3].querySelector('.mon-dot')?.classList.contains('mon-unknown')).toBe(true);
  });

  it('counts running and stopped containers beside the problem pills', () => {
    const crit = check({
      status: 'critical',
      details: details([
        rated('web', 'running', 'ok'),
        rated('api', 'exited', 'critical', 'exit:1', { exit_code: 1 }),
        rated('cache', 'running', 'warning', 'unhealthy'),
        rated('init', 'created', 'stopped', 'created'),
      ]),
    });
    const { container: el } = render(SecDocker, { props: { checks: [crit] } });
    const all = pills(el);
    expect(texts(all)).toEqual(['1 ✗', '1 ⚠', '2 laufen · 1 gestoppt']);
    expect(all[0].classList.contains('pill-crit')).toBe(true);
    expect(all[1].classList.contains('pill-warn')).toBe(true);
    expect(colored(all)).toEqual([all[0], all[1]]);
  });
});

describe('SecDocker reasons', () => {
  const every = [
    rated('web', 'running', 'ok'),
    rated('job', 'exited', 'stopped', 'stopped', { exit_code: 0 }),
    rated('api', 'exited', 'critical', 'exit:3', { exit_code: 3 }),
    rated('worker', 'exited', 'critical', 'oom', { exit_code: 137 }),
    rated('broken', 'created', 'critical', 'start_failed', { exit_code: 127 }),
    rated('loop', 'restarting', 'critical', 'restarting', { restart_count: 12 }),
    rated('zombie', 'dead', 'critical', 'dead'),
    rated('sick', 'running', 'warning', 'unhealthy'),
    rated('flaky', 'running', 'warning', 'restarted', { restart_count: 3 }),
    rated('frozen', 'paused', 'warning', 'paused'),
    rated('odd', 'migrating', 'warning', 'unknown_state'),
    rated('later', 'running', 'warning', 'disk_full'),
    rated('init', 'created', 'stopped', 'created'),
  ];

  it('names the reason of each container, problems first and stopped last', async () => {
    const crit = check({ status: 'critical', details: details(every) });
    const { container: el } = render(SecDocker, { props: { checks: [crit] } });
    expect(texts(pills(el))).toEqual(['5 ✗', '5 ⚠', '4 laufen · 2 gestoppt']);

    const rows = await expand(el);
    expect(rows.map(row)).toEqual([
      { name: 'api', note: 'beendet mit Code 3' },
      { name: 'worker', note: 'Speicher erschöpft (OOM)' },
      { name: 'broken', note: 'Start fehlgeschlagen' },
      { name: 'loop', note: 'startet neu' },
      { name: 'zombie', note: 'defekt (dead)' },
      { name: 'sick', note: 'Healthcheck schlägt fehl' },
      { name: 'flaky', note: '3× neu gestartet' },
      { name: 'frozen', note: 'pausiert' },
      { name: 'odd', note: 'unbekannter Zustand: migrating' },
      // A code this UI does not know yet still says something.
      { name: 'later', note: 'unbekannter Grund (running)' },
      { name: 'web', note: 'running' },
      { name: 'job', note: 'gestoppt' },
      { name: 'init', note: 'nie gestartet' },
    ]);
    const levels = rows.map((r) => /level-(\w+)/.exec(r.className)?.[1]);
    expect(levels).toEqual([
      ...Array(5).fill('crit'),
      ...Array(5).fill('warn'),
      'ok',
      'none',
      'none',
    ]);
  });

  // Kevin 2026-10-17: a single restart stays in the details, the status ok.
  it('shows the reason of a single restart while the status stays ok', async () => {
    const once = check({
      status: 'ok',
      message: 'Container warnings: web: restarted (2 running, 0 stopped)',
      details: details([
        rated('web', 'running', 'warning', 'restarted', { restart_count: 1 }),
        rated('db', 'running', 'ok'),
      ]),
    });
    const { container: el } = render(SecDocker, { props: { checks: [once] } });
    const all = pills(el);
    expect(texts(all)).toEqual(['1 ⚠', 'Alle 2 Container laufen']);
    expect(colored(all)).toEqual([]);
    expect(el.querySelector('.mon-line .mon-dot')?.classList.contains('mon-ok')).toBe(true);

    const rows = await expand(el);
    expect(rows.map(row)).toEqual([
      { name: 'web', note: '1× neu gestartet' },
      { name: 'db', note: 'running' },
    ]);
    expect(rows[0].classList.contains('level-warn')).toBe(true);
  });

  it('renders the reasons, counts and errors in English', async () => {
    setLanguage('en');
    const crit = check({ status: 'critical', details: details(every) });
    const errors = ['daemon_unreachable', 'timeout', 'cli_failed', 'parse_failed', null].map(
      (code, n) => ({ ...check({ status: 'warning', details: outage(code) }), id: `chk-${n}` }),
    );
    const { container: el } = render(SecDocker, { props: { checks: [crit, ...errors] } });
    expect(texts(pills(el))).toEqual([
      '5 ✗',
      '5 ⚠',
      '4 running · 2 stopped',
      'Docker daemon unreachable',
      'Docker timed out',
      'Docker command failed',
      'Docker output unreadable',
      'Docker unavailable',
    ]);
    expect((await expand(el)).map((r) => row(r).note)).toEqual([
      'exited with code 3',
      'out of memory (OOM)',
      'failed to start',
      'restarting',
      'dead',
      'health check failing',
      'restarted 3×',
      'paused',
      'unknown state: migrating',
      'unknown reason (running)',
      'running',
      'stopped',
      'never started',
    ]);
  });
});

describe('SecDocker without docker data', () => {
  // The server empties the list once the docker block is gone (T5); the
  // section must not fall back to an all-clear for it.
  it('shows no stale containers once the docker block is gone', async () => {
    const gone = check({
      status: 'unknown',
      message: 'No Docker data in report',
      details: { containers: [] },
    });
    const { container: el } = render(SecDocker, { props: { checks: [gone] } });
    const all = pills(el);
    expect(texts(all)).toEqual(['keine Daten']);
    expect(all[0].title).toBe('No Docker data in report');
    expect(colored(all)).toEqual([]);

    expect(await expand(el)).toEqual([]);
    expect(el.querySelector('.mon-expand-hint')).toBeNull();
  });
});

describe('SecDocker duplicate containers', () => {
  // Rows are keyed; a duplicate key made Svelte throw and the list vanished.
  it('shows a container listed twice once and counts it once', async () => {
    const twice = check({
      status: 'ok',
      details: details([
        rated('web', 'running', 'ok'),
        rated('db', 'running', 'ok'),
        rated('web', 'running', 'ok'),
      ]),
    });
    const { container: el } = render(SecDocker, { props: { checks: [twice] } });
    expect(texts(pills(el))).toEqual(['Alle 2 Container laufen']);
    expect((await expand(el)).map(row)).toEqual([
      { name: 'web', note: 'running' },
      { name: 'db', note: 'running' },
    ]);
  });
});

describe('SecDocker details of the wrong form', () => {
  // A container without a state string is dropped instead of counted.
  it('drops a container with a field of the wrong type', async () => {
    const wrong = check({
      status: 'ok',
      details: {
        available: true,
        error: null,
        containers: [rated('web', 'running', 'ok'), { name: 'bad', state: 3, category: 'ok' }],
      },
    });
    const { container: el } = render(SecDocker, { props: { checks: [wrong] } });
    expect(texts(pills(el))).toEqual(['Alle 1 Container laufen']);
    expect((await expand(el)).map(row)).toEqual([{ name: 'web', note: 'running' }]);
  });
});
