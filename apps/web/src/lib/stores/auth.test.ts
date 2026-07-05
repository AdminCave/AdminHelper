// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Auth store hydrate (4.77): a transient /me error must not destroy a still-valid session by
// logging out server-side; only a real auth failure (401/403) should.

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { ApiError } from '$lib/api/types';

vi.mock('$lib/api/client', () => ({
  restoreSession: vi.fn(),
  registerAuthFailureHandler: vi.fn(),
}));
vi.mock('$lib/api/auth', () => ({
  me: vi.fn(),
  logout: vi.fn(),
  login: vi.fn(),
}));

import { restoreSession } from '$lib/api/client';
import * as authApi from '$lib/api/auth';
import { auth } from './auth';

describe('auth hydrate (4.77)', () => {
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
});
