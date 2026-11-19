// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// arch-monitoring-neu-p0-abnahme T2 (R-1558): the large fleet of the data switch (Kevin
// 2026-11-19: hundreds of servers and checks must still read well) follows the same grammar as the
// small fixtures, is really large, and is the same on every load.
import { describe, expect, it, vi } from 'vitest';
import { duplicateKeys, grammarViolations } from '../grammar';
import { serverSummaries } from '../views/servers';
import { SCALE_OBJECTS } from './scale';

describe('scale fixtures', () => {
  it('follow the grammar and use every key once', () => {
    const bad = SCALE_OBJECTS.flatMap((o) => grammarViolations(o).map((v) => `${o.key}: ${v}`));
    expect(bad.slice(0, 10)).toEqual([]);
    expect(duplicateKeys(SCALE_OBJECTS)).toEqual([]);
  });

  it('is large, with a minority of servers in trouble', () => {
    const s = serverSummaries(SCALE_OBJECTS);
    const troubled = s.filter((x) => x.problems > 0).length;
    expect(s.length).toBe(292);
    expect(SCALE_OBJECTS.length).toBe(10510);
    expect(troubled).toBeGreaterThan(0);
    expect(troubled).toBeLessThan(s.length / 2);
  });

  it('rates every metric past its threshold like its row, so its bar takes the colour', () => {
    let rated = 0;
    const wrong: string[] = [];
    for (const o of SCALE_OBJECTS) {
      for (const m of o.metrics) {
        const t = m.threshold;
        if (!t || typeof m.value !== 'number') continue;
        const v = m.value;
        const past = (x?: number) => x !== undefined && (t.below ? v <= x : v >= x);
        const want = past(t.crit) ? 'critical' : past(t.warn) ? 'warning' : 'ok';
        if (want !== 'ok') rated += 1;
        // A silent host leaves its objects stale with the last rated value.
        const row = o.status === 'stale' ? want : o.status;
        if ((m.status ?? 'ok') !== want || (want !== 'ok' && row !== want)) {
          wrong.push(`${o.key} ${m.key}=${v} ${m.status ?? 'ok'}/${o.status}, expected ${want}`);
        }
      }
    }
    expect(wrong.slice(0, 10)).toEqual([]);
    expect(rated).toBeGreaterThan(0);
  });

  it('is the same on every load', async () => {
    vi.resetModules();
    const again = (await import('./scale')).SCALE_OBJECTS;
    expect(again).not.toBe(SCALE_OBJECTS);
    expect(again).toEqual(SCALE_OBJECTS);
  });
});
