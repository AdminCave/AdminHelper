// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// The window of a detached RDP session (R-1101) on a fake frame socket and the real terminals
// store: it takes its session over by id, logs in at the WebSocket with a fresh token, docks with
// its button, shows a failure in its own window, and ends no session as it starts.

import { describe, it, expect, beforeAll, beforeEach, afterEach, vi } from 'vitest';
import { render, cleanup, screen, fireEvent } from '@testing-library/svelte';
import type { FrameHandlers } from '$lib/rdp/frameSocket';
import { setLanguage, tNow } from '$lib/i18n';

const h = vi.hoisted(() => {
  class FakeSocket {
    static all: FakeSocket[] = [];
    close = vi.fn();
    constructor(
      readonly port: number,
      readonly token: string,
      readonly handlers: FrameHandlers,
    ) {
      FakeSocket.all.push(this);
    }
    send(): void {}
  }
  return {
    FakeSocket,
    rdpSessionAttach: vi.fn(async (_id: string) => ({ ws_port: 7101, token: 'fresh' })),
    rdpDock: vi.fn(async (_id: string) => {}),
    rdpSessionStop: vi.fn(async () => {}),
    listen: vi.fn(async () => () => {}),
    refreshSettings: vi.fn(async () => {}),
    reportError: vi.fn(),
  };
});

vi.mock('$lib/rdp/frameSocket', () => ({ FrameSocket: h.FakeSocket }));
vi.mock('$lib/rdp/renderer', async (original) => ({
  ...(await original<typeof import('$lib/rdp/renderer')>()),
  createRenderer: () => ({ kind: '2d', draw: vi.fn(), destroy: vi.fn() }),
}));
vi.mock('@tauri-apps/api/event', () => ({ listen: h.listen }));
vi.mock('$lib/bridge', () => ({
  rdpSessionAttach: h.rdpSessionAttach,
  rdpDock: h.rdpDock,
  rdpSessionStop: h.rdpSessionStop,
  setFullscreen: vi.fn(async () => {}),
}));
vi.mock('$lib/stores/statusBar', () => ({ reportError: h.reportError }));
vi.mock('$lib/stores/session', async () => {
  const { writable } = await import('svelte/store');
  return {
    settings: writable(null),
    sessionStore: writable({ settings: null, session: null }),
    refreshSettings: h.refreshSettings,
  };
});
vi.mock('$lib/stores/tunnel', async () => {
  const { writable } = await import('svelte/store');
  return { tunnelMappings: writable([]), getMappings: () => [] };
});

import DetachedRdp from './DetachedRdp.svelte';

beforeAll(() => setLanguage('en'));

beforeEach(() => {
  vi.clearAllMocks();
  h.FakeSocket.all = [];
  vi.stubGlobal(
    'ResizeObserver',
    class {
      observe(): void {}
      disconnect(): void {}
    },
  );
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

async function mount(second = false) {
  render(DetachedRdp, { sessionId: 'rdp-3', ...(second ? { screen: 1 } : {}) });
  await vi.waitFor(() => expect(h.FakeSocket.all).toHaveLength(1));
}

describe('DetachedRdp', () => {
  it('takes its session over and logs in with a fresh token', async () => {
    await mount();
    expect(h.rdpSessionAttach).toHaveBeenCalledExactlyOnceWith('rdp-3', 0);
    expect(h.FakeSocket.all[0]).toMatchObject({ port: 7101, token: 'fresh' });
    expect(h.refreshSettings).toHaveBeenCalled();
    expect(h.listen).toHaveBeenCalledWith('rdp-session', expect.any(Function));
    // A window of its own ends no session as it starts: main's tab still holds it.
    expect(h.rdpSessionStop).not.toHaveBeenCalled();
  });

  it('docks with its button and shows a failure in its own window', async () => {
    await mount();
    expect(screen.queryByRole('button', { name: 'End session' })).toBeNull();

    h.rdpDock.mockRejectedValueOnce(new Error('no window'));
    await fireEvent.click(screen.getByRole('button', { name: tNow('terminal.dock') }));
    expect(h.rdpDock).toHaveBeenCalledExactlyOnceWith('rdp-3');
    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toBe(tNow('terminal.dockFailed', { error: 'no window' }));

    await fireEvent.click(screen.getByRole('button', { name: tNow('terminal.dock') }));
    expect(h.rdpDock).toHaveBeenCalledTimes(2);
    await vi.waitFor(() => expect(screen.queryByRole('alert')).toBeNull());
    expect(h.rdpSessionStop).not.toHaveBeenCalled();
  });

  it('shows the second monitor without a Dock button', async () => {
    await mount(true);
    expect(h.rdpSessionAttach).toHaveBeenCalledExactlyOnceWith('rdp-3', 1);
    expect(screen.queryByRole('button', { name: tNow('terminal.dock') })).toBeNull();
  });
});
