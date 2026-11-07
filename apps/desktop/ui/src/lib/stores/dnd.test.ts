// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// R-1078 do not disturb: the three durations, critical through, the end by timer with no
// stale timer left, and the stored point per workspace. R-1081: the person's quiet hours hold
// back like it, and critical passes both only while the person lets it.

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

const h = vi.hoisted(() => ({ context: null as unknown, passes: true, quiet: false }));

vi.mock('./notifyPrefs', () => ({
  criticalPasses: () => h.passes,
  inQuiet: () => h.quiet,
}));

vi.mock('./workspace', async () => {
  const { writable } = await import('svelte/store');
  const context = writable<unknown>(null);
  h.context = context;
  return { context };
});

import { get, type Writable } from 'svelte/store';
import { allows, dndEnd, dndUntil, endDnd, loadDnd, startDnd } from './dnd';

const ctx = () => h.context as Writable<unknown>;
const workspace = (id: string) => ({ launcher: false, workspace: { id } });
const NOW = new Date(2026, 10, 4, 9, 30); // 2026-11-04 09:30 local

describe('do not disturb', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(NOW);
    localStorage.clear();
    h.passes = true;
    h.quiet = false;
    ctx().set(workspace('ws-a'));
    endDnd();
  });

  afterEach(() => {
    endDnd();
    vi.useRealTimers();
  });

  it('ends in one hour, four hours, or at 07:00 local the next day', () => {
    expect(dndEnd('1h', NOW)).toBe(NOW.getTime() + 3_600_000);
    expect(dndEnd('4h', NOW)).toBe(NOW.getTime() + 4 * 3_600_000);
    expect(dndEnd('tomorrow', NOW)).toBe(new Date(2026, 10, 5, 7, 0).getTime());
    // Shortly before midnight "tomorrow" is still the next calendar day.
    const late = new Date(2026, 10, 30, 23, 50);
    expect(dndEnd('tomorrow', late)).toBe(new Date(2026, 11, 1, 7, 0).getTime());
  });

  it('holds back info and warning but lets critical through', () => {
    expect(allows('info')).toBe(true);
    startDnd('1h');
    expect(get(dndUntil)).toBe(NOW.getTime() + 3_600_000);
    expect(allows('info')).toBe(false);
    expect(allows('warning')).toBe(false);
    expect(allows('critical')).toBe(true);
    endDnd();
    expect(get(dndUntil)).toBeNull();
    expect(allows('warning')).toBe(true);
  });

  // jsdom queues a timer per storage event, so the timer count is no measure here; a stale
  // expiry timer shows itself instead by ending a later, longer quiet too early.
  it('ends by itself when the time is up, and only the latest start counts', () => {
    startDnd('1h');
    startDnd('4h');
    vi.advanceTimersByTime(3_600_000);
    expect(get(dndUntil)).toBe(NOW.getTime() + 4 * 3_600_000);
    vi.advanceTimersByTime(3 * 3_600_000);
    expect(get(dndUntil)).toBeNull();
    expect(allows('info')).toBe(true);
    expect(localStorage.getItem('ah.dnd.ws-a')).toBeNull();
  });

  it('ending drops the expiry timer', () => {
    startDnd('1h');
    endDnd();
    startDnd('4h');
    vi.advanceTimersByTime(3_600_000);
    expect(get(dndUntil)).toBe(NOW.getTime() + 4 * 3_600_000);
  });

  it('keeps the point per workspace and reads it again after a restart', () => {
    startDnd('1h');
    expect(localStorage.getItem('ah.dnd.ws-a')).toBe(String(NOW.getTime() + 3_600_000));
    expect(localStorage.getItem('ah.dnd.ws-b')).toBeNull();

    // Another workspace window: its own key, off.
    ctx().set(workspace('ws-b'));
    expect(get(dndUntil)).toBeNull();

    // Back in the first one, as after a restart: the stored point holds again.
    ctx().set(workspace('ws-a'));
    expect(get(dndUntil)).toBe(NOW.getTime() + 3_600_000);
    expect(allows('info')).toBe(false);
  });

  it('treats a stored point that has passed, or garbage, as off', () => {
    localStorage.setItem('ah.dnd.ws-a', String(NOW.getTime() - 1));
    loadDnd();
    expect(get(dndUntil)).toBeNull();
    expect(localStorage.getItem('ah.dnd.ws-a')).toBeNull();

    localStorage.setItem('ah.dnd.ws-a', 'soon');
    loadDnd();
    expect(get(dndUntil)).toBeNull();
    expect(localStorage.getItem('ah.dnd.ws-a')).toBeNull();
  });

  it('checks the time itself, not only the timer', () => {
    startDnd('1h');
    expect(allows('info', NOW.getTime() + 3_600_000)).toBe(true);
    expect(allows('info', NOW.getTime() + 3_599_999)).toBe(false);
  });

  it('critical waits for the end too once the person does not let it pass', () => {
    h.passes = false;
    expect(allows('critical')).toBe(true);
    startDnd('1h');
    expect(allows('critical')).toBe(false);
    expect(allows('critical', NOW.getTime() + 3_600_000)).toBe(true);
  });

  it('the quiet hours hold back like do not disturb, critical only without the pass', () => {
    h.quiet = true;
    expect(allows('info')).toBe(false);
    expect(allows('warning')).toBe(false);
    expect(allows('critical')).toBe(true);
    h.passes = false;
    expect(allows('critical')).toBe(false);
    h.quiet = false;
    expect(allows('critical')).toBe(true);
  });
});
