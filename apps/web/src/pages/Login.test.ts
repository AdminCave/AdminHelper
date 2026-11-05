// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// The login page sends both fields to /api/auth/login and shows the server's message on a
// failure. The E2E anchors (#loginUser, #loginPass, .login-card, .login-error) stay.

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, cleanup, fireEvent, within } from '@testing-library/svelte';
import { get } from 'svelte/store';

import Login from './Login.svelte';
import { auth, isAuthenticated } from '$lib/stores/auth';
import { language } from '$lib/i18n';

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

let loginOk: boolean;
let fetchMock: ReturnType<typeof vi.fn>;

function fetchStub(input: RequestInfo | URL): Promise<Response> {
  const path = String(input).split('?')[0];
  if (path === '/api/auth/login') {
    return Promise.resolve(
      loginOk ? json({ access_token: 'a2' }) : json({ detail: 'Invalid credentials' }, 401),
    );
  }
  if (path === '/api/auth/me')
    return Promise.resolve(json({ id: 1, username: 'admin', is_admin: true }));
  if (path === '/api/auth/logout') return Promise.resolve(json({ detail: 'ok' }));
  return Promise.resolve(json({ detail: 'no session' }, 401));
}

function loginBody(): unknown {
  const call = fetchMock.mock.calls.find(([input]) => String(input) === '/api/auth/login');
  return call ? JSON.parse(String((call[1] as RequestInit).body)) : undefined;
}

async function fillAndSubmit(container: HTMLElement, user: string, pass: string) {
  const u = container.querySelector<HTMLInputElement>('#loginUser')!;
  const p = container.querySelector<HTMLInputElement>('#loginPass')!;
  await fireEvent.input(u, { target: { value: user } });
  await fireEvent.input(p, { target: { value: pass } });
  await fireEvent.click(within(container).getByRole('button', { name: 'Anmelden' }));
}

describe('Login', () => {
  beforeEach(() => {
    language.set('de');
    fetchMock = vi.fn(fetchStub);
    vi.stubGlobal('fetch', fetchMock);
  });

  afterEach(async () => {
    cleanup();
    await auth.logout();
    vi.unstubAllGlobals();
  });

  it('labels both fields and keeps the E2E anchors', () => {
    const view = render(Login);
    expect(view.container.querySelector('.login-card')).not.toBeNull();
    expect(view.getByLabelText('Benutzername').id).toBe('loginUser');
    expect(view.getByLabelText('Passwort').id).toBe('loginPass');
    expect((view.getByLabelText('Passwort') as HTMLInputElement).type).toBe('password');
    expect((view.getByLabelText('Benutzername') as HTMLInputElement).required).toBe(true);
  });

  it('signs in with the entered credentials', async () => {
    loginOk = true;
    const view = render(Login);
    await fillAndSubmit(view.container, 'admin', 'secret123');
    await vi.waitFor(() => expect(get(isAuthenticated)).toBe(true));
    expect(loginBody()).toEqual(
      expect.objectContaining({ username: 'admin', password: 'secret123' }),
    );
    expect(view.container.querySelector('.login-error')).toBeNull();
  });

  it("shows the server's message and stays signed out on bad credentials", async () => {
    loginOk = false;
    const view = render(Login);
    await fillAndSubmit(view.container, 'admin', 'falsch');
    const err = await view.findByRole('alert');
    expect(err.classList.contains('login-error')).toBe(true);
    expect(err.textContent).toBe('Invalid credentials');
    expect(get(isAuthenticated)).toBe(false);
    // The button is usable again for the next try.
    expect((view.getByRole('button', { name: 'Anmelden' }) as HTMLButtonElement).disabled).toBe(
      false,
    );
  });
});
