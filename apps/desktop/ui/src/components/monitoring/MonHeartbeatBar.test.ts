// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// T22: the availability bar lazily loads the agent_ping status timeline and
// renders it through MonStatusTimeline; a failed load stays empty. The
// synchronously-firing IO stub below pins the untrack() guard — without it the
// load inside the effect loops (effect_update_depth_exceeded).

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

// Deterministic IntersectionObserver: fires immediately as intersecting so
// the lazy load runs without a real viewport.
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
(window as unknown as { IntersectionObserver: unknown }).IntersectionObserver = ImmediateIO;

import MonHeartbeatBar from './MonHeartbeatBar.svelte';

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe('MonHeartbeatBar (T22)', () => {
  it('loads the 24h status history and renders timeline segments', async () => {
    mocks.fetchMetrics.mockResolvedValueOnce({
      statusHistory: [
        {
          metric: { __name__: 'monitor_check_status_value' },
          values: [
            [1, '0'],
            [2, '0'],
            [3, '2'],
            [4, '0'],
          ],
        },
      ],
    });
    const { container } = render(MonHeartbeatBar, { props: { checkId: 'hb-1' } });
    await waitFor(() =>
      expect(mocks.fetchMetrics).toHaveBeenCalledWith(expect.anything(), 'hb-1', '24h'),
    );
    await waitFor(() =>
      expect(container.querySelectorAll('.mon-timeline-seg').length).toBeGreaterThanOrEqual(3),
    );
  });

  it('stays empty when the metrics request fails', async () => {
    mocks.fetchMetrics.mockRejectedValueOnce(new Error('down'));
    const { container } = render(MonHeartbeatBar, { props: { checkId: 'hb-2' } });
    await waitFor(() => expect(mocks.fetchMetrics).toHaveBeenCalled());
    expect(container.querySelectorAll('.mon-timeline-seg')).toHaveLength(0);
  });
});
