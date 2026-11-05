// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// The tab bar of the embedded terminal (R-1069): only with a session, the page first, then each
// session with its name and status; a click or the arrow keys bring a tab to the front, the cross
// and Delete close a session.

import { describe, it, expect, beforeAll, afterEach, vi } from 'vitest';
import { render, cleanup, screen, fireEvent } from '@testing-library/svelte';
import type { Connection } from '$lib/bridge/types';
import { setLanguage, tNow } from '$lib/i18n';
import { PAGE_TAB, type TerminalSession, type TerminalStatus } from '$lib/stores/terminals';
import SessionTabs from './SessionTabs.svelte';

function session(key: string, name: string, status: TerminalStatus): TerminalSession {
  const connection = { id: key, name, kind: 'ssh', host: `${name}.example` } as Connection;
  return {
    key,
    connection,
    resolved: connection,
    status,
    exitCode: null,
    connectedAt: null,
    backendId: null,
  };
}

const WEB = session('terminal-1', 'web', 'connected');
const DB = session('terminal-2', 'db', 'connecting');
const OLD = session('terminal-3', 'old', 'disconnected');

function setup(active: string, sessions = [WEB, DB, OLD]) {
  const onSelect = vi.fn();
  const onClose = vi.fn();
  render(SessionTabs, { sessions, active, pageLabel: 'Connections', onSelect, onClose });
  return { onSelect, onClose };
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
});
