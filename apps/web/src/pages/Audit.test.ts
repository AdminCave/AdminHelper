// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// The audit view shows each entry's detail (R-0757), e.g. the fields a user.updated changed, as
// plain text.

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, cleanup, waitFor } from '@testing-library/svelte';

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
