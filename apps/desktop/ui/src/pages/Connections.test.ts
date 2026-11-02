// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// The connections page (R-1065, R-1067): library, kind and folder filters, search, chips, sorting,
// grouping, table and cards, selection, keyboard, inspector, favorites, quick access and the
// reachability column.

import { describe, it, expect, vi, beforeAll, beforeEach, afterEach } from 'vitest';
import { render, cleanup, screen, fireEvent, waitFor, within } from '@testing-library/svelte';
import { get } from 'svelte/store';
import type { Connection } from '$lib/bridge/types';

const h = vi.hoisted(() => ({
  items: [] as unknown[],
  probe: vi.fn(async (targets: unknown[]) => targets.map(() => null as number | null)),
  connect: vi.fn(async () => {}),
  edit: vi.fn(),
  setFavorites: vi.fn(),
  stop: vi.fn(),
  visible: null as null | (() => { conns: readonly unknown[]; tunneled: ReadonlySet<string> }),
}));

vi.mock('$lib/bridge', () => ({
  fetchConnectionsJwt: vi.fn(async () => h.items),
  syncConnections: vi.fn(async () => []),
  loadConnections: vi.fn(async () => []),
  saveConnections: vi.fn(async () => {}),
  probeTargets: h.probe,
}));
vi.mock('$lib/stores/session', async () => {
  const { writable } = await import('svelte/store');
  const sessionStore = writable({
    settings: {
      mode: 'server',
      url: null,
      allowSelfSignedCerts: false,
      favoriteConnections: ['b'],
    },
    session: { serverUrl: 'https://srv.example', username: 'alice', isAdmin: false },
  });
  h.setFavorites.mockImplementation(async (ids: string[]) => {
    sessionStore.update((s) => ({ ...s, settings: { ...s.settings, favoriteConnections: ids } }));
  });
  return { sessionStore, setFavoriteConnections: h.setFavorites };
});
vi.mock('$lib/stores/connectFlow', () => ({ initiateConnect: h.connect }));
vi.mock('$lib/stores/editor', () => ({ openEditor: h.edit }));
vi.mock('$lib/stores/connections', async (orig) => ({
  ...(await orig<typeof import('$lib/stores/connections')>()),
  startReachability: (visible: NonNullable<typeof h.visible>) => {
    h.visible = visible;
    return h.stop;
  },
}));

import { setLanguage, tNow } from '$lib/i18n';
import { clearInMemory, probeVisible, reachability, searchTerm } from '$lib/stores/connections';
import Connections from './Connections.svelte';

const HOUR = 60 * 60 * 1000;
const ago = (ms: number) => new Date(Date.now() - ms).toISOString();

function conn(over: Partial<Connection> & Pick<Connection, 'id' | 'name' | 'kind'>): Connection {
  return {
    host: null,
    port: null,
    username: null,
    domain: null,
    keyPath: null,
    url: null,
    notes: null,
    tags: [],
    trustCert: false,
    lastUsed: null,
    serverId: null,
    ...over,
  };
}

const A = conn({
  id: 'a',
  name: 'web01',
  kind: 'ssh',
  host: 'web01.example',
  tags: ['prod'],
  lastUsed: ago(HOUR),
});
const B = conn({ id: 'b', name: 'db01', kind: 'rdp', host: 'db01.example' });
const C = conn({
  id: 'c',
  name: 'portal',
  kind: 'web',
  url: 'https://portal.example',
  tags: ['prod'],
  lastUsed: ago(2 * HOUR),
});

function names(): string[] {
  return screen
    .getAllByTestId('conn-row')
    .map((r) => r.querySelector('.conn-name')?.textContent ?? '');
}

function counter(): string {
  return screen.getByTestId('conn-counter').textContent ?? '';
}

function rail() {
  return within(screen.getByRole('navigation', { name: tNow('connections.library') }));
}

async function renderPage(items: Connection[] = [A, B, C]) {
  h.items = items;
  render(Connections);
  await waitFor(() => expect(screen.getAllByTestId('conn-row').length).toBeGreaterThan(0));
}

async function selectGrouping(value: string) {
  const select = screen.getByRole('combobox');
  await fireEvent.change(select, { target: { value } });
}

beforeAll(() => {
  setLanguage('en');
});

beforeEach(() => {
  vi.clearAllMocks();
  h.visible = null;
  clearInMemory();
  searchTerm.set('');
});

afterEach(() => {
  cleanup();
});

describe('Connections page', () => {
  it('lists every connection, most recently used first, and counts them', async () => {
    await renderPage();
    await selectGrouping('none');
    expect(names()).toEqual(['web01', 'portal', 'db01']);
    expect(counter()).toBe(tNow('connections.count', { shown: 3, total: 3 }));
  });

  it('groups by server by default and folds a group away', async () => {
    await renderPage();
    const heads = screen.getAllByRole('button', { expanded: true });
    const db = heads.find((b) => b.textContent?.includes('db01.example'));
    expect(db).toBeDefined();
    await fireEvent.click(db!);
    expect(names()).not.toContain('db01');
    expect(db!.getAttribute('aria-expanded')).toBe('false');
  });

  it('groups by folder with a group for connections without one', async () => {
    await renderPage();
    await selectGrouping('tag');
    const groups = screen.getAllByTestId('conn-group').map((g) => g.textContent ?? '');
    expect(groups[0]).toContain('prod');
    expect(groups[1]).toContain(tNow('connections.group.noTag'));
  });

  it('filters by the search term, shows it as a chip and resets', async () => {
    await renderPage();
    searchTerm.set('portal');
    await waitFor(() => expect(names()).toEqual(['portal']));
    expect(counter()).toBe(tNow('connections.count', { shown: 1, total: 3 }));
    expect(screen.getByText(tNow('connections.chip.search', { q: 'portal' }))).not.toBeNull();

    await fireEvent.click(screen.getByRole('button', { name: tNow('connections.reset') }));
    await waitFor(() => expect(names()).toHaveLength(3));
    expect(get(searchTerm)).toBe('');
  });

  it('filters by library, kind and folder from the rail', async () => {
    await renderPage();
    await fireEvent.click(rail().getByRole('button', { name: /Favorites/ }));
    expect(names()).toEqual(['db01']);
    await fireEvent.click(rail().getByRole('button', { name: /All/ }));

    await fireEvent.click(rail().getByRole('button', { name: /SSH/ }));
    expect(names()).toEqual(['web01']);
    expect(screen.getByText(tNow('connections.chip.kind', { kind: 'SSH' }))).not.toBeNull();
    await fireEvent.click(rail().getByRole('button', { name: /SSH/ }));
    expect(names()).toHaveLength(3);

    await fireEvent.click(rail().getByRole('button', { name: /prod/ }));
    expect(names().sort()).toEqual(['portal', 'web01']);
  });

  it('shows the empty state when nothing matches and its button resets the filters', async () => {
    await renderPage();
    searchTerm.set('nothing-matches');
    expect(await screen.findByText(tNow('connections.noResults'))).not.toBeNull();
    await fireEvent.click(screen.getByRole('button', { name: tNow('connections.resetFilters') }));
    await waitFor(() => expect(names()).toHaveLength(3));
  });

  it('sorts by name and turns the direction on the second click', async () => {
    await renderPage();
    await selectGrouping('none');
    const head = screen.getByRole('button', { name: tNow('connections.col.name') });
    await fireEvent.click(head);
    expect(names()).toEqual(['db01', 'portal', 'web01']);
    expect(head.getAttribute('data-sort')).toBe('asc');
    await fireEvent.click(head);
    expect(names()).toEqual(['web01', 'portal', 'db01']);
  });

  it('selects a row on click and connects on double click or Enter', async () => {
    await renderPage();
    const row = screen.getAllByTestId('conn-row').find((r) => r.textContent?.includes('db01'))!;
    await fireEvent.click(row);
    expect(row.getAttribute('aria-selected')).toBe('true');
    expect(h.connect).not.toHaveBeenCalled();

    await fireEvent.dblClick(row);
    expect(h.connect).toHaveBeenCalledWith(B);
    await fireEvent.keyDown(row, { key: 'Enter' });
    expect(h.connect).toHaveBeenCalledTimes(2);
  });

  it('edits and stars a connection without connecting it', async () => {
    await renderPage();
    const row = screen.getAllByTestId('conn-row').find((r) => r.textContent?.includes('web01'))!;
    await fireEvent.click(within(row).getByRole('button', { name: tNow('action.edit') }));
    expect(h.edit).toHaveBeenCalledWith(A);

    await fireEvent.click(
      within(row).getByRole('button', { name: tNow('connections.favorite.add') }),
    );
    await waitFor(() => expect(h.setFavorites).toHaveBeenCalledWith(['b', 'a']));
    expect(h.connect).not.toHaveBeenCalled();
    expect(row.getAttribute('aria-selected')).toBe('false');
  });

  it('opens web connections with "Open" and connects the others', async () => {
    await renderPage();
    const web = screen.getAllByTestId('conn-row').find((r) => r.textContent?.includes('portal'))!;
    await fireEvent.click(within(web).getByRole('button', { name: tNow('connections.open') }));
    expect(h.connect).toHaveBeenCalledWith(C);
  });

  it('shows cards in the card view', async () => {
    await renderPage();
    await fireEvent.click(screen.getByRole('radio', { name: tNow('connections.view.cards') }));
    const rows = screen.getAllByTestId('conn-row');
    expect(rows).toHaveLength(3);
    expect(rows.every((r) => r.classList.contains('conn-card'))).toBe(true);
  });

  it('puts favorites and recently used connections in quick access while nothing is filtered', async () => {
    await renderPage();
    const quick = within(screen.getByTestId('quick-access'));
    expect(quick.getByText('db01')).not.toBeNull();
    expect(quick.getByText('web01')).not.toBeNull();
    searchTerm.set('db');
    await waitFor(() => expect(screen.queryByTestId('quick-access')).toBeNull());
  });

  it('probes the shown connections and shows latency and unreachable targets', async () => {
    await renderPage();
    expect(h.visible).not.toBeNull();
    const v = h.visible!();
    expect(v.conns.map((c) => (c as Connection).id).sort()).toEqual(['a', 'b', 'c']);

    h.probe.mockImplementationOnce(async (targets: unknown[]) =>
      (targets as { host: string }[]).map((t) =>
        t.host === 'web01.example' ? 12 : t.host === 'db01.example' ? null : 40,
      ),
    );
    await probeVisible(v.conns as Connection[], v.tunneled);
    expect(get(reachability)).toMatchObject({ a: 12, b: null, c: 40 });
    const ping = (name: string) =>
      within(screen.getAllByTestId('conn-row').find((r) => r.textContent?.includes(name))!)
        .getByTestId('conn-ping')
        .textContent?.trim();
    await waitFor(() => expect(ping('web01')).toBe(tNow('connections.ping.ms', { ms: 12 })));
    expect(ping('db01')).toBe(tNow('connections.ping.down'));
  });

  it('shows the selected connection in the inspector', async () => {
    await renderPage();
    const insp = within(screen.getByTestId('conn-inspector'));
    expect(insp.getByText(tNow('connections.insp.empty'))).not.toBeNull();
    const row = screen.getAllByTestId('conn-row').find((r) => r.textContent?.includes('db01'))!;
    await fireEvent.click(row);
    expect(insp.getByText('db01')).not.toBeNull();
    expect(insp.getByText(/^xfreerdp \/v:db01\.example:3389/)).not.toBeNull();
  });

  it('walks the rows with the arrow keys, connects with Enter and clears with Escape', async () => {
    await renderPage();
    await selectGrouping('none');
    const list = screen.getByRole('listbox');
    const selected = () =>
      screen
        .getAllByTestId('conn-row')
        .filter((r) => r.getAttribute('aria-selected') === 'true')
        .map((r) => r.querySelector('.conn-name')?.textContent);

    await fireEvent.keyDown(list, { key: 'ArrowDown' });
    expect(selected()).toEqual(['web01']);
    await fireEvent.keyDown(document.activeElement!, { key: 'ArrowDown' });
    expect(selected()).toEqual(['portal']);
    expect(document.activeElement?.textContent).toContain('portal');
    await fireEvent.keyDown(document.activeElement!, { key: 'ArrowDown' });
    await fireEvent.keyDown(document.activeElement!, { key: 'ArrowDown' });
    expect(selected()).toEqual(['db01']);
    await fireEvent.keyDown(document.activeElement!, { key: 'ArrowUp' });
    expect(selected()).toEqual(['portal']);

    await fireEvent.keyDown(document.activeElement!, { key: 'Enter' });
    expect(h.connect).toHaveBeenCalledWith(C);

    await fireEvent.keyDown(document.activeElement!, { key: 'Escape' });
    expect(selected()).toEqual([]);
    expect(
      within(screen.getByTestId('conn-inspector')).getByText(tNow('connections.insp.empty')),
    ).not.toBeNull();
  });

  it('skips the rows of a folded group', async () => {
    await renderPage();
    const heads = screen.getAllByRole('button', { expanded: true });
    await fireEvent.click(heads.find((b) => b.textContent?.includes('db01.example'))!);
    const list = screen.getByRole('listbox');
    for (let i = 0; i < 4; i++) await fireEvent.keyDown(list, { key: 'ArrowDown' });
    const sel = screen
      .getAllByTestId('conn-row')
      .find((r) => r.getAttribute('aria-selected') === 'true');
    expect(sel?.textContent).not.toContain('db01');
  });

  it('stops the probe when the page goes', async () => {
    await renderPage();
    expect(h.stop).not.toHaveBeenCalled();
    cleanup();
    expect(h.stop).toHaveBeenCalledTimes(1);
  });
});
