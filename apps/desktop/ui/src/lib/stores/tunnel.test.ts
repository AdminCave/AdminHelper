// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Tunnel store state machine (6.45): startIfServerMode has three outcomes — connected, disconnected
// with a status reset, and a swallowed fetchTunnels error that keeps the tunnel running with an empty
// mappings fallback. If the fallback breaks, the connect flow no longer resolves connections through
// the tunnel — a failure only the manual tunnel live-E2E would otherwise catch.

import { describe, it, expect, beforeEach, vi } from 'vitest';
import { get } from 'svelte/store';

const h = vi.hoisted(() => ({
  startTunnel: vi.fn(),
  fetchTunnels: vi.fn(),
  reportError: vi.fn(),
  session: {
    session: { serverUrl: 'https://x', token: 't', username: 'u' },
    settings: { mode: 'server' },
  },
}));

vi.mock('$lib/bridge', () => ({ startTunnel: h.startTunnel, fetchTunnels: h.fetchTunnels }));
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

import { startIfServerMode, tunnelUi, getMappings, markTerminated, markError } from './tunnel';

describe('tunnel store: startIfServerMode (6.45)', () => {
  beforeEach(() => vi.clearAllMocks());

  it('startTunnel failure -> ui disconnected + error report', async () => {
    h.startTunnel.mockRejectedValueOnce(new Error('frpc missing'));
    await startIfServerMode();
    expect(get(tunnelUi)).toBe('disconnected');
    expect(h.reportError).toHaveBeenCalled();
  });

  it('fetchTunnels failure leaves the tunnel running with mappings = []', async () => {
    h.startTunnel.mockResolvedValueOnce({ running: true });
    h.fetchTunnels.mockRejectedValueOnce(new Error('404'));
    await startIfServerMode();
    expect(get(tunnelUi)).toBe('connected');
    expect(getMappings()).toEqual([]);
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
