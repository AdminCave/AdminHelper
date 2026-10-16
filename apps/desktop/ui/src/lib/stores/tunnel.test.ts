// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Tunnel store (R-0402): an activation reconciles right away and then every 60 s, one
// reconciliation at a time; "no tunnels" is a quiet idle, an error leaves the tunnel as it
// is. The mappings fallback (6.45) stays: a failed fetchTunnels keeps the tunnel running,
// otherwise the connect flow no longer resolves connections through the tunnel — a failure
// only the manual tunnel live-E2E would otherwise catch.

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { get } from 'svelte/store';
import type { RefreshOutcome, TunnelMapping, TunnelRefresh } from '$lib/bridge/types';

const h = vi.hoisted(() => ({
  refreshTunnel: vi.fn(),
  fetchTunnels: vi.fn(),
  stopTunnel: vi.fn(),
  reportError: vi.fn(),
  session: {
    session: null as { serverUrl: string; token: string; username: string } | null,
    settings: { mode: 'server' },
  },
}));

vi.mock('$lib/bridge', () => ({
  refreshTunnel: h.refreshTunnel,
  fetchTunnels: h.fetchTunnels,
  stopTunnel: h.stopTunnel,
}));
vi.mock('./statusBar', () => ({ reportError: h.reportError }));
vi.mock('$lib/i18n', () => ({ tNow: (k: string) => k }));
vi.mock('./session', () => ({
  sessionStore: {
    subscribe: (run: (v: unknown) => void) => {
      run(h.session);
      return () => {};
    },
  },
}));

import {
  startIfServerMode,
  refreshNow,
  stop,
  tunnelUi,
  getMappings,
  markTerminated,
  markError,
} from './tunnel';

const SESSION = { serverUrl: 'https://x', token: 't', username: 'u' };
const MAPPING: TunnelMapping = {
  id: 'm1',
  serverId: 's1',
  tunnelType: 'stcp',
  protocol: 'ssh',
  localPort: 22,
  visitorPort: 6000,
  customDomains: null,
  connectionId: null,
  enabled: true,
  name: 'db',
};

function refreshed(outcome: RefreshOutcome): TunnelRefresh {
  const running = outcome !== 'stopped';
  return { status: { running, visitors: running ? ['db-visitor'] : [] }, outcome };
}

function deferred<T>(): {
  promise: Promise<T>;
  resolve: (v: T) => void;
  reject: (e: Error) => void;
} {
  let resolve!: (v: T) => void;
  let reject!: (e: Error) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

beforeEach(() => {
  vi.useFakeTimers();
  vi.resetAllMocks();
  h.session.session = SESSION;
  h.refreshTunnel.mockResolvedValue(refreshed('started'));
  h.fetchTunnels.mockResolvedValue([MAPPING]);
  h.stopTunnel.mockResolvedValue(undefined);
});

afterEach(async () => {
  // The store is module state: end this test's polling while the fake clock owns it.
  await stop();
  vi.useRealTimers();
});

describe('tunnel store: activation', () => {
  it('a failed first reconciliation -> ui disconnected + error report', async () => {
    h.refreshTunnel.mockRejectedValueOnce(new Error('frpc missing'));
    await startIfServerMode();
    expect(get(tunnelUi)).toBe('disconnected');
    expect(h.reportError).toHaveBeenCalledTimes(1);
  });

  it('fetchTunnels failure leaves the tunnel running with mappings = []', async () => {
    h.fetchTunnels.mockRejectedValueOnce(new Error('404'));
    await startIfServerMode();
    expect(get(tunnelUi)).toBe('connected');
    expect(getMappings()).toEqual([]);
  });

  it('no tunnels (stopped) on login -> idle without a message', async () => {
    h.refreshTunnel.mockResolvedValueOnce(refreshed('stopped'));
    await startIfServerMode();
    expect(get(tunnelUi)).toBe('idle');
    expect(getMappings()).toEqual([]);
    expect(h.reportError).not.toHaveBeenCalled();
  });

  it('markTerminated (frpc-terminated event) sets ui disconnected', () => {
    markTerminated();
    expect(get(tunnelUi)).toBe('disconnected');
  });

  it('markError (frpc-error event) sets ui disconnected and reports the error', () => {
    markError('frpc crashed');
    expect(get(tunnelUi)).toBe('disconnected');
    expect(h.reportError).toHaveBeenCalled();
  });
});

describe('tunnel store: polling (R-0402)', () => {
  it('reconciles right away, then every 60 s, and reloads the mappings after each run', async () => {
    await startIfServerMode();
    expect(h.refreshTunnel).toHaveBeenCalledTimes(1);
    expect(h.refreshTunnel).toHaveBeenCalledWith('https://x', 't', 'u');
    expect(get(tunnelUi)).toBe('connected');
    expect(getMappings()).toEqual([MAPPING]);

    await vi.advanceTimersByTimeAsync(59_999);
    expect(h.refreshTunnel).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1);
    expect(h.refreshTunnel).toHaveBeenCalledTimes(2);
    expect(h.fetchTunnels).toHaveBeenCalledTimes(2);
  });

  it('a slow reconciliation makes the ticks skip instead of overlapping', async () => {
    const slow = deferred<TunnelRefresh>();
    h.refreshTunnel.mockReturnValueOnce(slow.promise);
    const activation = startIfServerMode();
    await vi.advanceTimersByTimeAsync(150_000);
    expect(h.refreshTunnel).toHaveBeenCalledTimes(1);

    slow.resolve(refreshed('started'));
    await activation;
    expect(get(tunnelUi)).toBe('connected');
    await vi.advanceTimersByTimeAsync(0); // a skipped tick queues no follow-up
    expect(h.refreshTunnel).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(30_000); // the tick at 180 s
    expect(h.refreshTunnel).toHaveBeenCalledTimes(2);
  });

  it('refreshNow during a reconciliation queues one follow-up after it', async () => {
    const first = deferred<TunnelRefresh>();
    const second = deferred<TunnelRefresh>();
    h.refreshTunnel.mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);
    const activation = startIfServerMode();
    let done = false;
    const now = refreshNow().then(() => (done = true));
    await vi.advanceTimersByTimeAsync(0);
    expect(h.refreshTunnel).toHaveBeenCalledTimes(1);

    first.resolve(refreshed('started'));
    await activation;
    await vi.advanceTimersByTimeAsync(0);
    expect(h.refreshTunnel).toHaveBeenCalledTimes(2);
    expect(done).toBe(false);

    second.resolve(refreshed('reloaded'));
    await now;
    expect(h.refreshTunnel).toHaveBeenCalledTimes(2);
    expect(h.fetchTunnels).toHaveBeenCalledTimes(2);
    expect(get(tunnelUi)).toBe('connected');

    await refreshNow(); // nothing in flight: a run of its own
    expect(h.refreshTunnel).toHaveBeenCalledTimes(3);
  });

  it('refreshNow twice during the same reconciliation queues a single follow-up', async () => {
    const slow = deferred<TunnelRefresh>();
    h.refreshTunnel.mockReturnValueOnce(slow.promise);
    const activation = startIfServerMode();
    const both = Promise.all([refreshNow(), refreshNow()]);

    slow.resolve(refreshed('started'));
    await Promise.all([activation, both]);
    await vi.advanceTimersByTimeAsync(0);
    expect(h.refreshTunnel).toHaveBeenCalledTimes(2);
  });

  it('stop() drops the follow-up refreshNow queued', async () => {
    const slow = deferred<TunnelRefresh>();
    h.refreshTunnel.mockReturnValueOnce(slow.promise);
    const activation = startIfServerMode();
    const now = refreshNow();
    await stop();

    slow.resolve(refreshed('started'));
    await Promise.all([activation, now]);
    await vi.advanceTimersByTimeAsync(0);
    expect(h.refreshTunnel).toHaveBeenCalledTimes(1);
    expect(get(tunnelUi)).toBe('idle');
  });

  it('a new activation drops the follow-up refreshNow queued', async () => {
    const slow = deferred<TunnelRefresh>();
    h.refreshTunnel.mockReturnValueOnce(slow.promise);
    const first = startIfServerMode();
    const now = refreshNow();
    await startIfServerMode();

    slow.resolve(refreshed('started'));
    await Promise.all([first, now]);
    await vi.advanceTimersByTimeAsync(0);
    expect(h.refreshTunnel).toHaveBeenCalledTimes(2);
  });

  it('refreshNow does nothing without an activation', async () => {
    await refreshNow();
    expect(h.refreshTunnel).not.toHaveBeenCalled();
  });

  it('stopped (the last tunnel is gone) -> idle, no mappings, no message', async () => {
    await startIfServerMode();
    h.refreshTunnel.mockResolvedValueOnce(refreshed('stopped'));
    await vi.advanceTimersByTimeAsync(60_000);
    expect(get(tunnelUi)).toBe('idle');
    expect(getMappings()).toEqual([]);
    expect(h.fetchTunnels).toHaveBeenCalledTimes(1);
    expect(h.reportError).not.toHaveBeenCalled();
  });

  it('an error leaves the tunnel as it is and is reported once per series', async () => {
    await startIfServerMode();
    h.refreshTunnel
      .mockRejectedValueOnce(new Error('502'))
      .mockRejectedValueOnce(new Error('timeout'));
    await vi.advanceTimersByTimeAsync(120_000);
    expect(h.refreshTunnel).toHaveBeenCalledTimes(3);
    expect(get(tunnelUi)).toBe('connected');
    expect(getMappings()).toEqual([MAPPING]);
    expect(h.stopTunnel).not.toHaveBeenCalled();
    expect(h.reportError).toHaveBeenCalledTimes(1);

    await vi.advanceTimersByTimeAsync(60_000); // a success ends the series
    h.refreshTunnel.mockRejectedValueOnce(new Error('502'));
    await vi.advanceTimersByTimeAsync(60_000);
    expect(h.reportError).toHaveBeenCalledTimes(2);
  });

  it('a new activation starts a new error series', async () => {
    h.refreshTunnel.mockRejectedValueOnce(new Error('502'));
    await startIfServerMode();
    h.refreshTunnel.mockRejectedValueOnce(new Error('502'));
    await startIfServerMode();
    expect(h.reportError).toHaveBeenCalledTimes(2);
  });

  it('a failed mappings reload keeps the previous mappings', async () => {
    await startIfServerMode();
    h.fetchTunnels.mockRejectedValueOnce(new Error('502'));
    await vi.advanceTimersByTimeAsync(60_000);
    expect(h.fetchTunnels).toHaveBeenCalledTimes(2);
    expect(getMappings()).toEqual([MAPPING]);
    expect(get(tunnelUi)).toBe('connected');
  });

  it('stop() ends the polling', async () => {
    await startIfServerMode();
    await stop();
    expect(get(tunnelUi)).toBe('idle');
    await vi.advanceTimersByTimeAsync(180_000);
    expect(h.refreshTunnel).toHaveBeenCalledTimes(1);
  });

  it('a logout that bypasses stop() ends the polling at the next tick', async () => {
    await startIfServerMode();
    h.session.session = null;
    await vi.advanceTimersByTimeAsync(60_000);
    h.session.session = SESSION;
    await vi.advanceTimersByTimeAsync(120_000);
    expect(h.refreshTunnel).toHaveBeenCalledTimes(1);
  });

  it('an activation overtaken by stop() drops its result and stops the frpc it started', async () => {
    const slow = deferred<TunnelRefresh>();
    h.refreshTunnel.mockReturnValueOnce(slow.promise);
    const activation = startIfServerMode();
    await stop();
    expect(h.stopTunnel).toHaveBeenCalledTimes(1);

    slow.resolve(refreshed('started'));
    await activation;
    expect(get(tunnelUi)).toBe('idle');
    expect(h.fetchTunnels).not.toHaveBeenCalled();
    expect(h.stopTunnel).toHaveBeenCalledTimes(2);
    await vi.advanceTimersByTimeAsync(120_000);
    expect(h.refreshTunnel).toHaveBeenCalledTimes(1);
  });

  it('a failure of an overtaken reconciliation reports nothing', async () => {
    const slow = deferred<TunnelRefresh>();
    h.refreshTunnel.mockReturnValueOnce(slow.promise);
    const activation = startIfServerMode();
    await stop();

    slow.reject(new Error('502'));
    await activation;
    expect(get(tunnelUi)).toBe('idle');
    expect(h.reportError).not.toHaveBeenCalled();
  });

  it('stop() during the mappings reload leaves idle', async () => {
    await startIfServerMode();
    const reload = deferred<TunnelMapping[]>();
    h.fetchTunnels.mockReturnValueOnce(reload.promise);
    await vi.advanceTimersByTimeAsync(60_000);
    await stop();

    reload.resolve([MAPPING]);
    await vi.advanceTimersByTimeAsync(0);
    expect(get(tunnelUi)).toBe('idle');
    expect(getMappings()).toEqual([]);
  });

  // 'started': the overtaken run left frpc running; it belongs to the newer activation now.
  it.each(['stopped', 'started'] as const)(
    'an activation overtaken by a newer one leaves the tunnel to it (%s)',
    async (outcome) => {
      const slow = deferred<TunnelRefresh>();
      h.refreshTunnel.mockReturnValueOnce(slow.promise);
      const first = startIfServerMode();
      await startIfServerMode();
      expect(get(tunnelUi)).toBe('connected');

      slow.resolve(refreshed(outcome));
      await first;
      expect(get(tunnelUi)).toBe('connected');
      expect(getMappings()).toEqual([MAPPING]);
      expect(h.fetchTunnels).toHaveBeenCalledTimes(1);
      expect(h.stopTunnel).not.toHaveBeenCalled();
      await vi.advanceTimersByTimeAsync(60_000); // one polling left, not two
      expect(h.refreshTunnel).toHaveBeenCalledTimes(3);
    },
  );
});
