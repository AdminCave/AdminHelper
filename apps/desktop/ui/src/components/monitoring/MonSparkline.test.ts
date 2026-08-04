// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// merker-cleanup T2: the sparkline lazily loads its series. Both load paths run
// INSIDE the $effect, so they need untrack() — load() reads `loaded` and
// $sessionStore, and without the guard those reads become dependencies of the
// very effect that writes them (effect_update_depth_exceeded). MonHeartbeatBar
// got that fix in T22; this pins it for the sparkline, including the
// no-IntersectionObserver fallback that is unreachable in a real browser.

import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, cleanup, waitFor } from '@testing-library/svelte';

const mocks = vi.hoisted(() => ({
  fetchMetrics: vi.fn(),
}));

vi.mock('$lib/api/monitoring', () => ({ monitoringApi: { fetchMetrics: mocks.fetchMetrics } }));
vi.mock('$lib/stores/session', async () => {
  const { writable } = await import('svelte/store');
  return { sessionStore: writable({ session: {}, settings: {} }) };
});

import MonSparkline from './MonSparkline.svelte';

const SERIES = {
  data: [
    {
      metric: { __name__: 'monitor_agent_cpu_percent_value' },
      values: [
        [1, '10'],
        [2, '20'],
        [3, '30'],
      ],
    },
  ],
};

// Fires immediately as intersecting, so the lazy load runs without a viewport.
class ImmediateIO {
  private cb: IntersectionObserverCallback;
  constructor(cb: IntersectionObserverCallback) {
    this.cb = cb;
  }
  observe = (el: Element) =>
    this.cb(
      [{ isIntersecting: true, target: el } as IntersectionObserverEntry],
      this as unknown as IntersectionObserver,
    );
  disconnect = () => {};
  unobserve = () => {};
  takeRecords = () => [] as IntersectionObserverEntry[];
}

const realIO = (window as unknown as { IntersectionObserver: unknown }).IntersectionObserver;

afterEach(() => {
  cleanup();
  mocks.fetchMetrics.mockReset();
  // jsdom has no IntersectionObserver, so realIO is undefined — assigning it
  // back would leave the property DEFINED (as undefined) and send a future
  // third test into the observer branch, where `new undefined()` throws.
  if (realIO === undefined) {
    delete (window as unknown as { IntersectionObserver?: unknown }).IntersectionObserver;
  } else {
    (window as unknown as { IntersectionObserver: unknown }).IntersectionObserver = realIO;
  }
});

describe('MonSparkline lazy load', () => {
  it('loads the series once through the observer path', async () => {
    (window as unknown as { IntersectionObserver: unknown }).IntersectionObserver = ImmediateIO;
    mocks.fetchMetrics.mockResolvedValue(SERIES);

    const { container } = render(MonSparkline, { props: { checkId: 'c1' } });

    await waitFor(() => expect(mocks.fetchMetrics).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(container.querySelector('svg path')).toBeTruthy());
  });

  it('falls back to an immediate load without IntersectionObserver, without looping', async () => {
    // The untrack() guard lives in exactly this branch: a synchronous load()
    // inside the effect would otherwise re-trigger it forever. One call proves
    // the guard holds — a loop would rack up dozens before the assertion.
    delete (window as unknown as { IntersectionObserver?: unknown }).IntersectionObserver;
    mocks.fetchMetrics.mockResolvedValue(SERIES);

    const { container } = render(MonSparkline, { props: { checkId: 'c1' } });

    await waitFor(() => expect(mocks.fetchMetrics).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(container.querySelector('svg path')).toBeTruthy());
    expect(mocks.fetchMetrics).toHaveBeenCalledTimes(1);
  });
});
