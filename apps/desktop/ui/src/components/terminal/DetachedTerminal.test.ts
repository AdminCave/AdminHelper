// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// The window of a detached session (R-1070) on a fake xterm and the real terminals store: it
// takes its session over by id, writes the replay and then the live output, sends what is
// typed to its own session only, docks with its button, and ends no session as it starts.

import { describe, it, expect, beforeAll, beforeEach, afterEach, vi } from 'vitest';
import { render, cleanup, screen, fireEvent } from '@testing-library/svelte';
import { tick } from 'svelte';
import type { TerminalMessage } from '$lib/bridge';
import { setLanguage, tNow } from '$lib/i18n';

type Handler<T> = (value: T) => void;

const h = vi.hoisted(() => {
  class FakeTerminal {
    static last: FakeTerminal | null = null;
    options: Record<string, unknown>;
    cols = 80;
    rows = 24;
    data: Handler<string>[] = [];
    write = vi.fn((_data: Uint8Array, done?: () => void) => done?.());
    reset = vi.fn();
    focus = vi.fn();
    dispose = vi.fn();
    clearSelection = vi.fn();
    loadAddon = vi.fn();

    constructor(options: Record<string, unknown>) {
      this.options = { ...options };
      FakeTerminal.last = this;
    }
    open(parent: HTMLElement): void {
      parent.appendChild(document.createElement('textarea'));
    }
    onData(f: Handler<string>) {
      this.data.push(f);
      return { dispose: () => {} };
    }
    onBinary() {
      return { dispose: () => {} };
    }
    onResize() {
      return { dispose: () => {} };
    }
    attachCustomKeyEventHandler(): void {}
    hasSelection(): boolean {
      return false;
    }
    getSelection(): string {
      return '';
    }
  }
  return {
    FakeTerminal,
    channels: [] as ((message: TerminalMessage) => void)[],
    terminalAttach: vi.fn(async (_id: number, onMessage: (message: TerminalMessage) => void) => {
      h.channels.push(onMessage);
    }),
    terminalWrite: vi.fn(async (_id: number, _data: Uint8Array) => {}),
    terminalResize: vi.fn(async () => {}),
    terminalClose: vi.fn(async () => {}),
    terminalCloseAll: vi.fn(async () => {}),
    terminalDock: vi.fn(async () => {}),
    saveSettings: vi.fn(async () => {}),
    refreshSettings: vi.fn(async () => {}),
  };
});

vi.mock('@xterm/xterm', () => ({ Terminal: h.FakeTerminal }));
vi.mock('@xterm/addon-fit', () => ({
  FitAddon: class {
    fit = vi.fn();
  },
}));
vi.mock('@xterm/addon-search', () => ({
  SearchAddon: class {
    findNext = vi.fn();
    findPrevious = vi.fn();
  },
}));
vi.mock('@tauri-apps/api/event', () => ({ listen: vi.fn(async () => () => {}) }));
vi.mock('$lib/bridge', () => ({
  terminalAttach: h.terminalAttach,
  terminalWrite: h.terminalWrite,
  terminalResize: h.terminalResize,
  terminalClose: h.terminalClose,
  terminalCloseAll: h.terminalCloseAll,
  terminalDock: h.terminalDock,
  saveSettings: h.saveSettings,
}));
vi.mock('$lib/stores/session', async () => {
  const { writable } = await import('svelte/store');
  return { settings: writable(null), refreshSettings: h.refreshSettings };
});
vi.mock('$lib/stores/tunnel', async () => {
  const { writable } = await import('svelte/store');
  return { tunnelMappings: writable([]), getMappings: () => [] };
});

import DetachedTerminal from './DetachedTerminal.svelte';
import { clearStatus, reportError } from '$lib/stores/statusBar';

// An ArrayBuffer of this realm, as the store tells output by `instanceof ArrayBuffer`.
const out = (text: string) => Uint8Array.from(text, (c) => c.charCodeAt(0)).buffer as ArrayBuffer;
const text = (data: Uint8Array) => String.fromCharCode(...data);

async function mount() {
  render(DetachedTerminal, { id: 7 });
  await vi.waitFor(() => expect(h.FakeTerminal.last).not.toBeNull());
  await vi.waitFor(() => expect(h.channels.length).toBe(1));
  await tick();
  return h.FakeTerminal.last!;
}

beforeAll(() => setLanguage('en'));

beforeEach(() => {
  vi.clearAllMocks();
  h.FakeTerminal.last = null;
  h.channels = [];
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
  clearStatus();
  vi.unstubAllGlobals();
});

describe('DetachedTerminal', () => {
  it('takes its session over, writes the replay and the live output, and types into it', async () => {
    const term = await mount();
    expect(h.terminalAttach).toHaveBeenCalledExactlyOnceWith(7, expect.any(Function));
    expect(h.refreshSettings).toHaveBeenCalled();
    // A window of its own ends no session as it starts: the main window's are still running.
    expect(h.terminalCloseAll).not.toHaveBeenCalled();
    expect(h.terminalClose).not.toHaveBeenCalled();

    h.channels[0](out('kept'));
    h.channels[0]({ replayed: true });
    h.channels[0](out('live'));
    await tick();
    const written = term.write.mock.calls.map(([data]) => text(data as Uint8Array));
    expect(written.filter((w) => w !== '')).toEqual(['kept', 'live']);

    term.data.forEach((f) => f('ls\r'));
    await vi.waitFor(() => expect(h.terminalWrite).toHaveBeenCalled());
    expect(h.terminalWrite.mock.calls.every(([id]) => id === 7)).toBe(true);
  });

  it('shows an error reported by the terminals store in its own window (R-1169)', async () => {
    await mount();
    reportError('connection refused');
    expect(await screen.findByText('connection refused')).toBeTruthy();
  });

  it('docks with its button and shows a failure in its own window', async () => {
    await mount();
    expect(screen.queryByRole('button', { name: tNow('terminal.close') })).toBeNull();

    h.terminalDock.mockRejectedValueOnce(new Error('no window'));
    await fireEvent.click(screen.getByRole('button', { name: tNow('terminal.dock') }));
    expect(h.terminalDock).toHaveBeenCalledExactlyOnceWith(7);
    const failed = tNow('terminal.dockFailed', { error: 'no window' });
    expect((await screen.findByText(failed)).getAttribute('role')).toBe('alert');

    await fireEvent.click(screen.getByRole('button', { name: tNow('terminal.dock') }));
    expect(h.terminalDock).toHaveBeenCalledTimes(2);
    await vi.waitFor(() => expect(screen.queryByText(failed)).toBeNull());
  });

  it('offers to dock once the program has ended', async () => {
    await mount();
    h.channels[0]({ replayed: true });
    h.channels[0]({ exitCode: 0 });
    await tick();
    expect(screen.getByText(tNow('terminal.ended'))).toBeTruthy();
    expect(screen.getAllByRole('button', { name: tNow('terminal.dock') }).length).toBe(2);
    expect(screen.queryByRole('button', { name: tNow('terminal.reconnect') })).toBeNull();
  });
});
