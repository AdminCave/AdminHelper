// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// arch-monitoring-ui T6 (R-1225, concept decision 9c): the desktop's dead man's switch.
// Pins the limit max(10 min, 2 × shortest interval), a result older than it, a server
// that stops answering, the recovery, silence without an enabled check or before the
// first answer, and that signing out stops the asking and drops a late answer.

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Writable } from 'svelte/store';
import type { MonitoringStatusSummary } from '$lib/api/types';

const h = vi.hoisted(() => ({ fetch: vi.fn() }));

vi.mock('$lib/api/monitoring', () => ({
  monitoringApi: { fetchStatusSummary: h.fetch },
}));
vi.mock('$lib/stores/session', async () => {
  const { writable, get } = await import('svelte/store');
  const session = writable<object | null>(null);
  return { session, currentSession: () => get(session) };
});

import * as sessionMod from '$lib/stores/session';
import {
  PULSE_INTERVAL_MS,
  monitoringSilentMinutes,
  pulseLimitMs,
  silentMinutes,
} from './monitoringPulse';

const session = sessionMod.session as unknown as Writable<object | null>;
const MIN = 60_000;
const T0 = Date.parse('2026-11-10T12:00:00Z');

function summary(over: Partial<MonitoringStatusSummary> = {}): MonitoringStatusSummary {
  return {
    total: 3,
    ok: 3,
    warning: 0,
    critical: 0,
    unknown: 0,
    pending: 0,
    lastResultAt: new Date(Date.now()).toISOString(),
    minIntervalS: 60,
    ...over,
  };
}
const ago = (ms: number) => new Date(Date.now() - ms).toISOString();

describe('pulse limit and evaluation', () => {
  it('is max(10 min, 2 × the shortest interval)', () => {
    expect(pulseLimitMs(null)).toBe(10 * MIN);
    expect(pulseLimitMs(60)).toBe(10 * MIN);
    expect(pulseLimitMs(300)).toBe(10 * MIN);
    expect(pulseLimitMs(3600)).toBe(120 * MIN);
  });

  it('says nothing before the first answer or without an enabled check', () => {
    const none = { summary: null, noResultSince: null, failingSince: T0 - 60 * MIN };
    expect(silentMinutes(none, T0)).toBeNull();
    const noChecks = {
      summary: { ...summary(), lastResultAt: '2026-11-09T00:00:00Z', minIntervalS: null },
      noResultSince: null,
      failingSince: T0 - 60 * MIN,
    };
    expect(silentMinutes(noChecks, T0)).toBeNull();
  });

  it('counts from the last result, from the first wait without one, or from the outage', () => {
    const base = { noResultSince: null, failingSince: null };
    const at = (iso: string | null) => ({ ...summary(), lastResultAt: iso });
    expect(silentMinutes({ ...base, summary: at('2026-11-10T11:50:00Z') }, T0)).toBeNull();
    expect(silentMinutes({ ...base, summary: at('2026-11-10T11:49:00Z') }, T0)).toBe(11);
    expect(
      silentMinutes({ ...base, summary: at('garbage'), noResultSince: T0 - 12 * MIN }, T0),
    ).toBe(12);
    const outage = { summary: at('2026-11-10T11:59:00Z'), noResultSince: null };
    expect(silentMinutes({ ...outage, failingSince: T0 - 9 * MIN }, T0)).toBeNull();
    // The server clock runs ahead, its last result lies in the future: the outage of
    // 11 min still counts on its own.
    expect(
      silentMinutes(
        { summary: at('2026-11-10T12:30:00Z'), noResultSince: null, failingSince: T0 - 11 * MIN },
        T0,
      ),
    ).toBe(11);
  });
});

describe('monitoringSilentMinutes', () => {
  let latest: number | null | undefined;
  let unsubscribe: () => void;

  beforeEach(() => {
    vi.useFakeTimers({ now: T0 });
    session.set(null);
    h.fetch.mockReset();
    latest = undefined;
    unsubscribe = monitoringSilentMinutes.subscribe((v) => (latest = v));
  });
  afterEach(() => {
    unsubscribe();
    session.set(null);
    vi.useRealTimers();
  });

  async function signIn(): Promise<void> {
    session.set({ serverUrl: 'https://hub.example', isAdmin: true });
    await vi.advanceTimersByTimeAsync(0);
  }

  it('asks only while a session exists, at sign-in and once a minute', async () => {
    h.fetch.mockImplementation(() => Promise.resolve(summary()));
    await vi.advanceTimersByTimeAsync(5 * PULSE_INTERVAL_MS);
    expect(h.fetch).not.toHaveBeenCalled();
    await signIn();
    expect(h.fetch).toHaveBeenCalledTimes(1);
    // A settings change re-fires the session store; it is no new sign-in.
    session.update((s) => ({ ...s }));
    await vi.advanceTimersByTimeAsync(3 * PULSE_INTERVAL_MS);
    expect(h.fetch).toHaveBeenCalledTimes(4);
    expect(latest).toBeNull();
  });

  it('never asks for a non-admin session, and follows a change of role', async () => {
    h.fetch.mockImplementation(() => Promise.resolve(summary()));
    session.set({ serverUrl: 'https://hub.example', isAdmin: false });
    await vi.advanceTimersByTimeAsync(3 * PULSE_INTERVAL_MS);
    expect(h.fetch).not.toHaveBeenCalled();
    expect(latest).toBeNull();
    session.set({ serverUrl: 'https://hub.example', isAdmin: true });
    await vi.advanceTimersByTimeAsync(0);
    expect(h.fetch).toHaveBeenCalledTimes(1);
    session.set({ serverUrl: 'https://hub.example', isAdmin: false });
    await vi.advanceTimersByTimeAsync(3 * PULSE_INTERVAL_MS);
    expect(h.fetch).toHaveBeenCalledTimes(1);
  });

  it('warns once the newest result is older than the limit', async () => {
    h.fetch.mockImplementation(() => Promise.resolve(summary({ lastResultAt: ago(9 * MIN) })));
    await signIn();
    expect(latest).toBeNull();
    h.fetch.mockImplementation(() => Promise.resolve(summary({ lastResultAt: ago(11 * MIN) })));
    await vi.advanceTimersByTimeAsync(PULSE_INTERVAL_MS);
    expect(latest).toBe(11);
  });

  it('holds a longer limit for long intervals', async () => {
    h.fetch.mockImplementation(() =>
      Promise.resolve(summary({ lastResultAt: ago(90 * MIN), minIntervalS: 3600 })),
    );
    await signIn();
    expect(latest).toBeNull();
  });

  it('warns when the server stops answering past the limit, and clears on recovery', async () => {
    h.fetch.mockImplementation(() => Promise.resolve(summary()));
    await signIn();
    h.fetch.mockImplementation(() => Promise.reject(new Error('Request timed out')));
    await vi.advanceTimersByTimeAsync(10 * PULSE_INTERVAL_MS);
    expect(latest).toBeNull();
    await vi.advanceTimersByTimeAsync(PULSE_INTERVAL_MS);
    expect(latest).toBe(11);
    h.fetch.mockImplementation(() => Promise.resolve(summary()));
    await vi.advanceTimersByTimeAsync(PULSE_INTERVAL_MS);
    expect(latest).toBeNull();
  });

  it('warns when enabled checks never delivered a first result', async () => {
    h.fetch.mockImplementation(() => Promise.resolve(summary({ lastResultAt: null })));
    await signIn();
    await vi.advanceTimersByTimeAsync(10 * PULSE_INTERVAL_MS);
    expect(latest).toBeNull();
    await vi.advanceTimersByTimeAsync(PULSE_INTERVAL_MS);
    expect(latest).toBe(11);
  });

  it('stays quiet without an enabled check, even while the server is down', async () => {
    h.fetch.mockImplementation(() =>
      Promise.resolve(summary({ lastResultAt: ago(600 * MIN), minIntervalS: null })),
    );
    await signIn();
    h.fetch.mockImplementation(() => Promise.reject(new Error('down')));
    await vi.advanceTimersByTimeAsync(30 * PULSE_INTERVAL_MS);
    expect(latest).toBeNull();
  });

  it('says nothing while the first answer never came', async () => {
    h.fetch.mockImplementation(() => Promise.reject(new Error('down')));
    await signIn();
    await vi.advanceTimersByTimeAsync(30 * PULSE_INTERVAL_MS);
    expect(latest).toBeNull();
  });

  it('signing out stops the asking, clears the warning and drops a late answer', async () => {
    h.fetch.mockImplementation(() => Promise.resolve(summary({ lastResultAt: ago(20 * MIN) })));
    await signIn();
    expect(latest).toBe(20);

    let answer: (s: MonitoringStatusSummary) => void = () => {};
    h.fetch.mockImplementation(() => new Promise((resolve) => (answer = resolve)));
    await vi.advanceTimersByTimeAsync(PULSE_INTERVAL_MS);
    session.set(null);
    expect(latest).toBeNull();
    answer(summary({ lastResultAt: ago(30 * MIN) }));
    await vi.advanceTimersByTimeAsync(10 * PULSE_INTERVAL_MS);
    expect(latest).toBeNull();
    expect(h.fetch).toHaveBeenCalledTimes(2);
  });
});
