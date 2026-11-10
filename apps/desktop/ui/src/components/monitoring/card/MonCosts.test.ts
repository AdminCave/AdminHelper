// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// arch-monitoring-ui T6 (R-1225, concept §3.13): what monitoring costs one server, per
// agent collector, as a closed card on the server page. Pins the costliest-first order,
// the units, a braked collector and its factor, the closed line, no card while loading
// or without data, the error card, and that a late answer for the server before is dropped.

import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, waitFor } from '@testing-library/svelte';
import { tick } from 'svelte';
import type { MonitorCollectorCost, MonitorServerCosts } from '$lib/api/types';

const h = vi.hoisted(() => ({ fetch: vi.fn() }));

vi.mock('$lib/api/monitoring', () => ({ monitoringApi: { fetchServerCosts: h.fetch } }));
vi.mock('$lib/stores/session', () => ({
  currentSession: () => ({ serverUrl: 'https://hub.example' }),
}));

import { setLanguage } from '$lib/i18n';
import MonCosts, { byCost, isBraked } from './MonCosts.svelte';

function cost(collector: string, over: Partial<MonitorCollectorCost> = {}): MonitorCollectorCost {
  return {
    collector,
    durationMs: 10,
    cpuMs: 5,
    timeouts: 0,
    factor: 1,
    throttled: false,
    ...over,
  };
}

function costs(serverId: string, collectors: MonitorCollectorCost[]): MonitorServerCosts {
  return { serverId, window: '1h', collectors };
}

function rows(container: HTMLElement): string[][] {
  return Array.from(container.querySelectorAll('tbody tr')).map((tr) =>
    Array.from(tr.querySelectorAll('td')).map((td) => (td.textContent ?? '').trim()),
  );
}

async function open(container: HTMLElement): Promise<void> {
  await fireEvent.click(container.querySelector('.mon-card-toggle') as HTMLElement);
}

beforeAll(() => setLanguage('de'));
beforeEach(() => {
  h.fetch.mockReset();
});
afterEach(() => cleanup());

describe('cost order and brake', () => {
  it('sorts by CPU time, then duration, unknown last, then by name', () => {
    const list = [
      cost('b', { cpuMs: null, durationMs: 900 }),
      cost('a', { cpuMs: 5, durationMs: 1 }),
      cost('c', { cpuMs: 5, durationMs: 50 }),
      cost('d', { cpuMs: 40 }),
      cost('e', { cpuMs: null, durationMs: null }),
      cost('aa', { cpuMs: null, durationMs: null }),
    ];
    expect(list.sort(byCost).map((c) => c.collector)).toEqual(['d', 'c', 'a', 'b', 'aa', 'e']);
  });

  it('counts a factor above 1 or a held-back run as braked', () => {
    expect(isBraked(cost('x'))).toBe(false);
    expect(isBraked(cost('x', { factor: null, throttled: null }))).toBe(false);
    expect(isBraked(cost('x', { factor: 4 }))).toBe(true);
    expect(isBraked(cost('x', { factor: null, throttled: true }))).toBe(true);
  });
});

describe('MonCosts', () => {
  it('stays closed with a summary line and lists the costliest collector first', async () => {
    h.fetch.mockResolvedValue(
      costs('srv-1', [
        cost('system', { durationMs: 42.4, cpuMs: 12.6 }),
        cost('smart', { durationMs: 2345, cpuMs: 1530, timeouts: 3, factor: 4, throttled: true }),
        cost('docker', {
          durationMs: null,
          cpuMs: null,
          timeouts: null,
          factor: null,
          throttled: null,
        }),
      ]),
    );
    const { container } = render(MonCosts, { serverId: 'srv-1' });
    await waitFor(() => expect(container.querySelector('.mon-card')).not.toBeNull());
    expect(h.fetch).toHaveBeenCalledWith({ serverUrl: 'https://hub.example' }, 'srv-1');

    const toggle = container.querySelector('.mon-card-toggle') as HTMLElement;
    expect(toggle.getAttribute('aria-expanded')).toBe('false');
    expect(container.querySelector('.mon-card-title')?.textContent).toBe('Monitoring-Kosten');
    expect(container.querySelector('.mon-card-summary')?.textContent).toBe(
      'Collector: 3 · Gebremst: 1 · Zeitlimit-Treffer: 3',
    );
    expect(container.querySelector('.mon-card')?.hasAttribute('data-status')).toBe(false);

    await open(container);
    expect(container.querySelector('.costs-intro')?.textContent).toContain('über 1h');
    expect(rows(container)).toEqual([
      ['smart', '2,3 s', '1,5 s', '3', 'läuft einmal in 4 Läufen'],
      ['system', '42 ms', '13 ms', '0', 'nein'],
      ['docker', '—', '—', '—', '—'],
    ]);
    expect(container.querySelector('tr.braked')?.getAttribute('data-collector')).toBe('smart');
  });

  it('leaves the summary at the count when nothing is braked or timed out', async () => {
    h.fetch.mockResolvedValue(costs('srv-1', [cost('system'), cost('net')]));
    const { container } = render(MonCosts, { serverId: 'srv-1' });
    await waitFor(() =>
      expect(container.querySelector('.mon-card-summary')?.textContent).toBe('Collector: 2'),
    );
  });

  it('shows no card while loading nor for a server without measured collectors', async () => {
    let answer: (c: MonitorServerCosts) => void = () => {};
    h.fetch.mockImplementation(() => new Promise((resolve) => (answer = resolve)));
    const { container } = render(MonCosts, { serverId: 'srv-1' });
    await tick();
    expect(container.querySelector('.mon-card')).toBeNull();
    answer(costs('srv-1', []));
    await tick();
    await tick();
    expect(container.querySelector('.mon-card')).toBeNull();
  });

  it('says so in a closed card when the cost cannot be fetched', async () => {
    h.fetch.mockRejectedValue(new Error('HTTP 502'));
    const { container } = render(MonCosts, { serverId: 'srv-1' });
    await waitFor(() => expect(container.querySelector('.mon-card')).not.toBeNull());
    await open(container);
    expect(container.querySelector('.mon-card-body')?.textContent).toContain(
      'Kosten nicht abrufbar: HTTP 502',
    );
  });

  it('drops a late answer for the server shown before', async () => {
    const answers: Record<string, (c: MonitorServerCosts) => void> = {};
    h.fetch.mockImplementation(
      (_auth: unknown, id: string) => new Promise((resolve) => (answers[id] = resolve)),
    );
    const { container, rerender } = render(MonCosts, { serverId: 'srv-1' });
    await tick();
    await rerender({ serverId: 'srv-2' });
    answers['srv-2'](costs('srv-2', [cost('zfs')]));
    await waitFor(() => expect(container.querySelector('.mon-card')).not.toBeNull());
    answers['srv-1'](costs('srv-1', [cost('smart'), cost('system')]));
    await tick();
    await tick();
    await open(container);
    expect(rows(container).map((r) => r[0])).toEqual(['zfs']);
  });
});
