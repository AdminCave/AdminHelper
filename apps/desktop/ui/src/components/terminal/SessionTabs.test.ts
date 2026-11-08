// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// The tab bar of the embedded terminal (R-1069): only with a session, the page first, then each
// session with its name and status; a click or the arrow keys bring a tab to the front, the cross
// and Delete close a session. A running session detaches by its button, a double click or a
// pull downwards (R-1070); its tab stays in italics, and a click brings its window forward. An
// RDP tab (R-1098) has its own icon and stays in the window.

import { describe, it, expect, beforeAll, afterEach, vi } from 'vitest';
import { render, cleanup, screen, fireEvent } from '@testing-library/svelte';
import type { Connection } from '$lib/bridge/types';
import { setLanguage, tNow } from '$lib/i18n';
import { PAGE_TAB, type TerminalSession, type TerminalStatus } from '$lib/stores/terminals';
import SessionTabs from './SessionTabs.svelte';

function session(
  key: string,
  name: string,
  status: TerminalStatus,
  more: Partial<TerminalSession> = {},
): TerminalSession {
  const connection = { id: key, name, kind: 'ssh', host: `${name}.example` } as Connection;
  return {
    key,
    connection,
    resolved: connection,
    status,
    exitCode: null,
    connectedAt: null,
    backendId: null,
    ...more,
  };
}

const WEB = session('terminal-1', 'web', 'connected');
const DB = session('terminal-2', 'db', 'connecting');
const OLD = session('terminal-3', 'old', 'disconnected');

function setup(active: string, sessions = [WEB, DB, OLD]) {
  const onSelect = vi.fn();
  const onClose = vi.fn();
  const onDetach = vi.fn();
  render(SessionTabs, { sessions, active, pageLabel: 'Connections', onSelect, onClose, onDetach });
  return { onSelect, onClose, onDetach };
}

const tabs = () => screen.queryAllByRole('tab');

beforeAll(() => setLanguage('en'));
afterEach(() => cleanup());

describe('SessionTabs', () => {
  it('shows nothing without a session', () => {
    setup(PAGE_TAB, []);
    expect(screen.queryByRole('tablist')).toBeNull();
  });

  it('shows the page first, then each session with its name and status', () => {
    setup(DB.key);
    expect(screen.getByRole('tablist').getAttribute('aria-label')).toBe(tNow('terminal.tabs'));
    expect(tabs().map((t) => t.textContent?.trim())).toEqual(['Connections', 'web', 'db', 'old']);
    expect(tabs().map((t) => t.getAttribute('aria-selected'))).toEqual([
      'false',
      'false',
      'true',
      'false',
    ]);
    // Only the tab in front is in the tab order.
    expect(tabs().map((t) => t.tabIndex)).toEqual([-1, -1, 0, -1]);
    expect(
      tabs()
        .slice(1)
        .map((t) => t.querySelector('[role="img"]')?.getAttribute('aria-label')),
    ).toEqual([
      tNow('terminal.status.connected'),
      tNow('terminal.status.connecting'),
      tNow('terminal.status.disconnected'),
    ]);
  });

  it('brings the tab clicked to the front', async () => {
    const { onSelect } = setup(PAGE_TAB);
    await fireEvent.click(screen.getByRole('tab', { name: /db/ }));
    await fireEvent.click(screen.getByRole('tab', { name: 'Connections' }));
    expect(onSelect.mock.calls).toEqual([[DB.key], [PAGE_TAB]]);
  });

  it('closes a session with its cross, which brings no tab to the front', async () => {
    const { onSelect, onClose } = setup(PAGE_TAB);
    const cross = screen.getByRole('button', { name: tNow('terminal.tabs.close', { name: 'db' }) });
    expect(cross.tabIndex).toBe(-1);
    await fireEvent.click(cross);
    expect(onClose).toHaveBeenCalledExactlyOnceWith(DB);
    expect(onSelect).not.toHaveBeenCalled();
  });

  it('moves with the arrow keys, Home and End, focus and selection together', async () => {
    const { onSelect } = setup(PAGE_TAB);
    const [page, web, , old] = tabs();
    await fireEvent.keyDown(page, { key: 'ArrowRight' });
    expect(onSelect).toHaveBeenLastCalledWith(WEB.key);
    expect(document.activeElement).toBe(web);
    await fireEvent.keyDown(web, { key: 'End' });
    expect(onSelect).toHaveBeenLastCalledWith(OLD.key);
    expect(document.activeElement).toBe(old);
    await fireEvent.keyDown(old, { key: 'ArrowRight' });
    expect(onSelect).toHaveBeenLastCalledWith(PAGE_TAB);
    expect(document.activeElement).toBe(page);
    await fireEvent.keyDown(page, { key: 'ArrowLeft' });
    expect(onSelect).toHaveBeenLastCalledWith(OLD.key);
  });

  it('closes the session with Delete; the page has nothing to close', async () => {
    const { onSelect, onClose } = setup(WEB.key);
    const [page, web] = tabs();
    await fireEvent.keyDown(page, { key: 'Delete' });
    expect(onClose).not.toHaveBeenCalled();
    await fireEvent.keyDown(web, { key: 'Delete' });
    expect(onClose).toHaveBeenCalledExactlyOnceWith(WEB);
    expect(onSelect).not.toHaveBeenCalled();
  });

  describe('detach (R-1070)', () => {
    const RUN = session('terminal-4', 'run', 'connected', { backendId: 4 });
    const AWAY = session('terminal-5', 'away', 'connected', { backendId: 5, detached: true });
    const detachButton = (name: string) =>
      screen.queryByRole('button', { name: tNow('terminal.tabs.detach', { name }) });

    it('offers its button only on a running session, and it brings no tab to the front', async () => {
      const { onSelect, onDetach } = setup(PAGE_TAB, [WEB, OLD, RUN, AWAY]);
      // Not started yet, ended, or detached already: nothing to detach.
      expect(detachButton('web')).toBeNull();
      expect(detachButton('old')).toBeNull();
      expect(detachButton('away')).toBeNull();
      await fireEvent.click(detachButton('run')!);
      expect(onDetach).toHaveBeenCalledExactlyOnceWith(RUN);
      expect(onSelect).not.toHaveBeenCalled();
    });

    it('offers no window for an RDP session, by button or double click, and marks its tab', async () => {
      const RDP = session('terminal-6', 'win', 'connected', {
        rdp: {
          sessionId: 's1',
          wsPort: 7001,
          token: 't1',
          phase: 'connected',
          code: null,
          certificate: null,
          performance: null,
          notice: null,
        },
      });
      const { onDetach } = setup(PAGE_TAB, [RUN, RDP]);
      expect(detachButton('win')).toBeNull();
      await fireEvent.dblClick(screen.getByRole('tab', { name: /win/ }));
      expect(onDetach).not.toHaveBeenCalled();
      expect(
        screen.getByRole('tab', { name: /win/ }).querySelector('.lucide-monitor'),
      ).not.toBeNull();
      expect(screen.getByRole('tab', { name: /run/ }).querySelector('.lucide-monitor')).toBeNull();
    });

    it('detaches with a double click', async () => {
      const { onDetach } = setup(PAGE_TAB, [WEB, RUN]);
      await fireEvent.dblClick(screen.getByRole('tab', { name: /web/ }));
      expect(onDetach).not.toHaveBeenCalled();
      await fireEvent.dblClick(screen.getByRole('tab', { name: /run/ }));
      expect(onDetach).toHaveBeenCalledExactlyOnceWith(RUN);
    });

    it('detaches when pulled 46 px down, and the click that ends the pull selects nothing', async () => {
      const { onSelect, onDetach } = setup(PAGE_TAB, [RUN]);
      const tab = screen.getByRole('tab', { name: /run/ });
      await fireEvent.pointerDown(tab, { button: 0, pointerId: 1, clientY: 10 });
      await fireEvent.pointerMove(tab, { pointerId: 1, clientY: 55 });
      expect(onDetach).not.toHaveBeenCalled();
      await fireEvent.pointerMove(tab, { pointerId: 1, clientY: 56 });
      await fireEvent.pointerMove(tab, { pointerId: 1, clientY: 90 });
      expect(onDetach).toHaveBeenCalledExactlyOnceWith(RUN);
      await fireEvent.pointerUp(tab, { pointerId: 1 });
      await fireEvent.click(tab);
      expect(onSelect).not.toHaveBeenCalled();

      // Let go before the mark: a plain click, nothing detached.
      await fireEvent.pointerDown(tab, { button: 0, pointerId: 2, clientY: 10 });
      await fireEvent.pointerMove(tab, { pointerId: 2, clientY: 40 });
      await fireEvent.pointerUp(tab, { pointerId: 2 });
      await fireEvent.click(tab);
      expect(onDetach).toHaveBeenCalledTimes(1);
      expect(onSelect).toHaveBeenCalledExactlyOnceWith(RUN.key);
    });

    it('shows a detached tab in italics; a click brings its window, the arrows pass over it', async () => {
      const { onSelect, onDetach } = setup(PAGE_TAB, [AWAY, RUN]);
      const [page, away] = tabs();
      expect(away.getAttribute('title')).toBe(tNow('terminal.tabs.detached'));
      expect(away.closest('.detached')).not.toBeNull();
      expect(tabs()[2].closest('.detached')).toBeNull();
      await fireEvent.click(away);
      expect(onDetach).toHaveBeenCalledExactlyOnceWith(AWAY);
      expect(onSelect).not.toHaveBeenCalled();
      await fireEvent.keyDown(page, { key: 'ArrowRight' });
      expect(document.activeElement).toBe(away);
      expect(onSelect).not.toHaveBeenCalled();
      expect(onDetach).toHaveBeenCalledTimes(1);
    });
  });
});
