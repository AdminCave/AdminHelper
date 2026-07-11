// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { timeAgo } from './timeAgo';

// Stub translator: echoes the key (and count) so the bucketing is observable,
// and proves timeAgo uses the *passed* translator (the reactivity contract).
const t = (key: string, vars?: Record<string, unknown>) =>
  vars && 'count' in vars ? `${key}:${vars.count}` : key;

const ago = (ms: number) => new Date(Date.now() - ms).toISOString();
const MIN = 60_000;
const HOUR = 60 * MIN;
const DAY = 24 * HOUR;

describe('timeAgo', () => {
  // Freeze Date.now so ago() and timeAgo()'s own internal Date.now() observe the SAME instant —
  // otherwise time elapsed between the two calls (a GC pause, a slow CI runner) can push a
  // bucket-boundary fixture over the edge and flake the test (6.121).
  beforeEach(() => vi.spyOn(Date, 'now').mockReturnValue(1_700_000_000_000));
  afterEach(() => vi.restoreAllMocks());

  it('maps null / invalid / future to never', () => {
    expect(timeAgo(null, t)).toBe('timeAgo.never');
    expect(timeAgo(undefined, t)).toBe('timeAgo.never');
    expect(timeAgo('not-a-date', t)).toBe('timeAgo.never');
    expect(timeAgo(ago(-MIN), t)).toBe('timeAgo.never'); // future timestamp
  });

  it('buckets elapsed time into the right key', () => {
    expect(timeAgo(ago(5_000), t)).toBe('timeAgo.justNow');
    expect(timeAgo(ago(5 * MIN), t)).toBe('timeAgo.minutes:5');
    expect(timeAgo(ago(3 * HOUR), t)).toBe('timeAgo.hours:3');
    expect(timeAgo(ago(25 * HOUR), t)).toBe('timeAgo.yesterday');
    expect(timeAgo(ago(5 * DAY), t)).toBe('timeAgo.days:5');
    expect(timeAgo(ago(60 * DAY), t)).toBe('timeAgo.months:2');
    expect(timeAgo(ago(400 * DAY), t)).toBe('timeAgo.year:1');
  });

  it('uses the translator it is given (no global snapshot)', () => {
    const upper = (k: string) => k.toUpperCase();
    expect(timeAgo(null, upper)).toBe('TIMEAGO.NEVER');
  });
});
