// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// One embedded RDP session (R-1098) over a fake frame socket and renderer: each phase has its
// overlay, a refused certificate is shown to be confirmed and its trust starts anew, the actions
// reach the store or the bridge, a new session gets a socket of its own and the old one closes,
// and the foot shows what the stream measured, a dash for what it did not. The desktop follows
// the size of the tab after a pause or keeps a fixed size with a zoom (R-1100), starting with the
// modes of the settings.

import { describe, it, expect, beforeAll, beforeEach, afterEach, vi } from 'vitest';
import { render, cleanup, screen, fireEvent, within } from '@testing-library/svelte';
import { tick } from 'svelte';
import type { Writable } from 'svelte/store';
import type { Connection, Settings } from '$lib/bridge/types';
import type { FrameHandlers, FrameInput } from '$lib/rdp/frameSocket';
import { setLanguage } from '$lib/i18n';
import type { RdpView, TerminalSession } from '$lib/stores/terminals';

const h = vi.hoisted(() => {
  class FakeSocket {
    static all: FakeSocket[] = [];
    sent: FrameInput[] = [];
    close = vi.fn();
    constructor(
      readonly port: number,
      readonly token: string,
      readonly handlers: FrameHandlers,
    ) {
      FakeSocket.all.push(this);
    }
    send(input: FrameInput): void {
      this.sent.push(input);
    }
  }
  return {
    FakeSocket,
    draw: vi.fn(),
    disconnectRdp: vi.fn(),
    reconnectRdp: vi.fn(async () => true),
    setRdpPerformance: vi.fn(async () => true),
    setRdpDisplay: vi.fn(),
    setRdpWindow: vi.fn(),
    setRdpScaling: vi.fn(),
    trustRdpCertificate: vi.fn(async () => true),
    // The callbacks of the ResizeObservers, and the size the picture's box reports.
    resized: [] as (() => void)[],
    box: { width: 0, height: 0 },
    rdpSessionScreenshot: vi.fn(async () => true),
    rdpSessionInfo: vi.fn(),
    reportError: vi.fn(),
  };
});

vi.mock('$lib/rdp/frameSocket', () => ({ FrameSocket: h.FakeSocket }));
vi.mock('$lib/rdp/renderer', () => ({
  createRenderer: () => ({ kind: '2d', draw: h.draw, destroy: vi.fn() }),
}));
vi.mock('$lib/stores/terminals', () => ({
  disconnectRdp: h.disconnectRdp,
  reconnectRdp: h.reconnectRdp,
  setRdpPerformance: h.setRdpPerformance,
  setRdpDisplay: h.setRdpDisplay,
  setRdpWindow: h.setRdpWindow,
  setRdpScaling: h.setRdpScaling,
  trustRdpCertificate: h.trustRdpCertificate,
}));
vi.mock('$lib/stores/session', async () => {
  const { writable } = await import('svelte/store');
  return { settings: writable(null) };
});
vi.mock('$lib/bridge', () => ({
  rdpSessionScreenshot: h.rdpSessionScreenshot,
  rdpSessionInfo: h.rdpSessionInfo,
}));
vi.mock('$lib/stores/statusBar', () => ({ reportError: h.reportError }));
vi.mock('$lib/stores/tunnel', async () => {
  const { writable } = await import('svelte/store');
  return { tunnelMappings: writable([]) };
});

import { settings as settingsStore } from '$lib/stores/session';
import RdpSession from './RdpSession.svelte';

const settings = settingsStore as unknown as Writable<Partial<Settings> | null>;

const CONN = {
  id: 'r1',
  name: 'win',
  kind: 'rdp',
  host: 'win.example',
  port: 3390,
  username: 'ops',
  domain: 'CORP',
} as Connection;

const KEY = 'terminal-1';

function view(over: Partial<RdpView> = {}): RdpView {
  return {
    sessionId: 's1',
    wsPort: 7001,
    token: 't1',
    phase: 'connected',
    code: null,
    certificate: null,
    performance: null,
    window: null,
    scaling: null,
    notice: null,
    ...over,
  };
}

function session(rdp: RdpView, status: TerminalSession['status'] = 'connected'): TerminalSession {
  return {
    key: KEY,
    connection: CONN,
    resolved: CONN,
    status,
    exitCode: null,
    connectedAt: null,
    backendId: null,
    rdp,
  };
}

function mount(rdp: RdpView = view()) {
  const onClose = vi.fn();
  const result = render(RdpSession, { session: session(rdp), onClose });
  return { ...result, onClose };
}

const button = (name: string) => screen.getByRole('button', { name });
// The spinner is a status of its own: the overlay is the one around it.
const overlay = () => document.querySelector<HTMLElement>('.rdp-overlay');
const foot = (container: HTMLElement) => container.querySelector('.rdp-foot')!.textContent ?? '';

beforeAll(() => setLanguage('en'));

beforeEach(() => {
  vi.clearAllMocks();
  h.FakeSocket.all = [];
  h.resized = [];
  h.box = { width: 1000, height: 600 };
  settings.set(null);
  vi.stubGlobal(
    'ResizeObserver',
    class {
      constructor(callback: () => void) {
        h.resized.push(callback);
      }
      observe(): void {}
      disconnect(): void {}
    },
  );
  // jsdom lays nothing out: the picture's box has the size the test gives it.
  for (const side of ['clientWidth', 'clientHeight'] as const) {
    vi.spyOn(HTMLElement.prototype, side, 'get').mockImplementation(function (this: HTMLElement) {
      if (!this.classList.contains('rdp-view')) return 0;
      return side === 'clientWidth' ? h.box.width : h.box.height;
    });
  }
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

const sizes = () => h.FakeSocket.all[0].sent.filter((input) => input.t === 'size');
const select = (container: HTMLElement, name: string) =>
  container.querySelector<HTMLSelectElement>(`#rdp-${name}-${KEY}`)!;

describe('RdpSession (R-1098)', () => {
  it('shows what it connects to and opens a socket for the session', () => {
    mount();
    expect(screen.getByText('CORP\\ops @ win.example:3390')).toBeTruthy();
    expect(h.FakeSocket.all).toHaveLength(1);
    expect(h.FakeSocket.all[0]).toMatchObject({ port: 7001, token: 't1' });
  });

  it('shows the phases over the picture', async () => {
    const { rerender } = mount(
      view({ phase: 'connecting', sessionId: null, wsPort: null, token: null }),
    );
    expect(overlay()!.textContent).toContain('Connecting to win.example');
    expect(h.FakeSocket.all).toHaveLength(0);

    await rerender({
      session: session(view({ phase: 'disconnected', code: 'network', sessionId: null })),
    });
    expect(overlay()!.textContent).toContain('The network connection broke off.');
    await fireEvent.click(within(overlay()!).getByRole('button', { name: 'Reconnect' }));
    expect(h.reconnectRdp).toHaveBeenCalledWith(KEY);

    await rerender({
      session: session(view({ phase: 'disconnected', code: 'closed', sessionId: null })),
    });
    expect(overlay()!.textContent).toContain('Session disconnected.');

    await rerender({ session: session(view({ phase: 'failed', sessionId: null })) });
    expect(overlay()!.textContent).toContain('The connection failed.');

    await rerender({ session: session(view({ phase: 'connected' })) });
    expect(overlay()).toBeNull();
  });

  it('asks to confirm a refused certificate and trusts it; put aside, the overlay offers it again', async () => {
    mount(
      view({
        phase: 'certificate',
        sessionId: null,
        certificate: { identity: 'win.example:3390', fingerprint: 'ab:cd:ef', reason: 'changed' },
      }),
    );
    const dialog = screen.getByRole('dialog');
    expect(dialog.textContent).toContain('ab:cd:ef');
    await fireEvent.click(within(dialog).getByRole('button', { name: 'Do not connect' }));
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(h.trustRdpCertificate).not.toHaveBeenCalled();

    await fireEvent.click(within(overlay()!).getByRole('button', { name: 'Check certificate' }));
    await fireEvent.click(
      within(screen.getByRole('dialog')).getByRole('button', { name: 'Trust and connect' }),
    );
    expect(h.trustRdpCertificate).toHaveBeenCalledWith(KEY);
  });

  it('sends Ctrl+Alt+Del, takes a screenshot, shows the info, disconnects, reconnects and closes', async () => {
    h.rdpSessionInfo.mockResolvedValueOnce({
      target: 'win.example:3390',
      via_tunnel: false,
      credssp: true,
      certificate: 'pinned',
    });
    const { onClose } = mount();
    await fireEvent.click(button('Ctrl+Alt+Del'));
    // The size the tab asked for on mount goes first (R-1100).
    expect(h.FakeSocket.all[0].sent.filter((input) => input.t !== 'size')).toEqual([{ t: 'cad' }]);
    await fireEvent.click(button('Screenshot'));
    expect(h.rdpSessionScreenshot).toHaveBeenCalledWith('s1');
    await fireEvent.click(button('Connection info'));
    await vi.waitFor(() =>
      expect(screen.getByRole('dialog').textContent).toContain('win.example:3390'),
    );
    await fireEvent.click(button('Disconnect'));
    expect(h.disconnectRdp).toHaveBeenCalledWith(KEY);
    await fireEvent.click(screen.getAllByRole('button', { name: 'Reconnect' })[0]);
    expect(h.reconnectRdp).toHaveBeenCalledWith(KEY);
    await fireEvent.click(button('End session'));
    expect(onClose).toHaveBeenCalled();
  });

  it('says why a screenshot failed', async () => {
    h.rdpSessionScreenshot.mockRejectedValueOnce(new Error('no picture yet'));
    mount();
    await fireEvent.click(button('Screenshot'));
    await vi.waitFor(() => expect(h.reportError).toHaveBeenCalledWith('no picture yet'));
  });

  it('keeps Ctrl+Alt+Del and the screenshot off until connected', () => {
    mount(view({ phase: 'connecting' }));
    expect((button('Ctrl+Alt+Del') as HTMLButtonElement).disabled).toBe(true);
    expect((button('Screenshot') as HTMLButtonElement).disabled).toBe(true);
  });

  it('starts anew with the profile chosen in the tab', async () => {
    const { container } = mount();
    const select = container.querySelector('select')!;
    expect(select.value).toBe('auto');
    select.value = 'low';
    await fireEvent.change(select);
    expect(h.setRdpPerformance).toHaveBeenCalledWith(KEY, 'low');
  });

  it('asks for the size of the tab at once, and for a new one once it kept it for 300 ms', async () => {
    mount();
    expect(h.setRdpDisplay).toHaveBeenLastCalledWith(KEY, { width: 1000, height: 600, scale: 100 });
    expect(sizes().at(-1)).toEqual({ t: 'size', w: 1000, h: 600, scale: 100 });

    vi.useFakeTimers();
    const before = sizes().length;
    h.box = { width: 1200, height: 700 };
    h.resized[0]();
    vi.advanceTimersByTime(200);
    h.box = { width: 1400, height: 800 };
    h.resized[0]();
    vi.advanceTimersByTime(299);
    expect(sizes()).toHaveLength(before);
    vi.advanceTimersByTime(1);
    expect(sizes().slice(before)).toEqual([{ t: 'size', w: 1400, h: 800, scale: 100 }]);
    expect(h.setRdpDisplay).toHaveBeenLastCalledWith(KEY, { width: 1400, height: 800, scale: 100 });
  });

  it('starts with the modes of the settings, then of the connection, then of the tab', async () => {
    settings.set({ rdpWindowMode: 'custom', rdpScalingMode: 'hdpi', rdpCustomSize: '1920x1080' });
    const { container } = mount();
    expect(select(container, 'window').value).toBe('custom');
    expect(select(container, 'scaling').value).toBe('hdpi');
    expect(h.setRdpDisplay).toHaveBeenLastCalledWith(KEY, {
      width: 1920,
      height: 1080,
      scale: 175,
    });
    cleanup();

    const own = { ...CONN, options: { rdp: { windowMode: 'fit', scalingMode: 'normal' } } };
    const first = render(RdpSession, {
      session: { ...session(view()), connection: own as Connection },
    });
    expect(select(first.container, 'window').value).toBe('fit');
    expect(h.setRdpDisplay).toHaveBeenLastCalledWith(KEY, { width: 1000, height: 600, scale: 100 });
    cleanup();

    const tab = mount(view({ window: 'custom', scaling: 'normal' }));
    expect(select(tab.container, 'window').value).toBe('custom');
    expect(h.setRdpDisplay).toHaveBeenLastCalledWith(KEY, {
      width: 1920,
      height: 1080,
      scale: 100,
    });
  });

  it('chooses the window mode and the scaling for this tab, and the session follows', async () => {
    const { container, rerender } = mount();
    const window = select(container, 'window');
    window.value = 'custom';
    await fireEvent.change(window);
    expect(h.setRdpWindow).toHaveBeenCalledWith(KEY, 'custom');
    const scaling = select(container, 'scaling');
    scaling.value = 'hdpi';
    await fireEvent.change(scaling);
    expect(h.setRdpScaling).toHaveBeenCalledWith(KEY, 'hdpi');

    await rerender({ session: session(view({ window: 'custom', scaling: 'hdpi' })) });
    expect(sizes().at(-1)).toEqual({ t: 'size', w: 1280, h: 720, scale: 175 });
    // A fixed desktop does not follow the tab.
    vi.useFakeTimers();
    const before = sizes().length;
    h.box = { width: 1600, height: 900 };
    h.resized[0]();
    vi.advanceTimersByTime(1000);
    expect(sizes()).toHaveLength(before);
  });

  it('zooms a fixed desktop from 25 to 200 %, back to 1:1 and fitted into the tab', async () => {
    const fitted = mount();
    expect(screen.queryByRole('button', { name: 'Zoom in' })).toBeNull();
    fitted.unmount();

    const { container } = mount(view({ window: 'custom' }));
    const canvas = container.querySelector('canvas')!;
    const zoom = () => container.querySelector('.rdp-zoom')!.textContent!.trim();
    expect(zoom()).toBe('100 %');
    expect(canvas.style.width).toBe('1280px');
    expect(container.querySelector('.rdp-view')!.classList.contains('zoomed')).toBe(true);

    for (let i = 0; i < 4; i += 1) await fireEvent.click(button('Zoom out'));
    expect(zoom()).toBe('25 %');
    expect(canvas.style.width).toBe('320px');
    expect((button('Zoom out') as HTMLButtonElement).disabled).toBe(true);

    await fireEvent.click(button('1:1'));
    for (let i = 0; i < 5; i += 1) await fireEvent.click(button('Zoom in'));
    expect(zoom()).toBe('200 %');
    expect(canvas.style.height).toBe('1440px');
    expect((button('Zoom in') as HTMLButtonElement).disabled).toBe(true);

    await fireEvent.click(button('Fit'));
    expect(zoom()).toBe('Fit');
    expect(canvas.style.width).toBe('');
    expect(container.querySelector('.rdp-view')!.classList.contains('zoomed')).toBe(false);
  });

  it('asks the opened socket for the size the tab got while the session started', async () => {
    const { rerender } = mount(
      view({ phase: 'connecting', sessionId: null, wsPort: null, token: null }),
    );
    vi.useFakeTimers();
    h.box = { width: 1600, height: 900 };
    h.resized[0]();
    vi.advanceTimersByTime(300);
    await rerender({ session: session(view({ phase: 'connecting' })) });
    const socket = h.FakeSocket.all[0];
    expect(socket.sent).toEqual([]);
    socket.handlers.opened();
    expect(socket.sent).toEqual([{ t: 'size', w: 1600, h: 900, scale: 100 }]);
  });

  it('keeps the socket of the session while its phase changes', async () => {
    const { rerender } = mount(view({ phase: 'connecting' }));
    await rerender({ session: session(view({ phase: 'connected' })) });
    await rerender({ session: session(view({ phase: 'reconnecting' })) });
    expect(h.FakeSocket.all).toHaveLength(1);
    expect(h.FakeSocket.all[0].close).not.toHaveBeenCalled();
  });

  it('gives a new session a socket of its own and closes the old one', async () => {
    const { rerender } = mount();
    await rerender({ session: session(view({ sessionId: 's2', wsPort: 7002, token: 't2' })) });
    expect(h.FakeSocket.all).toHaveLength(2);
    expect(h.FakeSocket.all[0].close).toHaveBeenCalled();
    expect(h.FakeSocket.all[1]).toMatchObject({ port: 7002, token: 't2' });
  });

  it('draws the frames and shows the figures of the stream, a dash for what is missing', async () => {
    const { container } = mount(view({ notice: 'drive_unavailable' }));
    expect(foot(container)).toContain('— · — · — · — · —');
    expect(foot(container)).toContain('No drive shared');
    const socket = h.FakeSocket.all[0];
    const frame = {
      header: { x: 0, y: 0, width: 1, height: 1, desktopWidth: 1280, desktopHeight: 720 },
      pixels: new Uint8Array(4),
    };
    socket.handlers.frame(frame);
    expect(h.draw).toHaveBeenCalledWith(frame);
    socket.handlers.stats({ fps: 29.6, width: 1280, height: 720 });
    await tick();
    expect(foot(container)).toContain('1280×720 · — · 30 fps · — · —');
    socket.handlers.stats({ fps: 30, width: 1280, height: 720, mbps: 2.345, rttMs: 11.6 });
    await tick();
    expect(foot(container)).toContain('1280×720 · — · 30 fps · 2.3 Mbit/s · 12 ms');
  });
});
