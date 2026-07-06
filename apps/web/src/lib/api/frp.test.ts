// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

import { describe, it, expect, vi, beforeEach } from 'vitest';

// The text/blob fetchers go through requestRaw — the shared 401-refresh client (8201a84), so the
// finding's "own fetch path without refresh" premise is stale. What was untested is fetchOk's
// error-detail parsing on a non-ok response; pin that here (6.86).
const h = vi.hoisted(() => ({ requestRaw: vi.fn() }));
vi.mock('./client', () => ({
  http: { get: vi.fn(), post: vi.fn(), put: vi.fn() },
  requestRaw: h.requestRaw,
}));

import { getFrpsToml, getBulkZip } from './frp';

describe('frp text/blob fetchers (6.86)', () => {
  beforeEach(() => vi.clearAllMocks());

  it('throws with the server detail on a non-ok response', async () => {
    h.requestRaw.mockResolvedValue(
      new Response(JSON.stringify({ detail: 'token expired' }), { status: 401 }),
    );
    await expect(getFrpsToml()).rejects.toThrow('token expired');
  });

  it('falls back to HTTP <status> when the body carries no detail', async () => {
    h.requestRaw.mockResolvedValue(new Response('nope', { status: 500 }));
    await expect(getBulkZip()).rejects.toThrow('HTTP 500');
  });
});
