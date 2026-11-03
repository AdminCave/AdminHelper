// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

import { describe, expect, it } from 'vitest';
import {
  daysUntilFull,
  forecast,
  formatAxis,
  formatTick,
  formatValue,
  indexOfTime,
  linearSlope,
  niceMax,
  stats,
  toCsv,
} from './charts';

describe('niceMax', () => {
  it('rounds up to 1, 2, 2.5, 5 or 10 times a power of ten', () => {
    expect(niceMax(0.8)).toBe(1);
    expect(niceMax(1)).toBe(1);
    expect(niceMax(1.3)).toBe(2);
    expect(niceMax(2.2)).toBe(2.5);
    expect(niceMax(44.8)).toBe(50);
    expect(niceMax(112)).toBe(200);
    expect(niceMax(600)).toBe(1000);
  });
  it('falls back to 1 without a positive finite maximum', () => {
    expect(niceMax(0)).toBe(1);
    expect(niceMax(-5)).toBe(1);
    expect(niceMax(Number.NaN)).toBe(1);
    expect(niceMax(Number.POSITIVE_INFINITY)).toBe(1);
  });
});

describe('stats', () => {
  it('covers only the window and skips missing samples', () => {
    const data = [100, 10, null, 30, 20, 100];
    expect(stats(data, 1, 4)).toEqual({ avg: 20, p95: 30, max: 30, cur: 20 });
  });
  it('is null for a window without a value', () => {
    expect(stats([null, null, 5], 0, 1)).toBeNull();
  });
  it('takes the 95th percentile from the sorted values', () => {
    const data = Array.from({ length: 20 }, (_, i) => i + 1);
    expect(stats(data, 0, 19)?.p95).toBe(20);
    expect(stats(data.slice(0, 10), 0, 9)?.p95).toBe(10);
  });
});

describe('linearSlope and daysUntilFull', () => {
  it('fits the slope over the present points', () => {
    expect(linearSlope([10, null, 14, 16])).toBeCloseTo(2);
  });
  it('is null below two points or for a flat x', () => {
    expect(linearSlope([null, 5])).toBeNull();
    expect(linearSlope([])).toBeNull();
  });
  it('turns the slope into days', () => {
    // 1 point per hour, 2 % per point: 40 % left = 20 h.
    expect(daysUntilFull(60, 2, 3600)).toBeCloseTo(20 / 24);
    expect(daysUntilFull(60, 0, 3600)).toBeNull();
    expect(daysUntilFull(60, -1, 3600)).toBeNull();
    expect(daysUntilFull(60, null, 3600)).toBeNull();
  });
});

describe('forecast', () => {
  it('starts at the last value on the last grid point and grows capped', () => {
    expect(forecast([50, 60, null], 30, 3)).toEqual([null, null, 60, 90, 100, 100]);
  });
  it('never falls', () => {
    expect(forecast([50], -5, 2)).toEqual([50, 50, 50]);
  });
  it('is all null without a value', () => {
    expect(forecast([null, null], 1, 2)).toEqual([null, null, null, null]);
    expect(forecast([], 1, 2)).toEqual([null, null]);
  });
});

describe('indexOfTime', () => {
  it('is fractional on the uniform grid', () => {
    expect(indexOfTime([100, 160, 220], 190)).toBe(1.5);
    expect(indexOfTime([100], 190)).toBe(0);
  });
});

describe('formatting', () => {
  it('formats values per unit', () => {
    expect(formatValue(42.4, '%')).toBe('42 %');
    expect(formatValue(12.6, 'ms')).toBe('13 ms');
    expect(formatValue(-3.25, 'Mbit/s')).toBe('3.3 Mbit/s');
    expect(formatValue(250.4, 'Mbit/s')).toBe('250 Mbit/s');
    expect(formatValue(0.456, '')).toBe('0.46');
    expect(formatValue(null, '%')).toBe('—');
    expect(formatValue(undefined, '%')).toBe('—');
  });
  it('formats axis labels per unit', () => {
    expect(formatAxis(50, '%')).toBe('50%');
    expect(formatAxis(12.4, 'ms')).toBe('12');
    expect(formatAxis(1.5, '')).toBe('1.5');
    expect(formatAxis(-25, 'Mbit/s')).toBe('25');
    expect(formatAxis(2.5, 'Mbit/s')).toBe('2.5');
  });
  it('picks the tick form by span', () => {
    const at = Date.UTC(2026, 10, 2, 14, 30) / 1000;
    const date = new Date(at * 1000);
    expect(formatTick(at, 30 * 86400, 'en-GB')).toBe(
      date.toLocaleDateString('en-GB', { day: '2-digit', month: '2-digit' }),
    );
    expect(formatTick(at, 7 * 86400, 'en-GB')).toBe(
      date.toLocaleString('en-GB', { weekday: 'short', hour: '2-digit', minute: '2-digit' }),
    );
    expect(formatTick(at, 3600, 'en-GB')).toBe(
      date.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' }),
    );
  });
});

describe('toCsv', () => {
  it('writes one row per grid time with empty cells for missing values', () => {
    const csv = toCsv(
      [0, 60],
      [
        { label: 'CPU', data: [1.5, null] },
        { label: 'RAM', data: [2] },
      ],
    );
    expect(csv).toBe('time,CPU,RAM\n1970-01-01T00:00:00.000Z,1.5,2\n1970-01-01T00:01:00.000Z,,\n');
  });
  it('quotes separators and defuses formula labels', () => {
    const csv = toCsv(
      [],
      [
        { label: 'disk "/", root', data: [] },
        { label: '=HYPERLINK("x")', data: [] },
        { label: '-1', data: [] },
        { label: '@SUM', data: [] },
      ],
    );
    expect(csv).toBe(`time,"disk ""/"", root","'=HYPERLINK(""x"")",'-1,'@SUM\n`);
  });
});
