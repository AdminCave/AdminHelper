// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Auth store session lifecycle (4.77, 6.89): a transient /me error must not destroy a still-valid
// session (only a real 401/403 should); every hydrate path must reach ready:true (or the app hangs
// on the boot spinner); and the global auth-failure handler must end the session. Every way out of
// the session empties the data stores, and a login waits for the answer of the logout (R-0653).

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { get } from 'svelte/store';
import { ApiError, type User } from '$lib/api/types';

vi.mock('$lib/api/client', () => ({
  restoreSession: vi.fn(),
  registerAuthFailureHandler: vi.fn(),
}));
vi.mock('$lib/api/auth', () => ({
  me: vi.fn(),
  logout: vi.fn(),
  login: vi.fn(),
}));
vi.mock('./users', () => ({ users: { reset: vi.fn() } }));
vi.mock('./hooks', () => ({ hooks: { reset: vi.fn() } }));
vi.mock('./apikeys', () => ({ apikeys: { reset: vi.fn() } }));
vi.mock('./frp', () => ({ frpConfig: { reset: vi.fn() } }));

import { restoreSession, registerAuthFailureHandler } from '$lib/api/client';
import * as authApi from '$lib/api/auth';
import { users } from './users';
import { hooks } from './hooks';
import { apikeys } from './apikeys';
import { frpConfig } from './frp';
import { auth } from './auth';

function deferred(): { promise: Promise<void>; resolve: () => void } {
  let resolve!: () => void;
  const promise = new Promise<void>((r) => (resolve = r));
  return { promise, resolve };
}

// A macrotask: every promise callback that could run by now has run.
const settle = () => new Promise((resolve) => setTimeout(resolve, 0));

describe('auth store session lifecycle (4.77, 6.89)', () => {
  beforeEach(() => {
    vi.mocked(restoreSession).mockReset();
    vi.mocked(restoreSession).mockResolvedValue(true); // refresh cookie is valid
    vi.mocked(authApi.me).mockReset();
    vi.mocked(authApi.logout).mockReset();
    vi.mocked(authApi.login).mockReset();
    for (const store of [users, hooks, apikeys, frpConfig]) vi.mocked(store.reset).mockClear();
  });

  it('does NOT log out on a transient /me error (500) — keeps the session cookie', async () => {
    vi.mocked(authApi.me).mockRejectedValue(new ApiError(500, 'server error'));
    await auth.hydrate();
    expect(authApi.logout).not.toHaveBeenCalled();
  });

  it('logs out on a real auth error (401)', async () => {
    vi.mocked(authApi.me).mockRejectedValue(new ApiError(401, 'unauthorized'));
    await auth.hydrate();
    expect(authApi.logout).toHaveBeenCalled();
  });

  it('reaches ready:true with no user on a transient /me error (never a boot-spinner hang)', async () => {
    // The security/UX-critical invariant: every hydrate path must end at ready:true — a forgotten
    // ready:true in an error branch strands the app on the boot spinner forever.
    vi.mocked(authApi.me).mockRejectedValue(new ApiError(500, 'server error'));
    await auth.hydrate();
    expect(get(auth)).toEqual({ user: null, ready: true });
  });

  it('sets ready:true with no user (and skips /me) when restoreSession fails', async () => {
    vi.mocked(restoreSession).mockResolvedValue(false);
    await auth.hydrate();
    expect(get(auth)).toEqual({ user: null, ready: true });
    expect(authApi.me).not.toHaveBeenCalled(); // no /me without a restored session
  });

  it('sets the user and ready:true on a successful hydrate', async () => {
    const user: User = { id: 1, username: 'admin', is_admin: true };
    vi.mocked(authApi.me).mockResolvedValue(user);
    await auth.hydrate();
    expect(get(auth)).toEqual({ user, ready: true });
  });

  it('ends the session globally when the registered auth-failure handler fires', async () => {
    // The handler is registered once at module import (a global 401 anywhere must end the session).
    const handler = vi.mocked(registerAuthFailureHandler).mock.calls[0][0];
    vi.mocked(authApi.me).mockResolvedValue({ id: 1, username: 'admin', is_admin: true });
    await auth.hydrate();
    expect(get(auth).user).not.toBeNull();

    handler();

    expect(authApi.logout).toHaveBeenCalled();
    expect(get(auth)).toEqual({ user: null, ready: true });
  });

  // The three ways out of a session. Each resolves once the logout is under way, not answered.
  const endings: [string, () => Promise<void>][] = [
    [
      'logout()',
      async () => {
        void auth.logout();
      },
    ],
    [
      'the auth-failure handler',
      async () => {
        vi.mocked(registerAuthFailureHandler).mock.calls[0][0]();
      },
    ],
    [
      'hydrate with a 401 from /me',
      async () => {
        vi.mocked(authApi.me).mockRejectedValueOnce(new ApiError(401, 'unauthorized'));
        await auth.hydrate();
      },
    ],
  ];

  // The answer of POST /api/auth/logout clears the access token and the refresh cookie; a login
  // sent before it lands would lose both.
  it.each(endings)('lets a login wait for the answer of the logout after %s', async (_n, end) => {
    const user: User = { id: 1, username: 'admin', is_admin: true };
    const answer = deferred();
    vi.mocked(authApi.logout).mockReturnValue(answer.promise);
    vi.mocked(authApi.login).mockResolvedValue(user);

    await end();
    const login = auth.login('admin', 'pw');
    await settle();
    expect(authApi.login).not.toHaveBeenCalled();

    answer.resolve();
    await login;
    expect(authApi.login).toHaveBeenCalledTimes(1);
    expect(authApi.login).toHaveBeenCalledWith('admin', 'pw');
    expect(get(auth)).toEqual({ user, ready: true });
  });

  it.each(endings)('empties all four data stores on %s', async (_n, end) => {
    await end();
    await settle();

    for (const store of [users, hooks, apikeys, frpConfig]) {
      expect(store.reset).toHaveBeenCalledTimes(1);
    }
    expect(get(auth)).toEqual({ user: null, ready: true });
  });

  it('ends the session at once, and logout() settles only with the answer', async () => {
    vi.mocked(authApi.me).mockResolvedValue({ id: 1, username: 'admin', is_admin: true });
    await auth.hydrate();
    const answer = deferred();
    vi.mocked(authApi.logout).mockReturnValue(answer.promise);
    let settled = false;

    const done = auth.logout().then(() => (settled = true));
    expect(get(auth)).toEqual({ user: null, ready: true });
    await settle();
    expect(settled).toBe(false);

    answer.resolve();
    await done;
    expect(settled).toBe(true);
  });

  it('lets a login wait for every logout in flight, not only the last one', async () => {
    vi.mocked(authApi.login).mockResolvedValue({ id: 1, username: 'admin', is_admin: true });
    const first = deferred();
    const second = deferred();
    vi.mocked(authApi.logout)
      .mockReturnValueOnce(first.promise)
      .mockReturnValueOnce(second.promise);

    void auth.logout();
    vi.mocked(registerAuthFailureHandler).mock.calls[0][0]();
    const login = auth.login('admin', 'pw');
    second.resolve();
    await settle();
    expect(authApi.login).not.toHaveBeenCalled();

    first.resolve();
    await login;
    expect(authApi.login).toHaveBeenCalledTimes(1);
  });

  // A request of the old session that fails after the logout fires the auth-failure handler.
  it('lets a waiting login also wait for a logout that starts meanwhile', async () => {
    vi.mocked(authApi.login).mockResolvedValue({ id: 1, username: 'admin', is_admin: true });
    const first = deferred();
    const second = deferred();
    vi.mocked(authApi.logout)
      .mockReturnValueOnce(first.promise)
      .mockReturnValueOnce(second.promise);

    void auth.logout();
    const login = auth.login('admin', 'pw');
    vi.mocked(registerAuthFailureHandler).mock.calls[0][0]();
    first.resolve();
    await settle();
    expect(authApi.login).not.toHaveBeenCalled();

    second.resolve();
    await login;
    expect(authApi.login).toHaveBeenCalledTimes(1);
  });
});
