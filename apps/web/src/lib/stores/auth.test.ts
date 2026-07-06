// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Auth store session lifecycle (4.77, 6.89): a transient /me error must not destroy a still-valid
// session (only a real 401/403 should); every hydrate path must reach ready:true (or the app hangs
// on the boot spinner); and the global auth-failure handler must end the session.

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

import { restoreSession, registerAuthFailureHandler } from '$lib/api/client';
import * as authApi from '$lib/api/auth';
import { auth } from './auth';

describe('auth store session lifecycle (4.77, 6.89)', () => {
  beforeEach(() => {
    vi.mocked(restoreSession).mockReset();
    vi.mocked(restoreSession).mockResolvedValue(true); // refresh cookie is valid
    vi.mocked(authApi.me).mockReset();
    vi.mocked(authApi.logout).mockReset();
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
});
