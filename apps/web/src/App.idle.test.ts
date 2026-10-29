// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// The whole app signs out after `idle_timeout_minutes` (from GET /api/auth/me) without input, and
// leaves a notice that stays until it is closed. A session restored on page load ends at once if
// the last input in this browser is older than that; a session from a login starts fresh. Same
// stub pattern as pages.load.test.ts: the session is restored from the refresh cookie, everything
// else answers an empty list.

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, cleanup } from '@testing-library/svelte';
import { get } from 'svelte/store';

import App from './App.svelte';
import { auth, isAuthenticated } from '$lib/stores/auth';
import { toasts, dismissToast } from '$lib/stores/notifications';
import { language } from '$lib/i18n';

const START = new Date('2026-10-23T08:00:00Z').getTime();
const CHECK = 15_000;
const LAST_ACTIVITY = 'adminhelper_last_activity';

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

let idleMinutes: number;
let hasSessionCookie: boolean;
let fetchMock: ReturnType<typeof vi.fn>;

function fetchStub(input: RequestInfo | URL): Promise<Response> {
  const path = String(input).split('?')[0];
  if (path === '/api/auth/refresh') {
    return Promise.resolve(
      hasSessionCookie ? json({ access_token: 'a1' }) : json({ detail: 'no session' }, 401),
    );
  }
  if (path === '/api/auth/login') return Promise.resolve(json({ access_token: 'a2' }));
  if (path === '/api/auth/me') {
    return Promise.resolve(
      json({ id: 1, username: 'admin', is_admin: true, idle_timeout_minutes: idleMinutes }),
    );
  }
  if (path === '/api/auth/logout') return Promise.resolve(json({ detail: 'Abgemeldet' }));
  return Promise.resolve(json([]));
}

function logoutPosts(): number {
  return fetchMock.mock.calls.filter(
    ([input, init]) =>
      String(input) === '/api/auth/logout' && (init as RequestInit | undefined)?.method === 'POST',
  ).length;
}

async function renderSignedIn(minutes: number) {
  idleMinutes = minutes;
  const view = render(App);
  await vi.waitFor(() => expect(get(isAuthenticated)).toBe(true));
  return view;
}

describe('App: sign-out after inactivity', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(START);
    localStorage.clear();
    language.set('de');
    hasSessionCookie = true;
    fetchMock = vi.fn(fetchStub);
    vi.stubGlobal('fetch', fetchMock);
  });

  afterEach(async () => {
    cleanup();
    // The auth store outlives the component: the next test has to start without a session.
    await auth.logout();
    for (const t of get(toasts)) dismissToast(t.id);
    vi.useRealTimers();
    vi.unstubAllGlobals();
    localStorage.clear();
  });

  it('(a) signs out after the limit without input and leaves a notice that stays', async () => {
    const { container, getByText } = await renderSignedIn(1);
    expect(container.querySelector('.server-layout')).not.toBeNull();

    await vi.advanceTimersByTimeAsync(59_000);
    expect(logoutPosts()).toBe(0);
    expect(get(isAuthenticated)).toBe(true);

    await vi.advanceTimersByTimeAsync(2_000 + CHECK);
    expect(logoutPosts()).toBe(1);
    expect(get(isAuthenticated)).toBe(false);
    expect(container.querySelector('form.login-form')).not.toBeNull();
    const text = 'Nach 1 Minuten ohne Bedienung abgemeldet.';
    expect(get(toasts)).toEqual([expect.objectContaining({ kind: 'info', message: text })]);
    expect(getByText(text)).toBeTruthy();

    // Nobody was there when it appeared: the notice outlasts a normal toast, and the stopped
    // watch sends no second logout.
    await vi.advanceTimersByTimeAsync(10 * 60_000);
    expect(get(toasts).map((t) => t.message)).toEqual([text]);
    expect(logoutPosts()).toBe(1);
  });

  it('(b) idle_timeout_minutes 0 never signs out', async () => {
    const { container } = await renderSignedIn(0);

    await vi.advanceTimersByTimeAsync(10 * 60_000);
    expect(logoutPosts()).toBe(0);
    expect(get(isAuthenticated)).toBe(true);
    expect(container.querySelector('.server-layout')).not.toBeNull();
  });

  it('(c) a keydown every 30 s keeps the session, silence then ends it', async () => {
    await renderSignedIn(1);

    for (let i = 0; i < 6; i++) {
      await vi.advanceTimersByTimeAsync(30_000);
      window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Shift' }));
    }
    expect(logoutPosts()).toBe(0);
    expect(get(isAuthenticated)).toBe(true);

    await vi.advanceTimersByTimeAsync(61_000 + CHECK);
    expect(logoutPosts()).toBe(1);
    expect(get(isAuthenticated)).toBe(false);
  });

  it('(d) signing out by hand ends the watch of that session', async () => {
    await renderSignedIn(1);

    await auth.logout();
    expect(logoutPosts()).toBe(1);

    await vi.advanceTimersByTimeAsync(2 * 60_000);
    expect(logoutPosts()).toBe(1);
    expect(get(toasts)).toEqual([]);
  });

  it('(e) a session restored on load ends at once if the last input here is past the limit', async () => {
    idleMinutes = 1;
    localStorage.setItem(LAST_ACTIVITY, String(START - 2 * 60_000));
    const { container, getByText } = render(App);

    // Long before the first check after 15 s.
    await vi.waitFor(() => expect(logoutPosts()).toBe(1));
    expect(Date.now() - START).toBeLessThan(CHECK);
    // The session was restored first: the sign-out is the idle one, not a failed restore.
    expect(fetchMock.mock.calls.map(([input]) => String(input))).toContain('/api/auth/me');
    expect(get(isAuthenticated)).toBe(false);
    const text = 'Nach 1 Minuten ohne Bedienung abgemeldet.';
    expect(get(toasts)).toEqual([expect.objectContaining({ kind: 'info', message: text })]);
    await vi.waitFor(() => expect(container.querySelector('form.login-form')).not.toBeNull());
    expect(getByText(text)).toBeTruthy();
  });

  it('(f) a login after the idle sign-out in this tab starts fresh', async () => {
    await renderSignedIn(1);
    await vi.advanceTimersByTimeAsync(61_000 + CHECK);
    expect(logoutPosts()).toBe(1);
    // The stored time of the old session is past the limit now.
    expect(Date.now() - Number(localStorage.getItem(LAST_ACTIVITY))).toBeGreaterThan(60_000);

    await auth.login('admin', 'pw');
    await vi.advanceTimersByTimeAsync(CHECK);
    expect(get(isAuthenticated)).toBe(true);
    expect(logoutPosts()).toBe(1);

    // The new session has a watch of its own: silence ends it after the limit.
    await vi.advanceTimersByTimeAsync(60_000);
    expect(logoutPosts()).toBe(2);
    expect(get(isAuthenticated)).toBe(false);
  });

  it('(g) a login after a page load without a session starts fresh, however old the stored time', async () => {
    hasSessionCookie = false;
    idleMinutes = 1;
    localStorage.setItem(LAST_ACTIVITY, String(START - 120 * 60_000));
    const { container } = render(App);
    await vi.waitFor(() => expect(container.querySelector('form.login-form')).not.toBeNull());

    await auth.login('admin', 'pw');
    await vi.advanceTimersByTimeAsync(CHECK);
    expect(get(isAuthenticated)).toBe(true);
    expect(logoutPosts()).toBe(0);
  });
});
