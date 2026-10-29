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
    session: null as { serverUrl: string; username: string } | null,
    settings: { mode: 'server' },
  },
}));

vi.mock('$lib/bridge', () => ({
  refreshTunnel: h.refreshTunnel,
  fetchTunnels: h.fetchTunnels,
  stopTunnel: h.stopTunnel,
}));
vi.mock('./statusBar', () => ({ reportError: h.reportError }));
vi.mock('$lib/i18n', () => ({
  tNow: (k: string, vars?: Record<string, unknown>) => (vars ? `${k} ${JSON.stringify(vars)}` : k),
}));
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
  reconnectNow,
  stop,
  tunnelUi,
  tunnelStatus,
  getMappings,
  markTerminated,
  markError,
} from './tunnel';

const SESSION = { serverUrl: 'https://x', username: 'u' };
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
// An HTTPS tunnel needs no frpc: the visitor bundle leaves it out, the mappings carry it.
const HTTPS: TunnelMapping = {
  ...MAPPING,
  id: 'm2',
  tunnelType: 'https',
  protocol: 'web',
  localPort: 443,
  visitorPort: null,
  customDomains: 'web.example.com',
  connectionId: 'c1',
  name: 'web',
};

function refreshed(outcome: RefreshOutcome): TunnelRefresh {
  const running = outcome !== 'stopped';
  return { status: { running, visitors: running ? ['db-visitor'] : [] }, outcome, refused: null };
}

function refusedBy(code: number): TunnelRefresh {
  return { ...refreshed('stopped'), refused: code };
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

  it('no STCP tunnels (stopped) on login -> idle without a message, the mappings loaded', async () => {
    h.refreshTunnel.mockResolvedValueOnce(refreshed('stopped'));
    h.fetchTunnels.mockResolvedValueOnce([HTTPS]);
    await startIfServerMode();
    expect(get(tunnelUi)).toBe('idle');
    expect(getMappings()).toEqual([HTTPS]);
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
    expect(h.refreshTunnel).toHaveBeenCalledWith();
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

  // The follow-up is a reconciliation like any other: one at a time holds for it too.
  it('a tick during the follow-up skips instead of overlapping', async () => {
    const first = deferred<TunnelRefresh>();
    const second = deferred<TunnelRefresh>();
    h.refreshTunnel.mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);
    const activation = startIfServerMode();
    const now = refreshNow();
    first.resolve(refreshed('started'));
    await activation;
    await vi.advanceTimersByTimeAsync(0);
    expect(h.refreshTunnel).toHaveBeenCalledTimes(2);

    await vi.advanceTimersByTimeAsync(60_000); // the tick while the follow-up runs
    expect(h.refreshTunnel).toHaveBeenCalledTimes(2);
    second.resolve(refreshed('reloaded'));
    await now;
  });

  it('refreshNow during the follow-up queues one more after it', async () => {
    const first = deferred<TunnelRefresh>();
    const second = deferred<TunnelRefresh>();
    h.refreshTunnel.mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);
    const activation = startIfServerMode();
    const now = refreshNow();
    first.resolve(refreshed('started'));
    await activation;
    await vi.advanceTimersByTimeAsync(0);

    const again = refreshNow();
    await vi.advanceTimersByTimeAsync(0);
    expect(h.refreshTunnel).toHaveBeenCalledTimes(2);
    second.resolve(refreshed('reloaded'));
    await Promise.all([now, again]);
    expect(h.refreshTunnel).toHaveBeenCalledTimes(3);
  });

  it('an overtaken run that ends during the newer one does not let the next tick overlap', async () => {
    const old = deferred<TunnelRefresh>();
    const newer = deferred<TunnelRefresh>();
    h.refreshTunnel.mockReturnValueOnce(old.promise).mockReturnValueOnce(newer.promise);
    const first = startIfServerMode();
    const second = startIfServerMode();
    old.resolve(refreshed('started'));
    await first;

    await vi.advanceTimersByTimeAsync(60_000); // the tick while the newer run is in flight
    expect(h.refreshTunnel).toHaveBeenCalledTimes(2);
    newer.resolve(refreshed('started'));
    await second;
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

  it('stopped (the last STCP tunnel is gone) -> idle without a message, the mappings reloaded', async () => {
    await startIfServerMode();
    h.refreshTunnel.mockResolvedValueOnce(refreshed('stopped'));
    h.fetchTunnels.mockResolvedValueOnce([HTTPS]);
    await vi.advanceTimersByTimeAsync(60_000);
    expect(get(tunnelUi)).toBe('idle');
    expect(getMappings()).toEqual([HTTPS]);
    expect(h.fetchTunnels).toHaveBeenCalledTimes(2);
    expect(h.reportError).not.toHaveBeenCalled();
  });

  it('stopped and a failed mappings reload keep the previous mappings, without a message', async () => {
    await startIfServerMode();
    h.refreshTunnel.mockResolvedValueOnce(refreshed('stopped'));
    h.fetchTunnels.mockRejectedValueOnce(new Error('502'));
    await vi.advanceTimersByTimeAsync(60_000);
    expect(h.fetchTunnels).toHaveBeenCalledTimes(2);
    expect(get(tunnelUi)).toBe('idle');
    expect(getMappings()).toEqual([MAPPING]);
    expect(h.reportError).not.toHaveBeenCalled();
  });

  it('stopped because the server refused the tunnels -> idle, one message with the code while it lasts', async () => {
    h.refreshTunnel.mockResolvedValue(refusedBy(403));
    await startIfServerMode();
    expect(get(tunnelUi)).toBe('idle');
    expect(h.reportError).toHaveBeenCalledTimes(1);
    expect(h.reportError).toHaveBeenCalledWith('error.tunnel.refused {"code":403}');
    await vi.advanceTimersByTimeAsync(60_000);
    expect(h.refreshTunnel).toHaveBeenCalledTimes(2);
    expect(h.reportError).toHaveBeenCalledTimes(1);
  });

  it('a refusal after a run without one is a new message', async () => {
    h.refreshTunnel.mockResolvedValueOnce(refusedBy(403));
    await startIfServerMode();
    h.refreshTunnel.mockResolvedValueOnce(refreshed('started'));
    await vi.advanceTimersByTimeAsync(60_000);
    h.refreshTunnel.mockResolvedValueOnce(refusedBy(403));
    await vi.advanceTimersByTimeAsync(60_000);
    expect(h.reportError).toHaveBeenCalledTimes(2);
  });

  it('a new activation reports a lasting refusal again', async () => {
    h.refreshTunnel.mockResolvedValue(refusedBy(403));
    await startIfServerMode();
    await startIfServerMode();
    expect(h.reportError).toHaveBeenCalledTimes(2);
  });

  it('stop() still clears the mappings a stopped run loaded', async () => {
    h.refreshTunnel.mockResolvedValueOnce(refreshed('stopped'));
    h.fetchTunnels.mockResolvedValueOnce([HTTPS]);
    await startIfServerMode();
    expect(getMappings()).toEqual([HTTPS]);
    await stop();
    expect(get(tunnelUi)).toBe('idle');
    expect(getMappings()).toEqual([]);
  });

  it('stop() during the mappings reload of a stopped run leaves no mappings', async () => {
    await startIfServerMode();
    h.refreshTunnel.mockResolvedValueOnce(refreshed('stopped'));
    const reload = deferred<TunnelMapping[]>();
    h.fetchTunnels.mockReturnValueOnce(reload.promise);
    await vi.advanceTimersByTimeAsync(60_000);
    await stop();

    reload.resolve([HTTPS]);
    await vi.advanceTimersByTimeAsync(0);
    expect(get(tunnelUi)).toBe('idle');
    expect(getMappings()).toEqual([]);
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

describe('tunnel store: restart after an unexpected end (R-0402)', () => {
  // The backend as the store sees it: a reconciliation starts frpc unless it runs. `end()` is
  // frpc ending on its own, `fail()` the same with frpc-error; `starts` holds when it started,
  // in ms since the test began.
  function frpcBackend(outcome: 'started' | 'restarted' = 'started') {
    const t0 = Date.now();
    const starts: number[] = [];
    let running = false;
    h.refreshTunnel.mockImplementation(async () => {
      if (running) return refreshed('unchanged');
      running = true;
      starts.push(Date.now() - t0);
      return refreshed(outcome);
    });
    return {
      starts,
      end: () => {
        running = false;
        markTerminated();
      },
      fail: () => {
        running = false;
        markError('frpc crashed');
      },
    };
  }

  it('restarts a frpc that ended after 5, 10, 20, then 40 s while each restart fails', async () => {
    await startIfServerMode();
    h.refreshTunnel.mockRejectedValue(new Error('502'));
    markTerminated();
    await vi.advanceTimersByTimeAsync(4_999);
    expect(h.refreshTunnel).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1); // 5 s
    expect(h.refreshTunnel).toHaveBeenCalledTimes(2);
    await vi.advanceTimersByTimeAsync(9_999);
    expect(h.refreshTunnel).toHaveBeenCalledTimes(2);
    await vi.advanceTimersByTimeAsync(1); // 15 s
    expect(h.refreshTunnel).toHaveBeenCalledTimes(3);

    // This restart outlasts the tick at 60 s, which skips; otherwise the tick would pull the
    // 40 s restart forward.
    const slow = deferred<TunnelRefresh>();
    h.refreshTunnel.mockReturnValueOnce(slow.promise);
    await vi.advanceTimersByTimeAsync(20_000); // 35 s
    expect(h.refreshTunnel).toHaveBeenCalledTimes(4);
    await vi.advanceTimersByTimeAsync(26_000); // 61 s
    slow.reject(new Error('502'));
    await vi.advanceTimersByTimeAsync(39_999);
    expect(h.refreshTunnel).toHaveBeenCalledTimes(4);
    await vi.advanceTimersByTimeAsync(1); // 101 s
    expect(h.refreshTunnel).toHaveBeenCalledTimes(5);
    expect(get(tunnelUi)).toBe('disconnected');
    expect(h.stopTunnel).not.toHaveBeenCalled();
  });

  it('a frpc that ends 1 s after each restart is restarted after 5, 10, 20, 40, 60, 60 s', async () => {
    const timeouts = vi.spyOn(globalThis, 'setTimeout');
    try {
      const frpc = frpcBackend();
      await startIfServerMode();
      for (let restart = 1; restart <= 6; restart++) {
        await vi.advanceTimersByTimeAsync(1_000);
        frpc.end();
        for (let n = 0; frpc.starts.length <= restart && n < 5; n++) {
          await vi.advanceTimersToNextTimerAsync();
        }
      }
      expect(timeouts.mock.calls.map(([, ms]) => ms)).toEqual([
        5_000, 10_000, 20_000, 40_000, 60_000, 60_000,
      ]);
      // From the 40 s pause on, the tick at 60, 120, 180 s comes first and is the restart.
      expect(frpc.starts).toEqual([0, 6_000, 17_000, 38_000, 60_000, 120_000, 180_000]);
    } finally {
      timeouts.mockRestore();
    }
  });

  it.each([
    ['started', 61_000, 5_000],
    ['restarted', 61_000, 5_000],
    ['started', 60_000, 5_000],
    ['started', 59_999, 20_000],
  ] as const)(
    'frpc back by %s that ends %i ms later: the next pause is %i ms',
    async (outcome, ran, pause) => {
      const frpc = frpcBackend(outcome);
      await startIfServerMode();
      await vi.advanceTimersByTimeAsync(1_000);
      frpc.end(); // 1 s
      await vi.advanceTimersByTimeAsync(6_000);
      frpc.end(); // 7 s, 1 s after the restart at 6 s
      await vi.advanceTimersByTimeAsync(10_000);
      expect(frpc.starts).toEqual([0, 6_000, 17_000]);

      await vi.advanceTimersByTimeAsync(ran); // the tick at 60 s finds it running
      frpc.end();
      await vi.advanceTimersByTimeAsync(pause - 1);
      expect(frpc.starts).toHaveLength(3);
      await vi.advanceTimersByTimeAsync(1);
      expect(frpc.starts).toEqual([0, 6_000, 17_000, 17_000 + ran + pause]);
    },
  );

  it('a restarted frpc that ran a whole tick ends the restarts: a failed tick is a new series without a restart', async () => {
    const frpc = frpcBackend();
    await startIfServerMode();
    await vi.advanceTimersByTimeAsync(1_000);
    frpc.fail();
    await vi.advanceTimersByTimeAsync(5_000); // back at 6 s
    expect(frpc.starts).toEqual([0, 6_000]);
    expect(h.reportError).toHaveBeenCalledTimes(1);

    await vi.advanceTimersByTimeAsync(113_000); // the tick at 60 s finds it running
    h.refreshTunnel.mockRejectedValueOnce(new Error('502'));
    await vi.advanceTimersByTimeAsync(1_000); // the tick at 120 s fails
    expect(h.refreshTunnel).toHaveBeenCalledTimes(4);
    expect(h.reportError).toHaveBeenCalledTimes(2);
    await vi.advanceTimersByTimeAsync(59_999);
    expect(h.refreshTunnel).toHaveBeenCalledTimes(4);
  });

  it('a frpc that keeps ending with frpc-error is one message until it holds for a tick', async () => {
    const frpc = frpcBackend();
    await startIfServerMode();
    await vi.advanceTimersByTimeAsync(1_000);
    frpc.fail(); // 1 s
    await vi.advanceTimersByTimeAsync(6_000);
    frpc.fail(); // 7 s, 1 s after the restart at 6 s
    await vi.advanceTimersByTimeAsync(11_000);
    frpc.fail(); // 18 s, 1 s after the restart at 17 s
    await vi.advanceTimersByTimeAsync(20_000);
    expect(frpc.starts).toEqual([0, 6_000, 17_000, 38_000]);
    expect(h.reportError).toHaveBeenCalledTimes(1);

    await vi.advanceTimersByTimeAsync(61_000); // it holds: the tick at 60 s finds it running
    frpc.fail(); // 99 s: a new series
    expect(h.reportError).toHaveBeenCalledTimes(2);
    await vi.advanceTimersByTimeAsync(6_000);
    frpc.fail(); // 105 s, 1 s after the restart at 104 s
    expect(frpc.starts).toEqual([0, 6_000, 17_000, 38_000, 104_000]);
    expect(h.reportError).toHaveBeenCalledTimes(2);
  });

  it('failures that begin within a tick of a start stay one message', async () => {
    await startIfServerMode(); // starts frpc at 0 s
    h.refreshTunnel.mockRejectedValue(new Error('502'));
    await vi.advanceTimersByTimeAsync(10_000);
    await refreshNow(); // fails at 10 s
    await vi.advanceTimersByTimeAsync(50_000); // the tick at 60 s fails as well
    expect(h.refreshTunnel).toHaveBeenCalledTimes(3);
    expect(h.reportError).toHaveBeenCalledTimes(1);
  });

  // A frpc-error need not end frpc: the restart then finds it running.
  it('a frpc that survives its frpc-error ends the series once it held: a failed tick is a new series', async () => {
    await startIfServerMode();
    h.refreshTunnel.mockResolvedValue(refreshed('unchanged'));
    markError('pipe read error');
    await vi.advanceTimersByTimeAsync(5_000); // the restart finds frpc running
    expect(h.refreshTunnel).toHaveBeenCalledTimes(2);
    expect(get(tunnelUi)).toBe('connected');

    await vi.advanceTimersByTimeAsync(114_000); // the tick at 60 s finds it running
    h.refreshTunnel.mockRejectedValueOnce(new Error('502'));
    await vi.advanceTimersByTimeAsync(1_000); // the tick at 120 s fails
    expect(h.reportError).toHaveBeenCalledTimes(2);
    await vi.advanceTimersByTimeAsync(59_999); // and plans no restart
    expect(h.refreshTunnel).toHaveBeenCalledTimes(4);
  });

  it('a frpc that survives its frpc-error and ends after a tick is restarted after 5 s', async () => {
    await startIfServerMode();
    h.refreshTunnel.mockResolvedValue(refreshed('unchanged'));
    markError('pipe read error');
    await vi.advanceTimersByTimeAsync(66_000); // found running at 5 s, held past 65 s
    markTerminated();
    await vi.advanceTimersByTimeAsync(4_999);
    expect(h.refreshTunnel).toHaveBeenCalledTimes(3);
    await vi.advanceTimersByTimeAsync(1); // 71 s
    expect(h.refreshTunnel).toHaveBeenCalledTimes(4);
  });

  it('a restart that finds no tunnels ends the restarts', async () => {
    await startIfServerMode();
    h.refreshTunnel.mockResolvedValueOnce(refreshed('stopped'));
    markTerminated();
    await vi.advanceTimersByTimeAsync(5_000);
    expect(get(tunnelUi)).toBe('idle');

    h.refreshTunnel.mockRejectedValue(new Error('502'));
    await vi.advanceTimersByTimeAsync(55_000); // the tick at 60 s fails
    expect(h.refreshTunnel).toHaveBeenCalledTimes(3);
    await vi.advanceTimersByTimeAsync(59_999); // no restart until the next tick
    expect(h.refreshTunnel).toHaveBeenCalledTimes(3);
  });

  it('a tick during the pause is the restart; the planned one does not follow', async () => {
    await startIfServerMode();
    await vi.advanceTimersByTimeAsync(58_000);
    markTerminated(); // the restart is due at 63 s
    await vi.advanceTimersByTimeAsync(2_000); // the tick at 60 s
    expect(h.refreshTunnel).toHaveBeenCalledTimes(2);
    expect(get(tunnelUi)).toBe('connected');
    await vi.advanceTimersByTimeAsync(59_999);
    expect(h.refreshTunnel).toHaveBeenCalledTimes(2);
  });

  it('refreshNow during the pause is the restart; the planned one does not follow', async () => {
    await startIfServerMode();
    markTerminated();
    await vi.advanceTimersByTimeAsync(2_000);
    await refreshNow();
    expect(h.refreshTunnel).toHaveBeenCalledTimes(2);
    await vi.advanceTimersByTimeAsync(57_999);
    expect(h.refreshTunnel).toHaveBeenCalledTimes(2);
  });

  it('a run that started before frpc ended is no restart: the restart follows it', async () => {
    await startIfServerMode();
    const slow = deferred<TunnelRefresh>();
    h.refreshTunnel.mockReturnValueOnce(slow.promise);
    await vi.advanceTimersByTimeAsync(60_000); // the tick at 60 s hangs
    markTerminated(); // the restart is due at 65 s
    await vi.advanceTimersByTimeAsync(10_000);
    expect(h.refreshTunnel).toHaveBeenCalledTimes(2); // not beside the running one

    // It compared against the frpc that ended since: the series goes on.
    h.refreshTunnel.mockRejectedValueOnce(new Error('502'));
    slow.resolve({ status: { running: false, visitors: [] }, outcome: 'unchanged', refused: null });
    await vi.advanceTimersByTimeAsync(0);
    expect(h.refreshTunnel).toHaveBeenCalledTimes(3); // the restart, right after it
    await vi.advanceTimersByTimeAsync(9_999);
    expect(h.refreshTunnel).toHaveBeenCalledTimes(3);
    await vi.advanceTimersByTimeAsync(1); // 10 s after the failed restart
    expect(h.refreshTunnel).toHaveBeenCalledTimes(4);
  });

  it.each([
    ['unchanged', 'before the restart is due', 0],
    ['unchanged', 'with the restart queued behind it', 6_000],
    ['started', 'before the restart is due', 0],
    ['started', 'with the restart queued behind it', 6_000],
  ] as const)(
    'a run that saw frpc (%s) before it ended starts no hold time and shows no connection (it returns %s)',
    async (outcome, _, after) => {
      await startIfServerMode();
      const slow = deferred<TunnelRefresh>();
      h.refreshTunnel.mockReturnValueOnce(slow.promise);
      await vi.advanceTimersByTimeAsync(60_000); // the tick at 60 s hangs
      markTerminated(); // the restart is due at 65 s
      await vi.advanceTimersByTimeAsync(after);
      h.refreshTunnel.mockRejectedValue(new Error('502'));
      slow.resolve(refreshed(outcome)); // it still saw frpc running
      await vi.advanceTimersByTimeAsync(120_000 - after); // two minutes of failed runs: one series
      expect(h.reportError).toHaveBeenCalledTimes(1);
      expect(get(tunnelUi)).toBe('disconnected');
    },
  );

  it('a run that saw frpc before it ended leaves "disconnected" until the restart brings it back', async () => {
    await startIfServerMode();
    const slow = deferred<TunnelRefresh>();
    h.refreshTunnel.mockReturnValueOnce(slow.promise);
    await vi.advanceTimersByTimeAsync(60_000); // the tick at 60 s hangs
    markTerminated(); // the restart is due at 65 s
    const saved = [MAPPING, { ...MAPPING, id: 'm2', name: 'web' }];
    h.fetchTunnels.mockResolvedValueOnce(saved);
    slow.resolve(refreshed('unchanged')); // it still saw frpc running
    await vi.advanceTimersByTimeAsync(0);
    expect(get(tunnelUi)).toBe('disconnected');
    expect(getMappings()).toEqual(saved); // the mappings it fetched are current all the same
    await vi.advanceTimersByTimeAsync(5_000); // the restart starts frpc
    expect(h.refreshTunnel).toHaveBeenCalledTimes(3);
    expect(get(tunnelUi)).toBe('connected');
  });

  it('a run with a follow-up queued behind it leaves a connected display as it is', async () => {
    await startIfServerMode();
    const slow = deferred<TunnelRefresh>();
    const follow = deferred<TunnelRefresh>();
    h.refreshTunnel.mockReturnValueOnce(slow.promise).mockReturnValueOnce(follow.promise);
    await vi.advanceTimersByTimeAsync(60_000); // the tick at 60 s hangs
    const now = refreshNow(); // say a tunnel was saved
    slow.resolve(refreshed('reloaded'));
    await vi.advanceTimersByTimeAsync(0);
    expect(h.refreshTunnel).toHaveBeenCalledTimes(3); // the follow-up runs
    expect(get(tunnelUi)).toBe('connected');
    follow.resolve(refreshed('reloaded'));
    await now;
    expect(get(tunnelUi)).toBe('connected');
  });

  // Only the restart queued behind a run says frpc ended while it ran; a refreshNow does not.
  it('a refreshNow queued behind the first run lets it show the frpc it started, should the follow-up fail', async () => {
    const first = deferred<TunnelRefresh>();
    const follow = deferred<TunnelRefresh>();
    h.refreshTunnel.mockReturnValueOnce(first.promise).mockReturnValueOnce(follow.promise);
    const activation = startIfServerMode();
    const now = refreshNow(); // a tunnel saved while the first run starts frpc
    first.resolve(refreshed('started'));
    await activation;
    expect(get(tunnelUi)).toBe('connected');

    follow.reject(new Error('502'));
    await now;
    expect(get(tunnelUi)).toBe('connected');
    expect(get(tunnelStatus)?.running).toBe(true);
    expect(h.reportError).toHaveBeenCalledTimes(1);
  });

  it('a refreshNow queued behind a failing restart is the next restart: the pauses go on', async () => {
    await startIfServerMode();
    h.refreshTunnel.mockRejectedValue(new Error('502'));
    const slow = deferred<TunnelRefresh>();
    h.refreshTunnel.mockReturnValueOnce(slow.promise);
    markTerminated(); // the restart is due at 5 s
    await vi.advanceTimersByTimeAsync(6_000); // it hangs
    const now = refreshNow(); // say a tunnel was saved
    slow.reject(new Error('502'));
    await now; // the follow-up fails at 6 s
    expect(h.refreshTunnel).toHaveBeenCalledTimes(3);
    await vi.advanceTimersByTimeAsync(9_999);
    expect(h.refreshTunnel).toHaveBeenCalledTimes(3);
    await vi.advanceTimersByTimeAsync(1); // 10 s, as after the failed restart at 5 s alone
    expect(h.refreshTunnel).toHaveBeenCalledTimes(4);
  });

  it('a frpc restarted in the middle of a series starts its hold time anew', async () => {
    const frpc = frpcBackend();
    await startIfServerMode();
    await vi.advanceTimersByTimeAsync(1_000);
    frpc.end(); // 1 s
    await vi.advanceTimersByTimeAsync(5_000); // back at 6 s
    h.refreshTunnel.mockResolvedValueOnce(refreshed('restarted'));
    await vi.advanceTimersByTimeAsync(61_000); // the tick at 60 s restarts it, say for a new token
    frpc.end(); // 67 s: 61 s after the start at 6 s, 7 s after the restart at 60 s
    await vi.advanceTimersByTimeAsync(9_999);
    expect(frpc.starts).toEqual([0, 6_000]);
    await vi.advanceTimersByTimeAsync(1); // the series goes on: 10 s
    expect(frpc.starts).toEqual([0, 6_000, 77_000]);
  });

  it('a restart queued behind a run that fails keeps the pause sequence', async () => {
    await startIfServerMode();
    const t0 = Date.now();
    const slow = deferred<TunnelRefresh>();
    h.refreshTunnel.mockReturnValueOnce(slow.promise);
    await vi.advanceTimersByTimeAsync(60_000); // the tick at 60 s hangs
    markTerminated(); // the restart, due at 65 s, queues behind it
    await vi.advanceTimersByTimeAsync(6_000);
    const restarts: number[] = [];
    h.refreshTunnel.mockImplementation(async () => {
      restarts.push(Date.now() - t0);
      throw new Error('502');
    });
    slow.reject(new Error('502')); // 66 s
    await vi.advanceTimersByTimeAsync(40_000);
    expect(restarts).toEqual([66_000, 76_000, 96_000]);
  });

  it('frpc-error and frpc-terminated of one end plan a single restart', async () => {
    await startIfServerMode();
    markError('frpc crashed');
    markTerminated();
    await vi.advanceTimersByTimeAsync(5_000);
    expect(h.refreshTunnel).toHaveBeenCalledTimes(2);
    await vi.advanceTimersByTimeAsync(54_999);
    expect(h.refreshTunnel).toHaveBeenCalledTimes(2);
  });

  it('a frpc-error and the failed restarts after it are one message', async () => {
    await startIfServerMode();
    h.refreshTunnel.mockRejectedValueOnce(new Error('502')).mockRejectedValueOnce(new Error('502'));
    markError('frpc crashed');
    expect(h.reportError).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(15_000); // the restarts at 5 s and 15 s fail
    expect(h.refreshTunnel).toHaveBeenCalledTimes(3);
    markError('frpc crashed');
    expect(h.reportError).toHaveBeenCalledTimes(1);

    await vi.advanceTimersByTimeAsync(20_000); // the restart at 35 s brings frpc back
    expect(h.refreshTunnel).toHaveBeenCalledTimes(4);
    expect(get(tunnelUi)).toBe('connected');
    markError('frpc crashed'); // it did not hold: still the same series
    expect(h.reportError).toHaveBeenCalledTimes(1);
  });

  it('after stop() an ended frpc is not restarted', async () => {
    await startIfServerMode();
    markTerminated(); // the restart is due at 5 s
    await stop();
    markTerminated(); // a late event plans none either
    await vi.advanceTimersByTimeAsync(120_000);
    expect(h.refreshTunnel).toHaveBeenCalledTimes(1);
  });

  it('a new activation ends the restarts of the previous one', async () => {
    await startIfServerMode();
    h.refreshTunnel.mockRejectedValue(new Error('502'));
    markTerminated();
    await vi.advanceTimersByTimeAsync(5_000); // the restart fails, the next one is due at 15 s
    await startIfServerMode(); // fails as well, but is no restart
    expect(h.refreshTunnel).toHaveBeenCalledTimes(3);
    await vi.advanceTimersByTimeAsync(59_999);
    expect(h.refreshTunnel).toHaveBeenCalledTimes(3);
    await vi.advanceTimersByTimeAsync(1); // its first tick
    expect(h.refreshTunnel).toHaveBeenCalledTimes(4);
  });
});

describe('tunnel store: reconnectNow (R-0402)', () => {
  it('after an end of frpc it reconciles at once; the planned restart does not follow', async () => {
    await startIfServerMode();
    h.refreshTunnel.mockRejectedValueOnce(new Error('502')).mockRejectedValueOnce(new Error('502'));
    markTerminated();
    await vi.advanceTimersByTimeAsync(20_000); // the restarts at 5 s and 15 s fail; next at 35 s
    expect(h.refreshTunnel).toHaveBeenCalledTimes(3);

    await reconnectNow();
    expect(h.refreshTunnel).toHaveBeenCalledTimes(4);
    expect(get(tunnelUi)).toBe('connected');
    await vi.advanceTimersByTimeAsync(39_999); // past 35 s, up to the tick at 60 s
    expect(h.refreshTunnel).toHaveBeenCalledTimes(4);
  });

  it('a failed reconnect pauses 5 s again, without a second message', async () => {
    await startIfServerMode();
    h.refreshTunnel.mockRejectedValue(new Error('502'));
    markTerminated();
    await vi.advanceTimersByTimeAsync(18_000); // the restarts at 5 s and 15 s fail; next at 35 s
    expect(h.refreshTunnel).toHaveBeenCalledTimes(3);
    expect(h.reportError).toHaveBeenCalledTimes(1);

    await reconnectNow(); // fails at 18 s
    expect(h.refreshTunnel).toHaveBeenCalledTimes(4);
    await vi.advanceTimersByTimeAsync(4_999);
    expect(h.refreshTunnel).toHaveBeenCalledTimes(4);
    await vi.advanceTimersByTimeAsync(1); // 23 s
    expect(h.refreshTunnel).toHaveBeenCalledTimes(5);
    await vi.advanceTimersByTimeAsync(10_000); // 33 s
    expect(h.refreshTunnel).toHaveBeenCalledTimes(6);
    await vi.advanceTimersByTimeAsync(19_999); // nothing at 35 s; the next is due at 53 s
    expect(h.refreshTunnel).toHaveBeenCalledTimes(6);
    expect(h.reportError).toHaveBeenCalledTimes(1);
    expect(get(tunnelUi)).toBe('disconnected');
  });

  it('while a run that saw frpc before it ended is in flight, the reconnect is the restart behind it', async () => {
    await startIfServerMode();
    const slow = deferred<TunnelRefresh>();
    const restart = deferred<TunnelRefresh>();
    h.refreshTunnel.mockReturnValueOnce(slow.promise).mockReturnValueOnce(restart.promise);
    await vi.advanceTimersByTimeAsync(60_000); // the tick at 60 s hangs
    markTerminated(); // the restart is due at 65 s
    await vi.advanceTimersByTimeAsync(1_000);
    const now = reconnectNow();
    await vi.advanceTimersByTimeAsync(0);
    expect(h.refreshTunnel).toHaveBeenCalledTimes(2); // not beside the running one

    slow.resolve(refreshed('unchanged')); // it still saw frpc running
    await vi.advanceTimersByTimeAsync(0);
    expect(h.refreshTunnel).toHaveBeenCalledTimes(3); // the restart, right after it
    expect(get(tunnelUi)).toBe('disconnected');
    restart.resolve(refreshed('started'));
    await now;
    expect(get(tunnelUi)).toBe('connected');
    await vi.advanceTimersByTimeAsync(58_000); // past 65 s, up to 119 s
    expect(h.refreshTunnel).toHaveBeenCalledTimes(3);
  });

  it('while a restart is in flight it queues one more: should both fail, the next restart is 5 s away', async () => {
    await startIfServerMode();
    h.refreshTunnel.mockRejectedValue(new Error('502'));
    markTerminated();
    await vi.advanceTimersByTimeAsync(15_000); // the restarts at 5 s and 15 s fail; next at 35 s
    const slow = deferred<TunnelRefresh>();
    h.refreshTunnel.mockReturnValueOnce(slow.promise);
    await vi.advanceTimersByTimeAsync(20_000); // the restart at 35 s hangs
    expect(h.refreshTunnel).toHaveBeenCalledTimes(4);

    const now = reconnectNow();
    await vi.advanceTimersByTimeAsync(0);
    expect(h.refreshTunnel).toHaveBeenCalledTimes(4); // not beside the running one
    slow.reject(new Error('502'));
    await now;
    expect(h.refreshTunnel).toHaveBeenCalledTimes(5);
    await vi.advanceTimersByTimeAsync(4_999);
    expect(h.refreshTunnel).toHaveBeenCalledTimes(5);
    await vi.advanceTimersByTimeAsync(1); // 40 s
    expect(h.refreshTunnel).toHaveBeenCalledTimes(6);
    expect(h.reportError).toHaveBeenCalledTimes(1);
  });

  // No frpc ended: a failed reconnect is a failed reconciliation like a tick's.
  it('outside a restart series it reconciles once; a failure waits for the tick, without a second message', async () => {
    h.refreshTunnel.mockRejectedValue(new Error('502'));
    await startIfServerMode(); // the first start fails
    expect(get(tunnelUi)).toBe('disconnected');
    await vi.advanceTimersByTimeAsync(10_000);

    await reconnectNow();
    expect(h.refreshTunnel).toHaveBeenCalledTimes(2);
    await vi.advanceTimersByTimeAsync(49_999);
    expect(h.refreshTunnel).toHaveBeenCalledTimes(2);
    await vi.advanceTimersByTimeAsync(1); // the tick at 60 s
    expect(h.refreshTunnel).toHaveBeenCalledTimes(3);
    expect(h.reportError).toHaveBeenCalledTimes(1);
  });

  it('does nothing after stop()', async () => {
    await startIfServerMode();
    markTerminated();
    await stop();
    await reconnectNow();
    await vi.advanceTimersByTimeAsync(120_000);
    expect(h.refreshTunnel).toHaveBeenCalledTimes(1);
  });
});
