// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// arch-monitoring-ui T4 (R-1225): the cross-server table (certificates, backups,
// updates). Pins the start sort and aria-sort, flipping a column, empty values last in
// both directions, numeric collation of names, the filter with its count and its
// no-match text, and a column's own cell.

import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { cleanup, fireEvent, render } from '@testing-library/svelte';
import { createRawSnippet } from 'svelte';
import { setLanguage } from '$lib/i18n';
import CrossTable, { type CrossColumn } from './CrossTable.svelte';

interface Row {
  id: string;
  name: string;
  days: number | null;
}

const ROWS: Row[] = [
  { id: 'a', name: 'web-10', days: 30 },
  { id: 'b', name: 'web-9', days: null },
  { id: 'c', name: 'db', days: 5 },
];

const COLUMNS: CrossColumn<Row>[] = [
  { key: 'name', label: 'Server', text: (r) => r.name },
  {
    key: 'days',
    label: 'Tage',
    text: (r) => (r.days === null ? '—' : String(r.days)),
    sort: (r) => r.days,
    numeric: true,
  },
];

function props(extra: Record<string, unknown> = {}) {
  return {
    rows: ROWS,
    columns: COLUMNS,
    rowKey: (r: Row) => r.id,
    label: 'Zertifikate',
    emptyText: 'Keine Zertifikate',
    ...extra,
  };
}

function names(container: HTMLElement): string[] {
  return [...container.querySelectorAll('tbody tr')].map(
    (tr) => tr.querySelector('td')?.textContent?.trim() ?? '',
  );
}

function header(container: HTMLElement, label: string): HTMLElement {
  const th = [...container.querySelectorAll('th')].find((el) => el.textContent?.includes(label));
  if (!th) throw new Error(`no header ${label}`);
  return th;
}

beforeEach(() => setLanguage('de'));
afterEach(() => cleanup());

describe('CrossTable', () => {
  it('shows the empty text and no table without rows', () => {
    const { getByText, container } = render(CrossTable<Row>, props({ rows: [] }));
    expect(getByText('Keine Zertifikate')).toBeTruthy();
    expect(container.querySelector('table')).toBeNull();
  });

  it('keeps the given order without a sort key', () => {
    const { container, getByRole } = render(CrossTable<Row>, props());
    expect(getByRole('table', { name: 'Zertifikate' })).toBeTruthy();
    expect(names(container)).toEqual(['web-10', 'web-9', 'db']);
    expect(header(container, 'Server').getAttribute('aria-sort')).toBe('none');
  });

  it('starts sorted and puts empty values last in both directions', async () => {
    const { container } = render(CrossTable<Row>, props({ sortKey: 'days' }));
    expect(names(container)).toEqual(['db', 'web-10', 'web-9']);
    expect(header(container, 'Tage').getAttribute('aria-sort')).toBe('ascending');
    expect(header(container, 'Server').getAttribute('aria-sort')).toBe('none');

    await fireEvent.click(header(container, 'Tage').querySelector('button')!);
    expect(names(container)).toEqual(['web-10', 'db', 'web-9']);
    expect(header(container, 'Tage').getAttribute('aria-sort')).toBe('descending');
  });

  it('sorts a new column ascending, names with numbers in numeric order', async () => {
    const { container } = render(CrossTable<Row>, props({ sortKey: 'days', sortDir: 'desc' }));
    expect(names(container)).toEqual(['web-10', 'db', 'web-9']);
    await fireEvent.click(header(container, 'Server').querySelector('button')!);
    expect(names(container)).toEqual(['db', 'web-9', 'web-10']);
    expect(header(container, 'Server').getAttribute('aria-sort')).toBe('ascending');
    expect(header(container, 'Tage').getAttribute('aria-sort')).toBe('none');
  });

  it('filters over the cell texts and counts what is left', async () => {
    const { container, getByRole, getByText, queryByText } = render(CrossTable<Row>, props());
    const input = getByRole('searchbox', { name: 'Filtern' });
    expect(queryByText(/von 3/)).toBeNull();

    await fireEvent.input(input, { target: { value: '  WEB ' } });
    expect(names(container)).toEqual(['web-10', 'web-9']);
    expect(getByText('2 von 3')).toBeTruthy();

    await fireEvent.input(input, { target: { value: '30' } });
    expect(names(container)).toEqual(['web-10']);

    await fireEvent.input(input, { target: { value: 'zzz' } });
    expect(container.querySelector('table')).toBeNull();
    expect(getByText('Nichts passt zu „zzz“')).toBeTruthy();
    expect(getByText('0 von 3')).toBeTruthy();
  });

  it('renders a column cell instead of its text', () => {
    const pill = createRawSnippet((row: () => Row) => ({
      render: () => `<b data-testid="pill">${row().days ?? 'none'}</b>`,
    }));
    const columns: CrossColumn<Row>[] = [COLUMNS[0], { ...COLUMNS[1], cell: pill }];
    const { getAllByTestId } = render(CrossTable<Row>, props({ columns }));
    expect(getAllByTestId('pill').map((el) => el.textContent)).toEqual(['30', 'none', '5']);
  });
});
