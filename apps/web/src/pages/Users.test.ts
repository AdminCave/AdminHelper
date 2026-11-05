// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// The users page lists the accounts with their role, offers no delete on the own row, shows
// the empty state for an empty list and opens the dialogs from the header and the row.

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, cleanup, fireEvent, within } from '@testing-library/svelte';

import Users from './Users.svelte';
import { auth } from '$lib/stores/auth';
import { language } from '$lib/i18n';
import type { User } from '$lib/api/types';

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

let list: User[];

function fetchStub(input: RequestInfo | URL): Promise<Response> {
  const path = String(input).split('?')[0];
  if (path === '/api/auth/refresh') return Promise.resolve(json({ access_token: 'a1' }));
  if (path === '/api/auth/me')
    return Promise.resolve(json({ id: 1, username: 'admin', is_admin: true }));
  if (path === '/api/auth/logout') return Promise.resolve(json({ detail: 'ok' }));
  if (path === '/api/users') return Promise.resolve(json(list));
  return Promise.resolve(json([]));
}

function row(container: HTMLElement, name: string): HTMLElement {
  const tr = [...container.querySelectorAll<HTMLElement>('tbody tr')].find((r) =>
    r.textContent?.includes(name),
  );
  expect(tr, `no row ${name}`).toBeDefined();
  return tr as HTMLElement;
}

describe('Users page', () => {
  beforeEach(async () => {
    language.set('de');
    vi.stubGlobal('fetch', vi.fn(fetchStub));
    await auth.hydrate();
  });

  afterEach(async () => {
    cleanup();
    await auth.logout();
    vi.unstubAllGlobals();
  });

  it('lists the users with their role and no delete on the own row', async () => {
    list = [
      { id: 1, username: 'admin', is_admin: true, created_at: '2026-10-01T00:00:00Z' },
      { id: 2, username: 'bob', is_admin: false, created_at: '2026-10-02T00:00:00Z' },
    ];
    const { container, findByText } = render(Users);
    await findByText('bob');

    const me = within(row(container, 'admin'));
    expect(me.getByText('(ich)')).toBeTruthy();
    expect(me.getByText('Admin').closest('.pill-warn')).not.toBeNull();
    expect(me.queryByRole('button', { name: 'Löschen' })).toBeNull();
    expect(me.getByRole('button', { name: 'Bearbeiten' })).toBeTruthy();

    const bob = within(row(container, 'bob'));
    expect(bob.getByText('Benutzer').closest('.pill-accent')).not.toBeNull();
    expect(bob.getByRole('button', { name: 'Löschen' })).toBeTruthy();
    expect(bob.getByRole('button', { name: 'Registrierungs-Token' })).toBeTruthy();
  });

  it('shows the empty state for an empty list', async () => {
    list = [];
    const { container, findByText } = render(Users);
    await findByText('Keine Benutzer vorhanden.');
    expect(container.querySelector('table')).toBeNull();
  });

  it('opens the create dialog from the header and the edit dialog from a row', async () => {
    list = [{ id: 2, username: 'bob', is_admin: false }];
    const view = render(Users);
    await view.findByText('bob');

    await fireEvent.click(view.getByRole('button', { name: '+ Benutzer' }));
    const created = await view.findByRole('dialog');
    expect(created.textContent).toContain('Neuer Benutzer');
    await fireEvent.click(within(created).getAllByRole('button', { name: 'Schließen' })[0]);
    await vi.waitFor(() => expect(view.queryByRole('dialog')).toBeNull());

    await fireEvent.click(
      within(row(view.container, 'bob')).getByRole('button', { name: 'Bearbeiten' }),
    );
    const edit = await view.findByRole('dialog');
    expect(edit.textContent).toContain('Benutzer bearbeiten');
  });
});
