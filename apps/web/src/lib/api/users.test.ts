// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('./client', () => ({ http: { post: vi.fn(() => Promise.resolve({})) } }));

import { http } from './client';
import { mintEnrollToken } from './users';

describe('users api', () => {
  beforeEach(() => vi.clearAllMocks());

  it('mints an enrollment token for the user with the chosen validity', async () => {
    await mintEnrollToken('alice', 60);
    expect(http.post).toHaveBeenCalledTimes(1);
    expect(http.post).toHaveBeenCalledWith('/api/enrollment/token/for', {
      username: 'alice',
      ttl_minutes: 60,
    });
  });

  it('returns the grant as the server sent it', async () => {
    const grant = {
      token: 'tok',
      subjectId: 'alice',
      scope: 'access',
      browser: false,
      enrollPort: 8444,
      expiresAt: '2026-10-16T12:00:00.123456Z',
    };
    vi.mocked(http.post).mockResolvedValueOnce(grant);
    await expect(mintEnrollToken('alice', 1440)).resolves.toEqual(grant);
  });
});
