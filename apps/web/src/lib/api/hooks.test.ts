// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('./client', () => ({ http: { post: vi.fn(() => Promise.resolve({})) } }));

import { http } from './client';
import { run } from './hooks';
import type { HookRunResult } from './types';

describe('hooks api', () => {
  beforeEach(() => vi.clearAllMocks());

  it('posts a manual run to the encoded hook id and returns the response unchanged', async () => {
    const response = { success: false, result: {}, logs: ['Fehler: x'], error: 'x' };
    vi.mocked(http.post).mockResolvedValueOnce(response);
    await expect(run('a/b')).resolves.toBe(response);
    expect(http.post).toHaveBeenCalledTimes(1);
    expect(http.post).toHaveBeenCalledWith('/api/hooks/a%2Fb/run', {});
  });

  // `npm run check` (svelte-check) type-checks this file: each directive below fails the check
  // as soon as its line stops being a type error, i.e. when HookRunResult drifts from /run.
  it('types HookRunResult as the response of /run', () => {
    const ok: HookRunResult = { success: true, result: { n: 1 }, logs: [] };
    // @ts-expect-error /run sends no output field
    expect(ok.output).toBeUndefined();
    // @ts-expect-error /run sends no exit_code field
    expect(ok.exit_code).toBeUndefined();
    // @ts-expect-error /run sends no duration_ms field
    expect(ok.duration_ms).toBeUndefined();

    // @ts-expect-error success is always in the response
    const noSuccess: HookRunResult = { result: {}, logs: [] };
    // @ts-expect-error result is always in the response
    const noResult: HookRunResult = { success: true, logs: [] };
    // @ts-expect-error logs is always in the response
    const noLogs: HookRunResult = { success: true, result: {} };
    expect([noSuccess, noResult, noLogs]).toHaveLength(3);
  });
});
