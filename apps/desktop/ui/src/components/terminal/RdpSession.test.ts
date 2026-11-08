// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// One embedded RDP session (R-1098) over a fake frame socket and renderer: each phase has its
// overlay, a refused certificate is shown to be confirmed and its trust starts anew, the actions
// reach the store or the bridge, a new session gets a socket of its own and the old one closes,
// and the foot shows what the stream measured, a dash for what it did not.

import { describe, it, expect, beforeAll, beforeEach, afterEach, vi } from 'vitest';
import { render, cleanup, screen, fireEvent, within } from '@testing-library/svelte';
import { tick } from 'svelte';
import type { Connection } from '$lib/bridge/types';
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
    trustRdpCertificate: vi.fn(async () => true),
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
  trustRdpCertificate: h.trustRdpCertificate,
}));
vi.mock('$lib/bridge', () => ({
  rdpSessionScreenshot: h.rdpSessionScreenshot,
  rdpSessionInfo: h.rdpSessionInfo,
}));
vi.mock('$lib/stores/statusBar', () => ({ reportError: h.reportError }));
vi.mock('$lib/stores/tunnel', async () => {
  const { writable } = await import('svelte/store');
  return { tunnelMappings: writable([]) };
});

import RdpSession from './RdpSession.svelte';

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
});

afterEach(() => cleanup());

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
    expect(h.FakeSocket.all[0].sent).toEqual([{ t: 'cad' }]);
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
