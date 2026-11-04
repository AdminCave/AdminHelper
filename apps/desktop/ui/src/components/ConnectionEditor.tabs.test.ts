// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// The connection editor groups its fields in tabs (R-1066): a type switch on top, General and
// Sign-in for SSH and RDP, Web without a tab bar. In server mode General offers "Assign server",
// which saves the connection's serverId.

import { describe, it, expect, vi, beforeAll, beforeEach, afterEach } from 'vitest';
import { render, cleanup, fireEvent } from '@testing-library/svelte';
import { tick } from 'svelte';
import { writable } from 'svelte/store';
import { setLanguage } from '$lib/i18n';

const h = vi.hoisted(() => ({
  upsert: vi.fn(async () => {}),
  list: vi.fn(async (): Promise<{ id: string; name: string }[]> => []),
}));

vi.mock('$lib/bridge', () => ({}));
vi.mock('$lib/stores/connections', () => ({ upsert: h.upsert, remove: vi.fn() }));
vi.mock('$lib/stores/connectFlow', () => ({ initiateConnect: vi.fn() }));
vi.mock('$lib/stores/session', async () => {
  const { writable, get } = await import('svelte/store');
  const session = writable(null);
  return { settings: writable(null), session, currentSession: () => get(session) };
});
// The real infra store: only the API call is stubbed, so the test sees every load it triggers.
vi.mock('$lib/api/servers', () => ({ serversApi: { list: h.list } }));

import { emptyConnection } from '$lib/models/connection';
import type { Connection } from '$lib/bridge/types';
import { openEditor, closeEditor } from '$lib/stores/editor';
import * as sessionStores from '$lib/stores/session';
import { loadServers } from '$lib/stores/infra';
import ConnectionEditor from './ConnectionEditor.svelte';

type W<T> = ReturnType<typeof writable<T>>;
const settings = sessionStores.settings as unknown as W<{ mode: string } | null>;
const session = sessionStores.session as unknown as W<{
  username: string;
  isAdmin: boolean;
} | null>;

async function seedServers(list: { id: string; name: string }[]): Promise<void> {
  h.list.mockResolvedValueOnce(list);
  await loadServers();
  h.list.mockClear();
}

function serverMode(isAdmin = true): void {
  settings.set({ mode: 'server' });
  session.set({ username: isAdmin ? 'admin' : 'alice', isAdmin });
}

async function open(conn: Connection): Promise<HTMLElement> {
  openEditor(conn);
  const { container } = render(ConnectionEditor);
  await tick();
  return container;
}

const tabIds = (c: HTMLElement): string[] =>
  [...c.querySelectorAll<HTMLElement>('[role="tab"]')].map((t) => t.dataset.tab ?? '');

function selectTab(c: HTMLElement, id: string): Promise<boolean> {
  return fireEvent.click(c.querySelector<HTMLElement>(`[role="tab"][data-tab="${id}"]`)!);
}

function selectKind(c: HTMLElement, label: string): Promise<boolean> {
  const opt = [...c.querySelectorAll<HTMLElement>('[role="radio"]')].find(
    (b) => b.textContent?.trim() === label,
  );
  return fireEvent.click(opt!);
}

beforeAll(() => setLanguage('en'));

beforeEach(async () => {
  settings.set(null);
  session.set({ username: 'admin', isAdmin: true });
  await seedServers([]);
  session.set(null);
  h.list.mockReset();
  h.list.mockResolvedValue([]);
  h.upsert.mockClear();
});

afterEach(() => {
  cleanup();
  closeEditor();
});

describe('ConnectionEditor tabs', () => {
  it('shows General and Sign-in for SSH, with the key path on Sign-in only', async () => {
    const c = await open({ ...emptyConnection('ssh'), name: 'web01', host: 'web01.lan' });
    expect(tabIds(c)).toEqual(['general', 'auth']);
    expect(c.querySelector('[role="tab"][aria-selected="true"]')?.getAttribute('data-tab')).toBe(
      'general',
    );
    // The first two text inputs stay name and host (the live E2E specs rely on it).
    const texts = c.querySelectorAll<HTMLInputElement>('.editor-overlay input[type="text"]');
    expect(texts[0].name).toBe('name');
    expect(texts[1].name).toBe('host');
    expect(c.textContent).not.toContain('Key path');

    await selectTab(c, 'auth');
    expect(c.querySelector('input[name="host"]')).toBeNull();
    expect(c.textContent).toContain('Key path');
  });

  it('puts the domain on General and certificate trust on Sign-in for RDP', async () => {
    const c = await open({ ...emptyConnection('rdp'), name: 'dc01', host: 'dc01.lan' });
    expect(tabIds(c)).toEqual(['general', 'auth']);
    expect(c.textContent).toContain('Domain');
    expect(c.querySelector('input[type="checkbox"]')).toBeNull();

    await selectTab(c, 'auth');
    expect(c.querySelector('input[type="checkbox"]')).not.toBeNull();
  });

  it('hides the tab bar for Web and shows the URL', async () => {
    const c = await open({ ...emptyConnection('web'), name: 'pve' });
    expect(c.querySelector('[role="tablist"]')).toBeNull();
    expect(c.querySelector('input[type="url"]')).not.toBeNull();
    expect(c.querySelector('input[name="host"]')).toBeNull();
  });

  it('returns to General when the type changes', async () => {
    const c = await open({ ...emptyConnection('ssh'), name: 'web01' });
    await selectTab(c, 'auth');
    expect(c.querySelector('input[name="name"]')).toBeNull();

    await selectKind(c, 'RDP');
    expect(c.querySelector('[role="tab"][aria-selected="true"]')?.getAttribute('data-tab')).toBe(
      'general',
    );
    expect(c.querySelector('input[name="name"]')).not.toBeNull();
    expect(c.textContent).toContain('Domain');
  });
});

describe('ConnectionEditor assign server', () => {
  it('offers no server field outside server mode', async () => {
    const c = await open({ ...emptyConnection('ssh'), name: 'web01' });
    expect(c.querySelector('select[name="serverId"]')).toBeNull();
    expect(h.list).not.toHaveBeenCalled();
  });

  it('offers no server field to a non-admin and does not ask the server', async () => {
    // GET /api/servers is admin-only: a non-admin would get a 403 on every opening.
    serverMode(false);
    const c = await open({ ...emptyConnection('ssh'), name: 'web01', serverId: 's1' });
    for (let i = 0; i < 5; i++) await new Promise((r) => setTimeout(r, 0));
    expect(c.querySelector('select[name="serverId"]')).toBeNull();
    expect(h.list).not.toHaveBeenCalled();
  });

  it('loads the servers and saves the chosen serverId in server mode', async () => {
    serverMode();
    h.list.mockResolvedValueOnce([
      { id: 's1', name: 'mail-01' },
      { id: 's2', name: 'db-01' },
    ]);
    const c = await open({ ...emptyConnection('ssh'), name: 'web01', host: 'web01.lan' });
    await vi.waitFor(() =>
      expect(c.querySelectorAll('select[name="serverId"] option')).toHaveLength(3),
    );
    expect(h.list).toHaveBeenCalledTimes(1);
    const select = c.querySelector<HTMLSelectElement>('select[name="serverId"]')!;
    expect([...select.options].map((o) => o.textContent?.trim())).toEqual([
      'No server',
      'mail-01',
      'db-01',
    ]);
    expect(select.value).toBe('');

    select.value = 's2';
    await fireEvent.change(select);
    await fireEvent.click(c.querySelector<HTMLElement>('.btn.save')!);
    expect(h.upsert).toHaveBeenCalledTimes(1);
    expect((h.upsert.mock.calls[0] as unknown as [Connection])[0].serverId).toBe('s2');
  });

  it('keeps an unknown server and clears it with No server', async () => {
    serverMode();
    await seedServers([{ id: 's1', name: 'mail-01' }]);
    const c = await open({
      ...emptyConnection('ssh'),
      name: 'web01',
      host: 'web01.lan',
      serverId: 'gone',
    });
    expect(h.list).not.toHaveBeenCalled();

    const select = c.querySelector<HTMLSelectElement>('select[name="serverId"]')!;
    expect(select.value).toBe('gone');
    expect(select.selectedOptions[0].textContent?.trim()).toBe('Unknown server');

    select.value = '';
    await fireEvent.change(select);
    await fireEvent.click(c.querySelector<HTMLElement>('.btn.save')!);
    expect((h.upsert.mock.calls[0] as unknown as [Connection])[0].serverId).toBeNull();
  });

  it.each([
    ['answers with no servers', () => h.list.mockResolvedValue([])],
    ['fails', () => h.list.mockRejectedValue(new Error('down'))],
  ])('asks the server once per opening when it %s', async (_name, arrange) => {
    arrange();
    serverMode();
    const c = await open({ ...emptyConnection('ssh'), name: 'web01' });
    for (let i = 0; i < 5; i++) await new Promise((r) => setTimeout(r, 0));
    expect(h.list).toHaveBeenCalledTimes(1);
    expect(c.querySelectorAll('select[name="serverId"] option')).toHaveLength(1);
  });
});
