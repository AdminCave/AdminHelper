// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

import { describe, it, expect } from 'vitest';
import type { MonCheckSummary, MonitorCheck } from '$lib/api/types';
import {
  worstStatusForServer,
  worstStatusOf,
  gaugeClass,
  checkTypeUnit,
  toCsv,
  parseCsv,
  parseIntCsv,
} from './monitoring';

const summary = (serverId: string, status?: MonCheckSummary['state']): MonCheckSummary => ({
  id: Math.random().toString(36),
  serverId,
  state: status ?? null,
});

describe('worstStatusForServer', () => {
  it('returns null when no checks match the server', () => {
    expect(worstStatusForServer([summary('s1', { status: 'ok' })], 's2')).toBeNull();
  });

  it('picks the most severe status by precedence order', () => {
    const checks = [
      summary('s1', { status: 'ok' }),
      summary('s1', { status: 'warning' }),
      summary('s1', { status: 'critical' }),
    ];
    expect(worstStatusForServer(checks, 's1')).toBe('critical');
  });

  it('treats a missing status as pending', () => {
    const checks = [summary('s1', { status: 'ok' }), summary('s1', {})];
    expect(worstStatusForServer(checks, 's1')).toBe('pending');
  });

  it('only considers checks for the given server', () => {
    const checks = [summary('s1', { status: 'ok' }), summary('s2', { status: 'critical' })];
    expect(worstStatusForServer(checks, 's1')).toBe('ok');
  });
});

describe('worstStatusOf', () => {
  it('defaults to ok for an empty list', () => {
    expect(worstStatusOf([])).toBe('ok');
  });

  it('returns the worst status across checks', () => {
    const checks = [
      { state: { status: 'warning' } },
      { state: { status: 'unknown' } },
    ] as unknown as MonitorCheck[];
    // warning(3) outranks unknown(2)
    expect(worstStatusOf(checks)).toBe('warning');
  });

  it('treats null/missing state as pending', () => {
    const checks = [{ state: null }] as unknown as MonitorCheck[];
    expect(worstStatusOf(checks)).toBe('pending');
  });
});

describe('gaugeClass', () => {
  it('returns crit at or above the crit threshold', () => {
    expect(gaugeClass(95, 80, 95)).toBe('gauge-crit');
    expect(gaugeClass(99, 80, 95)).toBe('gauge-crit');
  });

  it('returns warn at or above warn but below crit', () => {
    expect(gaugeClass(80, 80, 95)).toBe('gauge-warn');
    expect(gaugeClass(94, 80, 95)).toBe('gauge-warn');
  });

  it('returns ok below the warn threshold', () => {
    expect(gaugeClass(0, 80, 95)).toBe('gauge-ok');
    expect(gaugeClass(79, 80, 95)).toBe('gauge-ok');
  });
});

describe('checkTypeUnit', () => {
  it('returns " ms" for latency check types', () => {
    expect(checkTypeUnit('ping')).toBe(' ms');
    expect(checkTypeUnit('tcp')).toBe(' ms');
    expect(checkTypeUnit('http')).toBe(' ms');
  });

  it('returns "%" for percentage check types', () => {
    expect(checkTypeUnit('agent_resources')).toBe('%');
    expect(checkTypeUnit('zfs_health')).toBe('%');
  });

  it('returns " s" for agent_ping', () => {
    expect(checkTypeUnit('agent_ping')).toBe(' s');
  });

  it('returns empty string for unitless types', () => {
    expect(checkTypeUnit('service_process')).toBe('');
  });
});

describe('toCsv', () => {
  it('joins arrays with ", "', () => {
    expect(toCsv(['a', 'b', 'c'])).toBe('a, b, c');
  });

  it('returns empty string for null/undefined', () => {
    expect(toCsv(null)).toBe('');
    expect(toCsv(undefined)).toBe('');
  });

  it('stringifies scalar values', () => {
    expect(toCsv(42)).toBe('42');
  });
});

describe('parseCsv', () => {
  it('splits, trims and drops empties', () => {
    expect(parseCsv('a, b ,, c ')).toEqual(['a', 'b', 'c']);
  });

  it('returns empty array for empty input', () => {
    expect(parseCsv('')).toEqual([]);
  });
});

describe('parseIntCsv', () => {
  it('parses integers and drops non-numeric entries', () => {
    expect(parseIntCsv('1, 2, x, 3')).toEqual([1, 2, 3]);
  });

  it('returns empty array when nothing parses', () => {
    expect(parseIntCsv('a, b')).toEqual([]);
  });
});
