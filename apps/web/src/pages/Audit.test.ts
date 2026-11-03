// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// The audit view shows each entry's detail (R-0757), e.g. the fields a user.updated changed, as
// plain text, and its actor filter sends a type only while one is chosen.

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, cleanup, fireEvent, waitFor } from '@testing-library/svelte';

vi.mock('$lib/api/audit', () => ({ list: vi.fn() }));

import Audit from './Audit.svelte';
import { list } from '$lib/api/audit';
import { language } from '$lib/i18n';
import type { AuditEntry } from '$lib/api/types';

function entry(id: number, detail: string | null): AuditEntry {
  return {
    id,
    timestamp: '2026-10-28T10:00:00Z',
    actorType: 'user',
    actorLabel: 'admin',
    action: 'user.updated',
    objectType: 'user',
    objectLabel: `u${id}`,
    sourceIp: '192.0.2.10',
    status: 'success',
    detail,
  };
}

async function rows(container: HTMLElement): Promise<HTMLTableRowElement[]> {
  await waitFor(() => expect(container.querySelectorAll('tbody tr').length).toBeGreaterThan(0));
  return [...container.querySelectorAll('tbody tr')] as HTMLTableRowElement[];
}

function cellUnder(container: HTMLElement, row: HTMLTableRowElement, header: string): string {
  const heads = [...container.querySelectorAll('thead th')].map((th) => th.textContent?.trim());
  const i = heads.indexOf(header);
  expect(i, `no column "${header}" in ${heads.join(', ')}`).toBeGreaterThanOrEqual(0);
  return row.cells[i].textContent?.trim() ?? '';
}

beforeEach(() => {
  language.set('de');
  vi.mocked(list).mockReset();
});

afterEach(() => cleanup());

describe('Audit view: detail column', () => {
  it('shows the detail of an entry under "Detail"', async () => {
    vi.mocked(list).mockResolvedValue([entry(1, 'is_admin, server_ids'), entry(2, null)]);
    const { container } = render(Audit);
    const [first, second] = await rows(container);

    expect(cellUnder(container, first, 'Detail')).toBe('is_admin, server_ids');
    expect(cellUnder(container, second, 'Detail')).toBe('–');
  });

  it('shows markup in a detail as text', async () => {
    vi.mocked(list).mockResolvedValue([entry(1, '<b>x</b>')]);
    const { container } = render(Audit);
    const [first] = await rows(container);

    expect(cellUnder(container, first, 'Detail')).toBe('<b>x</b>');
    expect(container.querySelector('tbody b')).toBeNull();
  });
});

// "All actors" is a value of its own in the select; it must not reach the server, which would
// filter on it and show an empty list.
describe('Audit view: actor filter', () => {
  it('sends an actor type only while one is chosen', async () => {
    vi.mocked(list).mockResolvedValue([]);
    const view = render(Audit);
    await waitFor(() => expect(list).toHaveBeenCalledTimes(1));
    expect(vi.mocked(list).mock.calls[0][0]?.actorType).toBeUndefined();

    await fireEvent.change(view.getByRole('combobox', { name: 'Actor-Typ' }), {
      target: { value: 'user' },
    });
    await fireEvent.click(view.getByRole('button', { name: 'Filtern' }));
    await waitFor(() => expect(list).toHaveBeenCalledTimes(2));
    expect(vi.mocked(list).mock.calls[1][0]?.actorType).toBe('user');

    await fireEvent.click(view.getByRole('button', { name: 'Zurücksetzen' }));
    await waitFor(() => expect(list).toHaveBeenCalledTimes(3));
    expect(vi.mocked(list).mock.calls[2][0]?.actorType).toBeUndefined();
  });
});
