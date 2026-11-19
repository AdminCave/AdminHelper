// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// arch-monitoring-neu-p0-abnahme T3 (R-1558): the limits Kevin accepted with the mockup
// (2026-11-19, „Wie im Mockup“) hold on the large fleet. An object-kind group draws its rows only
// when open and 60 at a time, shows a bar instead of dots above 42 objects; Objekte pages by 200,
// Querschnitte by 150, and a new filter or view starts at the first page again. T4: the server
// list folds the quiet servers, the Lagekarte shows the 20 worst of the fleet, and „Alle Server“
// draws 24 cards (8 with metrics) at a time.

import { afterEach, describe, expect, it, vi } from 'vitest';

// jsdom has neither matchMedia (svelte/motion reads it at import) nor scrollIntoView.
const jsdom = vi.hoisted(() => {
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
  const scrolled: Element[] = [];
  Element.prototype.scrollIntoView = function (this: Element) {
    scrolled.push(this);
  };
  return { scrolled };
});

import { cleanup, fireEvent, render } from '@testing-library/svelte';
import { SCALE_OBJECTS } from '../fixtures/scale';
import { NOW } from '../fixtures/time';
import type { Kind, MonObject } from '../model';
import { CROSS_VIEWS } from './cross';
import CrossView from './CrossView.svelte';
import KindGroups from './KindGroups.svelte';
import KindsView from './KindsView.svelte';
import AllServers from './AllServers.svelte';
import Lagekarte from './Lagekarte.svelte';
import { NO_FILTER, filterObjects } from './lists';
import ObjectsView from './ObjectsView.svelte';
import ServerNav from './ServerNav.svelte';
import { lageByServer, serverSummaries } from './servers';

afterEach(() => {
  cleanup();
  jsdom.scrolled.length = 0;
});

function many(kind: Kind, n: number): MonObject[] {
  return Array.from({ length: n }, (_, i) => ({
    key: `s${i}/${kind}/${i}`,
    server: `s${i}`,
    kind,
    name: `${kind}-${i}`,
    identity: ['x'],
    status: i === 0 ? ('critical' as const) : ('ok' as const),
    reason: i === 0 ? 'Fällt aus.' : 'Läuft.',
    since: '2026-11-18T08:00:00Z',
    metrics: [],
  }));
}

const group = (c: HTMLElement, kind: Kind) =>
  c.querySelector(`details.group[data-kind="${kind}"]`) as HTMLDetailsElement;
const rows = (el: Element) => el.querySelectorAll('button.row[data-key]').length;

async function openGroup(d: HTMLDetailsElement): Promise<void> {
  d.open = true;
  await fireEvent(d, new Event('toggle'));
}

describe('object-kind groups', () => {
  it('start closed and draw no row, even for the large fleet', () => {
    const { container } = render(KindGroups, {
      objects: SCALE_OBJECTS,
      now: NOW,
      onOpen: () => {},
    });
    const groups = container.querySelectorAll('details.group');
    expect(groups.length).toBe(new Set(SCALE_OBJECTS.map((o) => o.kind)).size);
    expect(container.querySelectorAll('details.group[open]').length).toBe(0);
    expect(rows(container)).toBe(0);
  });

  it('show dots up to 42 objects and a status bar above', () => {
    const { container } = render(KindGroups, {
      objects: [...many('service', 42), ...many('container', 43)],
      now: NOW,
      onOpen: () => {},
    });
    const dots = group(container, 'service');
    expect(dots.querySelectorAll('.dot').length).toBe(42);
    expect(dots.querySelector('[role="img"]')).toBeNull();
    const bar = group(container, 'container');
    expect(bar.querySelectorAll('.dot').length).toBe(0);
    expect(bar.querySelector('[role="img"]')?.getAttribute('aria-label')).toBe('1 Kritisch, 42 OK');
  });

  it('draw 60 rows when opened, 60 more per click, and start over when closed', async () => {
    const { container, getByRole } = render(KindGroups, {
      objects: many('service', 130),
      now: NOW,
      onOpen: () => {},
    });
    const d = group(container, 'service');
    await openGroup(d);
    expect(rows(d)).toBe(60);
    expect(d.querySelector('.page')?.textContent).toContain('60 von 130');
    await fireEvent.click(getByRole('button', { name: '60 weitere anzeigen' }));
    expect(rows(d)).toBe(120);
    await fireEvent.click(getByRole('button', { name: '10 weitere anzeigen' }));
    expect(rows(d)).toBe(130);
    expect(d.querySelector('.page-btn')).toBeNull();
    d.open = false;
    await fireEvent(d, new Event('toggle'));
    expect(rows(d)).toBe(0);
    await openGroup(d);
    expect(rows(d)).toBe(60);
  });

  it('open, mark and scroll to the kind a caller asks for', () => {
    const { container } = render(KindGroups, {
      objects: [...many('service', 3), ...many('disk', 3)],
      now: NOW,
      focus: 'disk',
      onOpen: () => {},
    });
    const d = group(container, 'disk');
    expect(d.open).toBe(true);
    expect(d.classList.contains('flash')).toBe(true);
    expect(rows(d)).toBe(3);
    expect(group(container, 'service').open).toBe(false);
    expect(jsdom.scrolled).toEqual([d]);
  });

  it('„Alle aufklappen“ opens every kind with its first page', async () => {
    const { container, getByRole } = render(KindsView, {
      objects: [...many('service', 130), ...many('disk', 5)],
      now: NOW,
      onOpen: () => {},
    });
    await fireEvent.click(getByRole('button', { name: 'Alle aufklappen' }));
    const groups = [...container.querySelectorAll<HTMLDetailsElement>('details.group')];
    expect(groups.every((d) => d.open)).toBe(true);
    expect(rows(group(container, 'service'))).toBe(60);
    expect(rows(group(container, 'disk'))).toBe(5);
    await fireEvent.click(getByRole('button', { name: 'Alle zuklappen' }));
    expect(rows(container)).toBe(0);
  });
});

describe('pages of the long lists', () => {
  const tableRows = (c: HTMLElement) => c.querySelectorAll('tbody tr').length;

  it('Objekte shows 200 rows a page and starts over with a new search', async () => {
    const { container, getByRole, getByLabelText, getByTestId } = render(ObjectsView, {
      objects: SCALE_OBJECTS,
      now: NOW,
      onOpen: () => {},
    });
    const all = filterObjects(SCALE_OBJECTS, NO_FILTER).length;
    expect(tableRows(container)).toBe(200);
    expect(getByTestId('objects-count').textContent).toContain(
      `${all} von ${SCALE_OBJECTS.length} Objekten, die ersten 200 gezeigt`,
    );
    await fireEvent.click(getByRole('button', { name: '200 weitere anzeigen' }));
    expect(tableRows(container)).toBe(400);
    const hits = filterObjects(SCALE_OBJECTS, { ...NO_FILTER, query: 'example' }).length;
    expect(hits).toBeGreaterThan(400);
    await fireEvent.input(getByLabelText('Objekte durchsuchen'), {
      target: { value: 'example' },
    });
    expect(tableRows(container)).toBe(200);
    expect(getByTestId('objects-count').textContent).toContain(`${hits} von`);
  });

  it('Querschnitte shows 150 rows a page and starts over in another view', async () => {
    const sizes = CROSS_VIEWS.map((v) => ({ v, n: v.rows(SCALE_OBJECTS).length }));
    const big = sizes.filter((s) => s.n > 300);
    expect(big.length).toBeGreaterThanOrEqual(2);
    const [first, second] = big;
    const { container, getByRole } = render(CrossView, {
      objects: SCALE_OBJECTS,
      now: NOW,
      view: first.v.id,
      onOpen: () => {},
    });
    expect(tableRows(container)).toBe(150);
    expect(container.querySelector('.page')?.textContent).toContain(`150 von ${first.n} gezeigt`);
    await fireEvent.click(getByRole('button', { name: '150 weitere anzeigen' }));
    expect(tableRows(container)).toBe(300);
    await fireEvent.click(getByRole('radio', { name: second.v.title }));
    expect(tableRows(container)).toBe(150);
    expect(container.querySelector('.page')?.textContent).toContain(`150 von ${second.n} gezeigt`);
  });
});

describe('overview with the large fleet', () => {
  const summaries = serverSummaries(SCALE_OBJECTS);
  const troubled = summaries.filter((s) => s.problems > 0 || s.worst === 'stale');
  const quiet = summaries.length - troubled.length;
  const attention = lageByServer(SCALE_OBJECTS).attention.length;
  const text = (el: Element | null) => (el?.textContent ?? '').replace(/\s+/g, ' ').trim();

  it('is large enough to fold everywhere', () => {
    expect(summaries.length).toBe(292);
    expect(quiet).toBeGreaterThan(24);
    expect(troubled.length).toBeGreaterThan(20);
    expect(attention).toBeGreaterThan(52);
  });

  it('the server list keeps the servers with problems and folds the quiet ones', async () => {
    const { container, getByRole } = render(ServerNav, {
      summaries,
      server: '',
      onSelect: () => {},
    });
    expect(container.querySelectorAll('button.item').length).toBe(1 + troubled.length);
    await fireEvent.click(getByRole('button', { name: `${quiet} Server ohne Probleme zeigen` }));
    expect(container.querySelectorAll('button.item').length).toBe(1 + summaries.length);
  });

  it('the Lagekarte has a field per server and the 20 worst rows', async () => {
    const { container, getByRole } = render(Lagekarte, {
      objects: SCALE_OBJECTS,
      now: NOW,
      filter: '',
      onOpen: () => {},
      onServer: () => {},
    });
    expect(container.querySelectorAll('button.lk-f').length).toBe(292);
    expect(container.querySelectorAll('.lk-row').length).toBe(20);
    expect(text(container.querySelector('.lk-more'))).toBe(
      `+272 weitere, davon ${troubled.length - 20} mit Problemen und ${quiet} ohne alle zeigen`,
    );
    await fireEvent.click(getByRole('button', { name: 'alle zeigen' }));
    expect(container.querySelectorAll('.lk-row').length).toBe(292);
  });

  it('„Alle Server“ draws 24 cards and 24 more per click', async () => {
    const { container, getByRole } = render(AllServers, {
      objects: SCALE_OBJECTS,
      now: NOW,
      onOpen: () => {},
      onServer: () => {},
    });
    const cards = () => container.querySelectorAll('section.server-card').length;
    expect(cards()).toBe(24);
    expect(text(container.querySelector('.more-servers'))).toBe(
      `24 weitere Server zeigen noch ${attention - 24} mit Problemen`,
    );
    await fireEvent.click(getByRole('button', { name: '24 weitere Server zeigen' }));
    expect(cards()).toBe(48);
  });

  it('„Alle Server“ with metrics draws 8 boxes', async () => {
    const { container, getByRole } = render(AllServers, {
      objects: SCALE_OBJECTS,
      now: NOW,
      onOpen: () => {},
      onServer: () => {},
    });
    await fireEvent.click(getByRole('radio', { name: 'Mit Kennzahlen' }));
    expect(container.querySelectorAll('section.wide-card').length).toBe(8);
    expect(text(container.querySelector('.more-servers'))).toBe(
      `8 weitere Server zeigen noch ${attention - 8} mit Problemen`,
    );
  });
});
