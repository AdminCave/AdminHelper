// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// arch-monitoring-neu-p0-abnahme T4 (R-1558): the server list and „Alle Server“ as Kevin accepted
// them (round 5, 2026-11-19). The server list keeps the order of today's monitoring and folds the
// quiet rest; the Lagekarte sums up a fleet from 40 servers on and shows the 20 worst rows; the
// board shows 24 cards (8 with metrics) and more per click.

import { afterEach, describe, expect, it, vi } from 'vitest';

// jsdom has no matchMedia, which svelte/motion (Lagekarte, Alle Server) reads at import, and no
// Web Animations, which the cards' flip and fade use: here every animation ends in a microtask.
vi.hoisted(() => {
  Element.prototype.getAnimations = () => [];
  Element.prototype.animate = function () {
    let cancelled = false;
    let done = () => {};
    return {
      playState: 'finished',
      effect: null,
      cancel: () => {
        cancelled = true;
      },
      get onfinish() {
        return done;
      },
      set onfinish(fn: () => void) {
        done = fn;
        queueMicrotask(() => {
          if (!cancelled && done === fn) fn();
        });
      },
    } as unknown as Animation;
  };
  window.matchMedia = (query: string) =>
    ({
      matches: false,
      media: query,
      onchange: null,
      addEventListener: () => {},
      removeEventListener: () => {},
      addListener: () => {},
      removeListener: () => {},
      dispatchEvent: () => false,
    }) as MediaQueryList;
});

import { cleanup, fireEvent, render, waitFor } from '@testing-library/svelte';
import { ALL_OBJECTS } from '../fixtures';
import { NOW } from '../fixtures/time';
import type { Kind, MonObject, Status } from '../model';
import AllServers from './AllServers.svelte';
import Lagekarte from './Lagekarte.svelte';
import { lageOf } from './lists';
import ServerNav from './ServerNav.svelte';
import { lageByServer, serverSummaries } from './servers';

afterEach(() => {
  cleanup();
  document.body.innerHTML = '';
});

const name = (prefix: string, i: number) => `${prefix}${String(i).padStart(3, '0')}`;

function obj(server: string, kind: Kind, status: Status, i = 0, since = NOW): MonObject {
  return {
    key: `${server}/${kind}/${i}`,
    server,
    kind,
    name: `${kind}-${i}`,
    identity: ['x'],
    status,
    reason: status === 'ok' ? 'Läuft.' : 'Fällt aus.',
    since: since.toISOString(),
    metrics: [],
  };
}

/** One host per server: `troubled` critical ones (t000…), then `quiet` ok ones (q000…). */
function fleet(troubled: number, quiet: number, status: Status = 'critical'): MonObject[] {
  return [
    ...Array.from({ length: troubled }, (_, i) => obj(name('t', i), 'host', status)),
    ...Array.from({ length: quiet }, (_, i) => obj(name('q', i), 'host', 'ok')),
  ];
}

const text = (el: Element | null) => (el?.textContent ?? '').replace(/\s+/g, ' ').trim();
const servers = (c: HTMLElement, sel: string) =>
  [...c.querySelectorAll<HTMLElement>(sel)].map((el) => el.dataset.server);

describe('server list', () => {
  const nav = (objects: MonObject[], server = '') => {
    const onSelect = vi.fn();
    const r = render(ServerNav, { summaries: serverSummaries(objects), server, onSelect });
    return { ...r, onSelect };
  };

  it('lists „Alle Server“ first, then the servers with problems, worst first, then the quiet ones', () => {
    const s = serverSummaries(ALL_OBJECTS);
    const troubled = s.filter((x) => x.problems > 0 || x.worst === 'stale');
    const quiet = s.filter((x) => !troubled.includes(x));
    expect(troubled.length).toBeGreaterThan(0);
    expect(quiet.length).toBeGreaterThan(0);
    const { container } = nav(ALL_OBJECTS);
    expect(servers(container, 'button.item')).toEqual([
      '',
      ...troubled.map((x) => x.server),
      ...quiet.map((x) => x.server),
    ]);
    expect([...container.querySelectorAll('h2')].map(text)).toEqual([
      `Mit Problemen ${troubled.length}`,
      `Ohne Probleme ${quiet.length}`,
    ]);
    const all = container.querySelector('button.item.all');
    expect(text(all)).toContain(`${troubled.length} von ${s.length} mit Problemen`);
    expect(all?.getAttribute('aria-current')).toBe('true');
  });

  it('marks the selected server', () => {
    const { container } = nav(fleet(2, 2), 'q001');
    const current = container.querySelectorAll('[aria-current="true"]');
    expect([...current].map((el) => (el as HTMLElement).dataset.server)).toEqual(['q001']);
  });

  it('keeps up to 24 quiet servers listed and folds 25 behind one line', async () => {
    const open = nav(fleet(1, 24));
    expect(open.container.querySelector('button.fold')).toBeNull();
    expect(servers(open.container, 'button.item').length).toBe(26);
    cleanup();

    const { container, getByRole } = nav(fleet(1, 25));
    expect(servers(container, 'button.item')).toEqual(['', 't000']);
    await fireEvent.click(getByRole('button', { name: '25 Server ohne Probleme zeigen' }));
    expect(servers(container, 'button.item').length).toBe(27);
  });

  it('lists the folded quiet servers for a search or a quiet selection', async () => {
    const selected = nav(fleet(1, 25), 'q007');
    expect(selected.container.querySelector('button.fold')).toBeNull();
    expect(servers(selected.container, 'button.item').length).toBe(27);
    cleanup();

    const { container, getByLabelText } = nav(fleet(1, 25));
    await fireEvent.input(getByLabelText('Server suchen'), { target: { value: 'Q01' } });
    expect(servers(container, 'button.item')).toEqual([
      '',
      ...Array.from({ length: 10 }, (_, i) => name('q', 10 + i)),
    ]);
    expect(container.querySelector('button.fold')).toBeNull();
    // A search keeps them listed even when more than 24 quiet servers match.
    await fireEvent.input(getByLabelText('Server suchen'), { target: { value: 'Q' } });
    expect(servers(container, 'button.item')).toEqual([
      '',
      ...Array.from({ length: 25 }, (_, i) => name('q', i)),
    ]);
    expect(container.querySelector('button.fold')).toBeNull();
  });

  it('says when no server matches the search', async () => {
    const { container, getByLabelText } = nav(fleet(2, 2));
    await fireEvent.input(getByLabelText('Server suchen'), { target: { value: 'zzz' } });
    expect(servers(container, 'button.item')).toEqual(['']);
    expect(text(container.querySelector('.none'))).toBe('Kein Server passt zu „zzz“.');
  });

  it('„/“ focuses the search, but not while typing in another field', async () => {
    const { getByLabelText } = nav(fleet(2, 2));
    const search = getByLabelText('Server suchen');
    await fireEvent.keyDown(document.body, { key: '/' });
    expect(document.activeElement).toBe(search);

    const other = document.createElement('input');
    document.body.append(other);
    other.focus();
    await fireEvent.keyDown(other, { key: '/' });
    expect(document.activeElement).toBe(other);
  });

  it('arrow keys move through the list and select, stopping at either end', async () => {
    const { container, onSelect } = nav(fleet(2, 1));
    const items = [...container.querySelectorAll<HTMLButtonElement>('button.item')];
    items[0].focus();
    await fireEvent.keyDown(items[0], { key: 'ArrowDown' });
    expect(document.activeElement).toBe(items[1]);
    expect(onSelect).toHaveBeenLastCalledWith('t000');
    await fireEvent.keyDown(items[1], { key: 'ArrowUp' });
    await fireEvent.keyDown(items[0], { key: 'ArrowUp' });
    expect(document.activeElement).toBe(items[0]);
    expect(onSelect).toHaveBeenLastCalledWith('');
    items[3].focus();
    await fireEvent.keyDown(items[3], { key: 'ArrowDown' });
    expect(document.activeElement).toBe(items[3]);
    expect(onSelect).toHaveBeenLastCalledWith('q000');
  });
});

describe('Lagekarte', () => {
  const map = (objects: MonObject[]) => {
    const onOpen = vi.fn();
    const onServer = vi.fn();
    const r = render(Lagekarte, { objects, now: NOW, filter: '', onOpen, onServer });
    return { ...r, onOpen, onServer };
  };

  it('shows every server as a row and no carpet below 40 servers', () => {
    const { container } = map(fleet(5, 34));
    expect(container.querySelector('.lk-fleet')).toBeNull();
    expect(container.querySelectorAll('.lk-row').length).toBe(39);
    expect(container.querySelector('.lk-more')).toBeNull();
  });

  it('sums up 40 servers in a carpet, worst first, and shows the 20 worst rows', async () => {
    const objects = fleet(25, 15);
    const { container, getByRole } = map(objects);
    expect(servers(container, 'button.lk-f')).toEqual(
      serverSummaries(objects).map((s) => s.server),
    );
    expect(text(container.querySelector('.lk-fleet-head'))).toBe(
      '40 Server 25 mit Problemen · ein Feld je Server, schlimmste zuerst',
    );
    expect(servers(container, 'button.lk-server')).toEqual(
      Array.from({ length: 20 }, (_, i) => name('t', i)),
    );
    expect(text(container.querySelector('.lk-more'))).toBe(
      '+20 weitere, davon 5 mit Problemen und 15 ohne alle zeigen',
    );
    await fireEvent.click(getByRole('button', { name: 'alle zeigen' }));
    expect(container.querySelectorAll('.lk-row').length).toBe(40);
    await fireEvent.click(getByRole('button', { name: 'nur die 20 schlimmsten zeigen' }));
    expect(container.querySelectorAll('.lk-row').length).toBe(20);
  });

  it('names the server under focus in the carpet head and selects it on click', async () => {
    const { container, onServer } = map(fleet(25, 15));
    const field = container.querySelector('button.lk-f[data-server="q003"]') as HTMLElement;
    expect(field.getAttribute('aria-label')).toBe('q003: alles in Ordnung');
    await fireEvent.focus(field);
    expect(text(container.querySelector('.lk-fleet-head'))).toContain('q003 alles in Ordnung');
    await fireEvent.blur(field);
    expect(text(container.querySelector('.lk-fleet-head'))).toContain('40 Server');
    await fireEvent.click(field);
    expect(onServer).toHaveBeenCalledWith('q003');
  });

  it('opens a single object from its cell, a server at that kind for several, nothing for none', async () => {
    const objects = [
      obj('t000', 'host', 'critical'),
      ...[0, 1, 2].map((i) => obj('t000', 'service', 'warning', i)),
      obj('q000', 'host', 'ok'),
    ];
    const { container, onOpen, onServer } = map(objects);
    const cell = (server: string, kind: Kind) =>
      container.querySelector(
        `.lk-cell[data-server="${server}"][data-kind="${kind}"]`,
      ) as HTMLElement;
    await fireEvent.click(cell('t000', 'host'));
    expect(onOpen).toHaveBeenCalledWith('t000/host/0');
    expect(cell('t000', 'service').getAttribute('aria-label')).toContain('3 Objekte');
    await fireEvent.click(cell('t000', 'service'));
    expect(onServer).toHaveBeenCalledWith('t000', 'service');
    expect(cell('q000', 'service').tagName).toBe('SPAN');
    expect(cell('q000', 'service').dataset.state).toBe('none');
  });
});

describe('„Alle Server“', () => {
  const board = (objects: MonObject[]) => {
    const onOpen = vi.fn();
    const onServer = vi.fn();
    const r = render(AllServers, { objects, now: NOW, onOpen, onServer });
    return { ...r, onOpen, onServer };
  };
  const cards = (c: HTMLElement) => servers(c, 'section.server-card');

  it('heads with the open problems and the servers they are on', () => {
    const { container, getByTestId } = board(ALL_OBJECTS);
    const lage = lageOf(ALL_OBJECTS);
    expect(text(container.querySelector('.hero .sr-only'))).toBe(String(lage.problems.length));
    expect(getByTestId('lage-summary').textContent).toBe(
      `auf ${lageByServer(ALL_OBJECTS).attention.length} von ${lage.servers} Servern`,
    );
  });

  it('shows up to 28 cards at once and folds more behind 24', async () => {
    const all = board(fleet(28, 0));
    expect(cards(all.container).length).toBe(28);
    expect(all.container.querySelector('.more-btn')).toBeNull();
    cleanup();

    const { container, getByRole } = board(fleet(29, 3));
    expect(cards(container)).toEqual(Array.from({ length: 24 }, (_, i) => name('t', i)));
    expect(text(container.querySelector('.more-servers'))).toBe(
      '5 weitere Server zeigen noch 5 mit Problemen',
    );
    await fireEvent.click(getByRole('button', { name: '5 weitere Server zeigen' }));
    expect(cards(container).length).toBe(29);
    expect(container.querySelector('.more-btn')).toBeNull();
  });

  it('shows 8 cards with metrics and 8 more per click', async () => {
    const { container, getByRole } = board(fleet(29, 0));
    await fireEvent.click(getByRole('radio', { name: 'Mit Kennzahlen' }));
    expect(container.querySelectorAll('section.wide-card').length).toBe(8);
    expect(text(container.querySelector('.more-servers'))).toBe(
      '8 weitere Server zeigen noch 21 mit Problemen',
    );
    await fireEvent.click(getByRole('button', { name: '8 weitere Server zeigen' }));
    expect(container.querySelectorAll('section.wide-card').length).toBe(16);
  });

  it('the legend narrows the cards to a state and starts over at the first cards', async () => {
    const objects = [...fleet(40, 0), obj('w000', 'host', 'warning')];
    const { container, getByRole } = board(objects);
    const tile = (st: Status) =>
      container.querySelector(`button[data-tile="${st}"]`) as HTMLButtonElement;
    expect(tile('unknown').disabled).toBe(true);
    await fireEvent.click(getByRole('button', { name: '17 weitere Server zeigen' }));
    expect(cards(container).length).toBe(41);
    await fireEvent.click(tile('warning'));
    expect(tile('warning').getAttribute('aria-pressed')).toBe('true');
    // The other cards fade out before they leave.
    await waitFor(() => expect(cards(container)).toEqual(['w000']));
    expect(text(container.querySelector('.filter-note'))).toContain('Filter aufheben');
    await fireEvent.click(tile('warning'));
    expect(tile('warning').getAttribute('aria-pressed')).toBe('false');
    await waitFor(() => expect(cards(container).length).toBe(24));
  });

  it('lists the 12 newest problems, newest first', () => {
    const objects = Array.from({ length: 20 }, (_, i) =>
      obj(name('t', i), 'host', 'critical', 0, new Date(NOW.getTime() - (i + 1) * 60_000)),
    );
    const { container } = board(objects);
    const keys = [...container.querySelectorAll<HTMLElement>('button.rc-item')].map(
      (el) => el.dataset.key,
    );
    expect(keys).toEqual(Array.from({ length: 12 }, (_, i) => `${name('t', i)}/host/0`));
  });

  it('a card opens its server and its problem lines', async () => {
    const objects = [obj('t000', 'host', 'critical'), obj('t000', 'disk', 'warning')];
    const { container, onOpen, onServer } = board(objects);
    const card = container.querySelector('section.server-card[data-server="t000"]') as HTMLElement;
    await fireEvent.click(card.querySelector('button.server') as HTMLElement);
    expect(onServer).toHaveBeenCalledWith('t000');
    await fireEvent.click(
      card.querySelector('button.p-line[data-key="t000/disk/0"]') as HTMLElement,
    );
    expect(onOpen).toHaveBeenCalledWith('t000/disk/0');
  });

  it('says so when nothing is open', () => {
    const { container, getByText } = board(fleet(0, 5));
    expect(getByText('Keine offenen Probleme')).toBeTruthy();
    expect(cards(container)).toEqual([]);
  });
});
