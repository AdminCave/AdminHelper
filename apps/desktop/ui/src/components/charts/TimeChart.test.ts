// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/svelte';
import { setLanguage } from '$lib/i18n';
import type { ChartSeries } from '$lib/charts';
import TimeChart from './TimeChart.svelte';

// jsdom measures 0 px, so the chart draws 800 px wide: the plot is 738 px from x = 46,
// and a grid of 10 points puts index i at clientX 46 + i * 82.
const T0 = 1_700_000_000;
const times = Array.from({ length: 10 }, (_, i) => T0 + i * 60);
const clientX = (i: number) => 46 + i * 82;

function series(extra: Partial<ChartSeries> = {}): ChartSeries[] {
  return [
    {
      key: 'cpu',
      label: 'CPU',
      color: 'red',
      data: times.map((_, i) => 10 + i),
      prev: times.map(() => 5),
      ...extra,
    },
    { key: 'ram', label: 'RAM', color: 'blue', data: times.map(() => 50) },
  ];
}

beforeEach(() => {
  setLanguage('en');
});
afterEach(() => cleanup());

describe('TimeChart', () => {
  it('draws one line per visible series and leaves a hidden one out', () => {
    const s = series();
    s[1].hidden = true;
    const { container } = render(TimeChart, { series: s, times, label: 'CPU history' });
    const lines = container.querySelectorAll('[data-testid="chart-line"]');
    expect([...lines].map((l) => l.getAttribute('data-series'))).toEqual(['cpu']);
    expect(container.querySelectorAll('[data-testid="chart-prev"]')).toHaveLength(1);
    expect(screen.getByRole('application', { name: 'CPU history' })).toBeTruthy();
  });

  it('shows the values, the previous period and nearby events under the cursor', async () => {
    // `events` is also a render option of testing-library, so the props go in explicitly.
    const { container } = render(TimeChart, {
      props: {
        series: series(),
        times,
        label: 'history',
        events: [{ at: T0 + 3 * 60, status: 'critical', label: 'Disk / critical' }],
      },
    });
    const chart = screen.getByRole('application');
    await fireEvent.mouseMove(chart, { clientX: clientX(3) });
    const rows = container.querySelectorAll('[data-testid="chart-tip-row"]');
    expect(rows).toHaveLength(2);
    expect(rows[0].textContent).toContain('CPU');
    expect(rows[0].textContent).toContain('13 %');
    expect(rows[0].textContent).toContain('before 5 %');
    expect(rows[1].textContent).toContain('50 %');
    expect(screen.getByRole('status').textContent).toContain('Disk / critical');

    await fireEvent.mouseLeave(chart);
    expect(screen.queryByRole('status')).toBeNull();
  });

  it('marks forecast points beyond nowIndex', async () => {
    render(TimeChart, { series: series(), times, label: 'history', nowIndex: 6 });
    expect(screen.getByText('now → forecast')).toBeTruthy();
    const chart = screen.getByRole('application');
    await fireEvent.mouseMove(chart, { clientX: clientX(8) });
    expect(screen.getByRole('status').textContent).toContain('Forecast');
    await fireEvent.mouseMove(chart, { clientX: clientX(5) });
    expect(screen.getByRole('status').textContent).not.toContain('Forecast');
  });

  it('hides the now line when the zoom lies right of it', () => {
    render(TimeChart, { series: series(), times, label: 'history', nowIndex: 5, zoom: [7, 9] });
    expect(screen.queryByText('now → forecast')).toBeNull();
  });

  it('zooms on a drag over at least three points and resets on double click', async () => {
    const onZoom = vi.fn();
    render(TimeChart, { series: series(), times, label: 'history', onZoom });
    const chart = screen.getByRole('application');

    await fireEvent.mouseDown(chart, { clientX: clientX(2) });
    await fireEvent.mouseMove(chart, { clientX: clientX(4) });
    await fireEvent.mouseUp(chart);
    expect(onZoom).not.toHaveBeenCalled();

    await fireEvent.mouseDown(chart, { clientX: clientX(7) });
    await fireEvent.mouseMove(chart, { clientX: clientX(2) });
    await fireEvent.mouseUp(chart);
    expect(onZoom).toHaveBeenCalledWith([2, 7]);

    await fireEvent.dblClick(chart);
    expect(onZoom).toHaveBeenLastCalledWith(null);
  });

  it('draws only the zoomed window', () => {
    const { container } = render(TimeChart, {
      series: series(),
      times,
      label: 'history',
      zoom: [4, 6],
    });
    const d = container.querySelector('[data-series="cpu"]')?.getAttribute('d') ?? '';
    expect(d.match(/[ML]/g)).toHaveLength(3);
    expect(d.startsWith('M46.0 ')).toBe(true);
  });

  it('moves the cursor with the keyboard', async () => {
    const { container } = render(TimeChart, { series: series(), times, label: 'history' });
    const chart = screen.getByRole('application');
    await fireEvent.focus(chart);
    const value = () => container.querySelector('[data-testid="chart-tip-row"]')?.textContent ?? '';
    expect(value()).toContain('19 %');
    await fireEvent.keyDown(chart, { key: 'ArrowLeft' });
    expect(value()).toContain('18 %');
    await fireEvent.keyDown(chart, { key: 'Home' });
    expect(value()).toContain('10 %');
    await fireEvent.keyDown(chart, { key: 'Escape' });
    expect(screen.queryByRole('status')).toBeNull();
  });

  it('draws thresholds, events and maintenance bands', () => {
    const { container } = render(TimeChart, {
      props: {
        series: series(),
        times,
        label: 'history',
        thresholds: [{ value: 80, status: 'warning', label: 'warn 80' }],
        events: [{ at: T0 + 120, status: 'ok', label: 'ok' }],
        bands: [{ start: T0 + 60, end: T0 + 240, label: 'Patch' }],
      },
    });
    expect(container.querySelectorAll('[data-testid="chart-threshold"]')).toHaveLength(1);
    expect(container.querySelectorAll('[data-testid="chart-event"]')).toHaveLength(1);
    expect(container.querySelectorAll('[data-testid="chart-band"]')).toHaveLength(1);
    expect(screen.getByText('warn 80')).toBeTruthy();
  });
});
