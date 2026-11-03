// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// The API keys page lists the keys with their permission, shows the empty state for an empty
// list and opens the create dialog from the header.

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, cleanup, fireEvent, within } from '@testing-library/svelte';

import ApiKeys from './ApiKeys.svelte';
import { language } from '$lib/i18n';
import type { ApiKey } from '$lib/api/types';

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

let list: ApiKey[];

function fetchStub(input: RequestInfo | URL): Promise<Response> {
  const path = String(input).split('?')[0];
  if (path === '/api/api-keys') return Promise.resolve(json(list));
  return Promise.resolve(json({ detail: 'unexpected' }, 404));
}

describe('ApiKeys page', () => {
  beforeEach(() => {
    language.set('de');
    vi.stubGlobal('fetch', vi.fn(fetchStub));
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it('lists the keys with their permission and a delete button each', async () => {
    list = [
      { id: 1, name: 'ci', permission: 'read_write', created_at: '2026-10-01T00:00:00Z' },
      { id: 2, name: 'grafana', permission: 'read', created_at: '2026-10-02T00:00:00Z' },
    ];
    const { container, findByText } = render(ApiKeys);
    await findByText('grafana');

    const rows = [...container.querySelectorAll<HTMLElement>('tbody tr')];
    expect(rows).toHaveLength(2);
    expect(within(rows[0]).getByText('Lesen & Schreiben').closest('.pill-ok')).not.toBeNull();
    expect(within(rows[1]).getByText('Nur lesen').closest('.pill-muted')).not.toBeNull();
    for (const r of rows) {
      expect(within(r).getByRole('button', { name: 'Löschen' })).toBeTruthy();
    }
  });

  it('shows the empty state for an empty list', async () => {
    list = [];
    const { container, findByText } = render(ApiKeys);
    await findByText('Keine API-Keys vorhanden.');
    expect(container.querySelector('table')).toBeNull();
  });

  it('opens the create dialog from the header', async () => {
    list = [];
    const view = render(ApiKeys);
    await fireEvent.click(view.getByRole('button', { name: '+ API-Key' }));
    const dialog = await view.findByRole('dialog');
    expect(dialog.textContent).toContain('Neuer API-Key');
  });
});
