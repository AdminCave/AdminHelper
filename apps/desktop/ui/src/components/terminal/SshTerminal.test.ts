// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// One session of the embedded terminal (R-1069) on a fake xterm: what is typed goes to the
// program, its output to the terminal, the options reach the terminal as they change, copying
// on select and pasting with a right click follow the options, a paste carries only text, the
// search goes forward and back, and an ended session offers to reconnect on an empty terminal.
// The snippets (R-1071) and the files (R-1072) have a panel each, which takes the place of the
// options, and the foot warns while a snippet goes to every session.

import { describe, it, expect, beforeAll, beforeEach, afterEach, vi } from 'vitest';
import { render, cleanup, screen, fireEvent, within } from '@testing-library/svelte';
import { tick } from 'svelte';
import { writable } from 'svelte/store';
import type { Connection, Settings, TerminalPrefs, TunnelMapping } from '$lib/bridge/types';
import { setLanguage, tNow } from '$lib/i18n';
import { getSettingsDefaults, getTerminalDefaults } from '$lib/models/settings';
import type { TerminalSession } from '$lib/stores/terminals';

type Handler<T> = (value: T) => void;

const h = vi.hoisted(() => {
  class FakeTerminal {
    static last: FakeTerminal | null = null;
    options: Record<string, unknown>;
    cols = 80;
    rows = 24;
    selection = '';
    textarea: HTMLTextAreaElement | null = null;
    data: Handler<string>[] = [];
    binary: Handler<string>[] = [];
    resized: Handler<{ cols: number; rows: number }>[] = [];
    keyHandler: ((e: KeyboardEvent) => boolean) | null = null;
    write = vi.fn();
    reset = vi.fn();
    focus = vi.fn();
    dispose = vi.fn();
    clearSelection = vi.fn();
    loadAddon = vi.fn();
    // As xterm's paste: the text comes out as typed.
    paste = vi.fn((text: string) => this.data.forEach((f) => f(text)));
    // As xterm, its textarea takes the paste of the webview as it is.
    ownPaste = vi.fn();

    constructor(options: Record<string, unknown>) {
      this.options = { ...options };
      FakeTerminal.last = this;
    }
    open(parent: HTMLElement): void {
      this.textarea = document.createElement('textarea');
      this.textarea.addEventListener('paste', this.ownPaste);
      parent.appendChild(this.textarea);
    }
    onData(f: Handler<string>) {
      this.data.push(f);
      return { dispose: () => {} };
    }
    onBinary(f: Handler<string>) {
      this.binary.push(f);
      return { dispose: () => {} };
    }
    onResize(f: Handler<{ cols: number; rows: number }>) {
      this.resized.push(f);
      return { dispose: () => {} };
    }
    attachCustomKeyEventHandler(f: (e: KeyboardEvent) => boolean): void {
      this.keyHandler = f;
    }
    hasSelection(): boolean {
      return this.selection !== '';
    }
    getSelection(): string {
      return this.selection;
    }
  }
  return {
    FakeTerminal,
    fit: vi.fn(),
    findNext: vi.fn(),
    findPrevious: vi.fn(),
    sink: null as ((data: Uint8Array) => void) | null,
    detach: vi.fn(),
    attachTerminal: vi.fn(),
    writeTerminal: vi.fn(),
    resizeTerminal: vi.fn(),
    reconnectTerminal: vi.fn(async () => {}),
    runSnippet: vi.fn(async () => {}),
    setSnippets: vi.fn(async () => {}),
    saveSettings: vi.fn<(next: unknown) => Promise<void>>(async () => {}),
    refreshSettings: vi.fn(async () => {}),
    reportError: vi.fn(),
    sftpList: vi.fn(async (_session: number, path: string) => ({ path, entries: [] })),
    observers: [] as (() => void)[],
  };
});

vi.mock('@xterm/xterm', () => ({ Terminal: h.FakeTerminal }));
vi.mock('@xterm/addon-fit', () => ({
  FitAddon: class {
    fit = h.fit;
  },
}));
vi.mock('@xterm/addon-search', () => ({
  SearchAddon: class {
    findNext = h.findNext;
    findPrevious = h.findPrevious;
  },
}));
vi.mock('$lib/stores/terminals', async () => {
  const { writable } = await import('svelte/store');
  return {
    attachTerminal: h.attachTerminal,
    writeTerminal: h.writeTerminal,
    resizeTerminal: h.resizeTerminal,
    reconnectTerminal: h.reconnectTerminal,
    runSnippet: h.runSnippet,
    snippetBroadcast: writable(false),
    terminals: writable({ sessions: [], active: 'terminal-1' }),
  };
});
vi.mock('$lib/bridge', () => ({
  saveSettings: h.saveSettings,
  sftpList: h.sftpList,
}));
vi.mock('@tauri-apps/api/event', () => ({ listen: vi.fn(async () => () => {}) }));
vi.mock('$lib/stores/statusBar', () => ({ reportError: h.reportError }));
vi.mock('$lib/stores/session', async () => {
  const { writable } = await import('svelte/store');
  return {
    settings: writable(null),
    refreshSettings: h.refreshSettings,
    setSnippets: h.setSnippets,
  };
});
vi.mock('$lib/stores/tunnel', async () => {
  const { writable } = await import('svelte/store');
  return { tunnelMappings: writable([]) };
});

import { settings } from '$lib/stores/session';
import { snippetBroadcast as broadcastStore } from '$lib/stores/terminals';
import { tunnelMappings } from '$lib/stores/tunnel';
import { sanitizePaste } from '$lib/terminal/paste';
import { terminalTheme } from '$lib/terminal/themes';
import SshTerminal from './SshTerminal.svelte';

const settingsStore = settings as unknown as ReturnType<typeof writable<Settings | null>>;
const mappingsStore = tunnelMappings as unknown as ReturnType<typeof writable<TunnelMapping[]>>;
const snippetBroadcast = broadcastStore as unknown as ReturnType<typeof writable<boolean>>;

const CONN = {
  id: 'c1',
  name: 'db',
  kind: 'ssh',
  host: 'db.example',
  port: 2222,
  username: 'ops',
} as Connection;

const KEY = 'terminal-1';

function session(over: Partial<TerminalSession> = {}): TerminalSession {
  return {
    key: KEY,
    connection: CONN,
    resolved: CONN,
    status: 'connecting',
    exitCode: null,
    connectedAt: null,
    backendId: null,
    ...over,
  };
}

function withPrefs(over: Partial<TerminalPrefs>): void {
  settingsStore.set({
    ...getSettingsDefaults(),
    terminal: { ...getTerminalDefaults(), ...over },
  });
}

let width = 0;
let clipboard: { writeText: ReturnType<typeof vi.fn>; readText: ReturnType<typeof vi.fn> };

async function mount(s: TerminalSession = session()) {
  const onClose = vi.fn();
  const view = render(SshTerminal, { session: s, onClose });
  await vi.waitFor(() => expect(h.FakeTerminal.last).not.toBeNull());
  await tick();
  const term = h.FakeTerminal.last!;
  const body = view.container.querySelector('.term-body') as HTMLElement;
  return { ...view, term, body, onClose };
}

const typed = (text: string) => new TextEncoder().encode(text);

beforeAll(() => {
  setLanguage('en');
  Object.defineProperty(HTMLElement.prototype, 'clientWidth', {
    configurable: true,
    get: () => width,
  });
  Object.defineProperty(HTMLElement.prototype, 'clientHeight', {
    configurable: true,
    get: () => width,
  });
});

beforeEach(() => {
  vi.clearAllMocks();
  h.FakeTerminal.last = null;
  h.sink = null;
  h.observers = [];
  h.attachTerminal.mockImplementation((_key: string, sink: (data: Uint8Array) => void) => {
    h.sink = sink;
    return h.detach;
  });
  // As the bridge and the refresh after it: the settings then hold what was saved.
  h.saveSettings.mockImplementation(async (next) => settingsStore.set(next as Settings));
  width = 600;
  withPrefs({});
  mappingsStore.set([]);
  snippetBroadcast.set(false);
  clipboard = {
    writeText: vi.fn(async () => {}),
    readText: vi.fn(async () => 'ls -la'),
  };
  Object.defineProperty(navigator, 'clipboard', { configurable: true, value: clipboard });
  vi.stubGlobal(
    'ResizeObserver',
    class {
      constructor(private cb: () => void) {
        h.observers.push(() => this.cb());
      }
      observe(): void {}
      disconnect(): void {}
    },
  );
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe('SshTerminal', () => {
  it('opens the terminal with the options and sends what is typed to the program', async () => {
    withPrefs({ fontSize: 15, theme: 'light', cursor: 'bar', scrollback: 1000 });
    const { term } = await mount();

    expect(term.options).toMatchObject({
      fontSize: 15,
      theme: terminalTheme('light'),
      cursorStyle: 'bar',
      scrollback: 1000,
    });
    // A link in the output opens nothing.
    const links = term.options.linkHandler as { activate: () => void };
    expect(links.activate()).toBeUndefined();
    expect(term.focus).toHaveBeenCalled();

    term.data.forEach((f) => f('ü\r'));
    expect(h.writeTerminal).toHaveBeenCalledWith(KEY, typed('ü\r'));
    term.binary.forEach((f) => f('\x1b[M \xff!'));
    expect(h.writeTerminal).toHaveBeenLastCalledWith(
      KEY,
      Uint8Array.from([0x1b, 0x5b, 0x4d, 0x20, 0xff, 0x21]),
    );
  });

  it('leaves the keys with a dialog that is still open when it starts', async () => {
    // Connect in the connection editor keeps the editor open over the new tab.
    const dialog = document.createElement('div');
    dialog.setAttribute('role', 'dialog');
    dialog.setAttribute('aria-modal', 'true');
    const button = document.createElement('button');
    dialog.append(button);
    document.body.append(dialog);
    button.focus();
    try {
      const { term } = await mount();

      expect(term.focus).not.toHaveBeenCalled();
      expect(document.activeElement).toBe(button);
    } finally {
      dialog.remove();
    }
  });

  it('writes the output of the program and lets go of it when it unmounts', async () => {
    const { term, unmount } = await mount();
    expect(h.attachTerminal).toHaveBeenCalledWith(KEY, expect.any(Function));

    h.sink!(typed('hello'));
    // Output of the program comes without a callback; only the end of a replay brings one.
    expect(term.write).toHaveBeenCalledWith(typed('hello'), undefined);

    unmount();
    expect(h.detach).toHaveBeenCalled();
    expect(term.dispose).toHaveBeenCalled();
  });

  it('fits to its size, sends a new size to the program and skips a pane without size', async () => {
    const { term } = await mount();
    expect(h.fit).toHaveBeenCalledTimes(1);

    term.resized.forEach((f) => f({ cols: 120, rows: 40 }));
    expect(h.resizeTerminal).toHaveBeenCalledWith(KEY, 120, 40);
    await tick();
    expect(screen.getByText('120×40')).toBeTruthy();

    // A pane in the background: the terminal keeps its size.
    width = 0;
    h.observers.forEach((f) => f());
    expect(h.fit).toHaveBeenCalledTimes(1);
    width = 800;
    h.observers.forEach((f) => f());
    expect(h.fit).toHaveBeenCalledTimes(2);
  });

  it('shows where it is connected, its tunnel and its status', async () => {
    mappingsStore.set([
      { id: 'm0', connectionId: 'c1', enabled: false, name: 'off' },
      { id: 'm1', connectionId: 'c1', enabled: true, name: 'db-tunnel' },
      { id: 'm2', connectionId: 'c2', enabled: true, name: 'other' },
    ] as TunnelMapping[]);
    const { rerender } = await mount();

    expect(screen.getByText('ops@db.example:2222')).toBeTruthy();
    expect(screen.getByText('db-tunnel')).toBeTruthy();
    expect(screen.queryByText('other')).toBeNull();
    expect(screen.getAllByText(tNow('terminal.status.connecting')).length).toBeGreaterThan(0);

    const at = new Date(2026, 10, 5, 9, 4, 7).getTime();
    await rerender({ session: session({ status: 'connected', connectedAt: at }) });
    const since = tNow('terminal.status.connectedSince', {
      time: new Date(at).toLocaleTimeString('en-GB', {
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
      }),
    });
    expect(screen.getAllByText(since).length).toBeGreaterThan(0);
  });

  it('leaves out port 22 and a missing user', async () => {
    await mount(session({ connection: { ...CONN, port: 22, username: null } }));
    expect(screen.getByText('db.example')).toBeTruthy();
  });

  it('takes a change of the options without opening the terminal again', async () => {
    const { term } = await mount();
    h.fit.mockClear();

    withPrefs({ theme: 'contrast', cursor: 'underline', scrollback: 100_000 });
    await tick();
    expect(term.options).toMatchObject({
      theme: terminalTheme('contrast'),
      cursorStyle: 'underline',
      scrollback: 100_000,
    });
    expect(h.fit).not.toHaveBeenCalled();

    withPrefs({ theme: 'contrast', cursor: 'underline', scrollback: 100_000, fontSize: 18 });
    await tick();
    expect(term.options.fontSize).toBe(18);
    // Another font size is another cell size.
    expect(h.fit).toHaveBeenCalledTimes(1);
    expect(h.FakeTerminal.last).toBe(term);
  });

  it('changes the font size with its buttons and saves it', async () => {
    withPrefs({ fontSize: 21 });
    const { term } = await mount();

    await fireEvent.click(screen.getByRole('button', { name: tNow('terminal.fontLarger') }));
    expect(term.options.fontSize).toBe(22);
    await vi.waitFor(() =>
      expect(h.saveSettings).toHaveBeenCalledWith(
        expect.objectContaining({ terminal: expect.objectContaining({ fontSize: 22 }) }),
      ),
    );
    const larger = screen.getByRole('button', { name: tNow('terminal.fontLarger') });
    expect((larger as HTMLButtonElement).disabled).toBe(true);

    await fireEvent.click(screen.getByRole('button', { name: tNow('terminal.fontSmaller') }));
    expect(term.options.fontSize).toBe(21);
  });

  it('copies a selection made with the mouse when the options say so', async () => {
    const { term, body } = await mount();

    await fireEvent.mouseDown(body, { button: 0 });
    term.selection = 'uptime';
    await fireEvent.mouseUp(window);
    expect(clipboard.writeText).toHaveBeenCalledWith('uptime');

    // A selection the search made: no mouse, nothing copied.
    clipboard.writeText.mockClear();
    term.selection = 'match';
    await fireEvent.mouseUp(window);
    expect(clipboard.writeText).not.toHaveBeenCalled();

    withPrefs({ copyOnSelect: false });
    await tick();
    await fireEvent.mouseDown(body, { button: 0 });
    await fireEvent.mouseUp(window);
    expect(clipboard.writeText).not.toHaveBeenCalled();
  });

  it('pastes on a right click, and points to Ctrl+Shift+V when the clipboard is closed', async () => {
    const { body } = await mount();

    expect(await fireEvent.contextMenu(body)).toBe(false);
    await vi.waitFor(() => expect(h.writeTerminal).toHaveBeenCalledWith(KEY, typed('ls -la')));
    expect(screen.queryByRole('status')).toBeNull();

    clipboard.readText.mockRejectedValueOnce(new Error('not allowed'));
    await fireEvent.contextMenu(body);
    const hint = await screen.findByRole('status');
    expect(hint.textContent).toBe(tNow('terminal.pasteHint'));

    withPrefs({ rightClickPaste: false });
    await tick();
    clipboard.readText.mockClear();
    // The menu of the webview stays.
    expect(await fireEvent.contextMenu(body)).toBe(true);
    expect(clipboard.readText).not.toHaveBeenCalled();
  });

  it('pastes only text, from a right click and from the paste of the webview', async () => {
    const { term, body } = await mount();
    const sent = () =>
      h.writeTerminal.mock.calls.flatMap(([, data]) => Array.from(data as Uint8Array));

    clipboard.readText.mockResolvedValueOnce('a\x1b[201~b\x9b\x00\x7f\tc\r\n');
    await fireEvent.contextMenu(body);
    await vi.waitFor(() => expect(term.paste).toHaveBeenCalledWith('a[201~b\tc\r\n'));

    const clipboardData = {
      getData: (type: string) => (type === 'text/plain' ? 'x\x1b[201~y\r' : ''),
    };
    expect(await fireEvent.paste(term.textarea!, { clipboardData })).toBe(false);
    expect(term.paste).toHaveBeenLastCalledWith('x[201~y\r');
    expect(term.ownPaste).not.toHaveBeenCalled();
    expect(sent()).not.toContain(0x1b);
    expect(sent()).not.toContain(0x9b);

    // Nothing left to paste: nothing goes to the program.
    term.paste.mockClear();
    await fireEvent.paste(term.textarea!, { clipboardData: { getData: () => '\x1b\x03' } });
    expect(term.paste).not.toHaveBeenCalled();
  });

  it('asks before pasting several lines when the option is on, and only then', async () => {
    const { term, body } = await mount();
    const multi = { getData: () => 'cd /tmp\nrm -rf x\n' };

    // Off by default: the lines go at once, without a question.
    await fireEvent.paste(term.textarea!, { clipboardData: multi });
    expect(term.paste).toHaveBeenLastCalledWith('cd /tmp\nrm -rf x\n');
    expect(screen.queryByRole('alertdialog')).toBeNull();

    withPrefs({ confirmMultilinePaste: true });
    await tick();
    term.paste.mockClear();

    // One line asks nothing.
    await fireEvent.paste(term.textarea!, { clipboardData: { getData: () => 'uptime' } });
    expect(term.paste).toHaveBeenLastCalledWith('uptime');
    expect(screen.queryByRole('alertdialog')).toBeNull();

    // Several lines wait for the answer, which has the focus on Cancel (xterm keeps Tab) and
    // names the count; Escape drops them, and so does Cancel.
    term.paste.mockClear();
    await fireEvent.paste(term.textarea!, { clipboardData: multi });
    expect(term.paste).not.toHaveBeenCalled();
    const first = await screen.findByRole('alertdialog', {
      name: tNow('terminal.pasteConfirm', { n: 2 }),
    });
    expect(document.activeElement).toBe(
      within(first).getByRole('button', { name: tNow('terminal.pasteConfirm.cancel') }),
    );
    await fireEvent.keyDown(first, { key: 'Escape' });
    expect(term.paste).not.toHaveBeenCalled();
    expect(screen.queryByRole('alertdialog')).toBeNull();

    await fireEvent.paste(term.textarea!, { clipboardData: multi });
    const ask = await screen.findByRole('alertdialog');
    await fireEvent.click(
      within(ask).getByRole('button', { name: tNow('terminal.pasteConfirm.cancel') }),
    );
    expect(term.paste).not.toHaveBeenCalled();
    expect(screen.queryByRole('alertdialog')).toBeNull();

    // A right click asks the same; paste sends the cleaned text.
    clipboard.readText.mockResolvedValueOnce('a\x1b\r\nb');
    await fireEvent.contextMenu(body);
    const again = await screen.findByRole('alertdialog');
    expect(term.paste).not.toHaveBeenCalled();
    await fireEvent.click(
      within(again).getByRole('button', { name: tNow('terminal.pasteConfirm.paste') }),
    );
    expect(term.paste).toHaveBeenCalledWith('a\r\nb');
    expect(screen.queryByRole('alertdialog')).toBeNull();
  });

  it('keeps Ctrl+Shift+C and Ctrl+Shift+V for itself and gives the program every other key', async () => {
    const { term } = await mount();
    const key = (type: string, init: KeyboardEventInit) =>
      term.keyHandler!(new KeyboardEvent(type, { cancelable: true, ...init }));

    term.selection = 'df -h';
    const copy = new KeyboardEvent('keydown', {
      key: 'C',
      ctrlKey: true,
      shiftKey: true,
      cancelable: true,
    });
    expect(term.keyHandler!(copy)).toBe(false);
    expect(copy.defaultPrevented).toBe(true);
    expect(clipboard.writeText).toHaveBeenCalledWith('df -h');

    clipboard.writeText.mockClear();
    expect(key('keyup', { key: 'C', ctrlKey: true, shiftKey: true })).toBe(false);
    expect(clipboard.writeText).not.toHaveBeenCalled();

    const paste = new KeyboardEvent('keydown', {
      key: 'V',
      ctrlKey: true,
      shiftKey: true,
      cancelable: true,
    });
    expect(term.keyHandler!(paste)).toBe(false);
    // The paste of the webview follows.
    expect(paste.defaultPrevented).toBe(false);

    expect(key('keydown', { key: 'c', ctrlKey: true })).toBe(true);
    expect(key('keydown', { key: 'v', ctrlKey: true })).toBe(true);
    expect(key('keydown', { key: 'a' })).toBe(true);
  });

  it('searches forward with Enter and back with Shift+Enter', async () => {
    const { term } = await mount();
    const field = screen.getByRole('searchbox', { name: tNow('terminal.search') });

    await fireEvent.keyDown(field, { key: 'Enter' });
    expect(h.findNext).not.toHaveBeenCalled();

    await fireEvent.input(field, { target: { value: 'error' } });
    await fireEvent.keyDown(field, { key: 'Enter' });
    expect(h.findNext).toHaveBeenCalledWith('error');
    await fireEvent.keyDown(field, { key: 'Enter', shiftKey: true });
    expect(h.findPrevious).toHaveBeenCalledWith('error');

    await fireEvent.click(screen.getByRole('button', { name: tNow('ui.clear') }));
    expect(term.clearSelection).toHaveBeenCalled();
  });

  it('offers to reconnect an ended session on an empty terminal', async () => {
    const { term, rerender } = await mount(session({ status: 'connected', connectedAt: 1 }));
    expect(screen.queryByText(tNow('terminal.ended'))).toBeNull();

    await rerender({ session: session({ status: 'disconnected', exitCode: 255 }) });
    expect(screen.getAllByText(tNow('terminal.status.exited', { code: 255 })).length).toBe(1);
    const ended = screen.getByText(tNow('terminal.ended')).parentElement as HTMLElement;
    await fireEvent.click(within(ended).getByRole('button', { name: tNow('terminal.reconnect') }));

    expect(term.reset).toHaveBeenCalled();
    expect(h.reconnectTerminal).toHaveBeenCalledWith(KEY);
    expect(term.reset.mock.invocationCallOrder[0]).toBeLessThan(
      h.reconnectTerminal.mock.invocationCallOrder[0],
    );

    await rerender({ session: session({ status: 'disconnected', exitCode: null }) });
    expect(screen.getAllByText(tNow('terminal.status.disconnected')).length).toBe(1);
  });

  it('ends the session with its button and opens the options panel', async () => {
    const { onClose } = await mount();

    await fireEvent.click(screen.getByRole('button', { name: tNow('terminal.close') }));
    expect(onClose).toHaveBeenCalledTimes(1);

    const toggle = screen.getByRole('button', { name: tNow('terminal.options') });
    expect(screen.queryByRole('complementary')).toBeNull();
    await fireEvent.click(toggle);
    expect(toggle.getAttribute('aria-pressed')).toBe('true');
    expect(screen.getByRole('complementary', { name: tNow('terminal.options') })).toBeTruthy();
  });

  it('opens the snippets in a panel that takes the place of the options', async () => {
    await mount(session({ status: 'connected', backendId: 1 }));
    const snippets = screen.getByRole('button', { name: tNow('terminal.snippets') });
    const options = screen.getByRole('button', { name: tNow('terminal.options') });

    await fireEvent.click(snippets);
    expect(snippets.getAttribute('aria-pressed')).toBe('true');
    const panel = screen.getByRole('complementary', { name: tNow('terminal.snippets') });
    await fireEvent.click(within(panel).getByText('$ df -h'));
    expect(h.runSnippet).toHaveBeenCalledWith(KEY, 'df -h');
    // The keys go back to the terminal.
    expect(h.FakeTerminal.last!.focus).toHaveBeenCalled();

    await fireEvent.click(options);
    expect(screen.queryByRole('complementary', { name: tNow('terminal.snippets') })).toBeNull();
    expect(screen.getByRole('complementary', { name: tNow('terminal.options') })).toBeTruthy();
    expect(snippets.getAttribute('aria-pressed')).toBe('false');

    await fireEvent.click(snippets);
    expect(screen.queryByRole('complementary', { name: tNow('terminal.options') })).toBeNull();
    await fireEvent.click(snippets);
    expect(screen.queryByRole('complementary')).toBeNull();
  });

  it('opens the files of the session in a panel that takes the place of the others', async () => {
    await mount(session({ status: 'connected', backendId: 4 }));
    const files = screen.getByRole('button', { name: tNow('terminal.files') });
    await fireEvent.click(screen.getByRole('button', { name: tNow('terminal.snippets') }));

    await fireEvent.click(files);
    expect(files.getAttribute('aria-pressed')).toBe('true');
    expect(screen.queryByRole('complementary', { name: tNow('terminal.snippets') })).toBeNull();
    expect(screen.getByRole('complementary', { name: tNow('terminal.files') })).toBeTruthy();
    await vi.waitFor(() => expect(h.sftpList).toHaveBeenCalledWith(4, '.'));

    await fireEvent.click(screen.getByRole('button', { name: tNow('terminal.options') }));
    expect(screen.queryByRole('complementary', { name: tNow('terminal.files') })).toBeNull();
    expect(files.getAttribute('aria-pressed')).toBe('false');
  });

  it('runs no snippet in a session that does not run', async () => {
    await mount(session({ status: 'disconnected', exitCode: 0 }));
    await fireEvent.click(screen.getByRole('button', { name: tNow('terminal.snippets') }));
    const card = screen.getByText('$ df -h').closest('button') as HTMLButtonElement;
    expect(card.disabled).toBe(true);
    await fireEvent.click(card);
    expect(h.runSnippet).not.toHaveBeenCalled();
  });

  it('warns in its foot while the broadcast is on', async () => {
    await mount();
    const warning = tNow('terminal.snippets.broadcastActive');
    expect(screen.queryByText(warning)).toBeNull();
    snippetBroadcast.set(true);
    await tick();
    expect(screen.getByText(warning).closest('footer')).toBeTruthy();
    snippetBroadcast.set(false);
    await tick();
    expect(screen.queryByText(warning)).toBeNull();
  });
});

describe('SshTerminal in a detached window (R-1070)', () => {
  async function mountDocked(s: TerminalSession) {
    const onDock = vi.fn();
    const view = render(SshTerminal, { session: s, onDock });
    await vi.waitFor(() => expect(h.FakeTerminal.last).not.toBeNull());
    await tick();
    return { ...view, onDock };
  }

  it('offers only to dock: no target, font, snippets, files, options, reconnect or close', async () => {
    const { onDock } = await mountDocked(session({ status: 'connected', connectedAt: null }));
    expect(screen.queryByText('ops@db.example:2222')).toBeNull();
    for (const name of [
      'fontSmaller',
      'fontLarger',
      'snippets',
      'files',
      'options',
      'reconnect',
      'close',
    ] as const) {
      expect(screen.queryByRole('button', { name: tNow(`terminal.${name}`) })).toBeNull();
    }
    // Taken over from the main window, it knows no time it connected.
    expect(screen.getAllByText(tNow('terminal.status.connected')).length).toBeGreaterThan(0);

    await fireEvent.click(screen.getByRole('button', { name: tNow('terminal.dock') }));
    expect(onDock).toHaveBeenCalledTimes(1);
  });

  it('offers to dock an ended session instead of reconnecting it', async () => {
    const { onDock } = await mountDocked(session({ status: 'disconnected', exitCode: 0 }));
    const ended = screen.getByText(tNow('terminal.ended')).parentElement as HTMLElement;
    expect(within(ended).queryByRole('button', { name: tNow('terminal.reconnect') })).toBeNull();
    await fireEvent.click(within(ended).getByRole('button', { name: tNow('terminal.dock') }));
    expect(onDock).toHaveBeenCalledTimes(1);
    expect(h.reconnectTerminal).not.toHaveBeenCalled();
  });

  it('warns in its foot while the broadcast is on, as main does', async () => {
    await mountDocked(session({ status: 'connected', connectedAt: null }));
    const warning = tNow('terminal.snippets.broadcastActive');
    expect(screen.queryByText(warning)).toBeNull();
    snippetBroadcast.set(true);
    await tick();
    expect(screen.getByText(warning).closest('footer')).toBeTruthy();
  });
});

describe('terminalTheme', () => {
  it('falls back to Cave for a scheme this version does not know', () => {
    expect(terminalTheme('neon')).toBe(terminalTheme('cave'));
    expect(terminalTheme('toString')).toBe(terminalTheme('cave'));
    expect(terminalTheme('light')).not.toBe(terminalTheme('cave'));
  });
});

describe('sanitizePaste', () => {
  it('keeps text, tabs and line breaks and drops the other control characters', () => {
    expect(sanitizePaste('ls -la\tü 🙂\r\n')).toBe('ls -la\tü 🙂\r\n');
    expect(sanitizePaste('\x00\x03\x08\x0b\x0c\x1b\x1f\x7f\x80\x9b\x9f')).toBe('');
    expect(sanitizePaste('\x1b[201~rm\x9b')).toBe('[201~rm');
    // The first characters past each range stay.
    expect(sanitizePaste('\x20\x7e\xa0')).toBe(' ~\xa0');
  });
});

describe('SshTerminal running a playbook (R-1073)', () => {
  const PLAYBOOK = { id: '', name: 'apt-upgrade', kind: 'ssh', tags: [] } as unknown as Connection;

  it('names the playbook and its dry run and offers no reconnect', async () => {
    await mount(
      session({
        connection: PLAYBOOK,
        resolved: PLAYBOOK,
        status: 'disconnected',
        exitCode: 0,
        ansible: { check: true },
      }),
    );
    expect(screen.getByText('apt-upgrade --check')).toBeTruthy();
    expect(screen.queryByRole('button', { name: tNow('terminal.reconnect') })).toBeNull();
    expect(screen.getByText(tNow('terminal.ended'))).toBeTruthy();
    expect(screen.getByRole('button', { name: tNow('terminal.close') })).toBeTruthy();
  });

  it('names the playbook alone without a dry run', async () => {
    await mount(session({ connection: PLAYBOOK, resolved: PLAYBOOK, ansible: { check: false } }));
    expect(screen.getByText('apt-upgrade')).toBeTruthy();
  });

  it('takes no snippets nor files and does not warn of a broadcast it does not get', async () => {
    snippetBroadcast.set(true);
    await mount(
      session({
        connection: PLAYBOOK,
        resolved: PLAYBOOK,
        status: 'connected',
        ansible: { check: false },
      }),
    );
    expect(screen.queryByRole('button', { name: tNow('terminal.snippets') })).toBeNull();
    expect(screen.queryByRole('button', { name: tNow('terminal.files') })).toBeNull();
    expect(screen.queryByText(tNow('terminal.snippets.broadcastActive'))).toBeNull();
  });
});

describe('SshTerminal prompting for a monitoring credential (arch-monitoring-ui)', () => {
  it('names its host but takes no snippets nor files and does not warn of a broadcast', async () => {
    snippetBroadcast.set(true);
    await mount(session({ status: 'connected', credential: { ref: 'pve-api' } }));
    // The prompt runs on the host, so the target stays; anything else typed would land in the secret.
    expect(screen.getByText('ops@db.example:2222')).toBeTruthy();
    expect(screen.queryByRole('button', { name: tNow('terminal.snippets') })).toBeNull();
    expect(screen.queryByRole('button', { name: tNow('terminal.files') })).toBeNull();
    expect(screen.queryByText(tNow('terminal.snippets.broadcastActive'))).toBeNull();
  });
});
