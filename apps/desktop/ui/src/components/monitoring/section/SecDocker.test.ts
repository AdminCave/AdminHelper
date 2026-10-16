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

setLanguage('de');
afterEach(() => {
  cleanup();
  if (get(monitoring).expandedCheckId === ID) toggleExpanded(ID);
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
    const noData = check({ status: 'unknown', message: 'Keine Docker-Daten im Report' });
    const { container: el } = render(SecDocker, { props: { checks: [noData] } });
    const [pill, ...rest] = pills(el);
    expect(rest).toEqual([]);
    expect(pill.textContent?.trim()).toBe('keine Daten');
    expect(pill.title).toBe('Keine Docker-Daten im Report');
  });

  it('keeps the dash for an empty list that is not unknown', () => {
    const empty = check({ status: 'ok', message: 'Keine Container gefunden' });
    const { container: el } = render(SecDocker, { props: { checks: [empty] } });
    const [pill, ...rest] = pills(el);
    expect(rest).toEqual([]);
    expect(pill.textContent?.trim()).toBe('—');
    expect(pill.title).toBe('');
  });
});
