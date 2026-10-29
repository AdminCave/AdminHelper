// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// A refused command reaches the UI as an Error (R-0709): the backend's {code, message, status}
// as an IpcError, Tauri's own text refusals as a plain Error, anything else never as
// "[object Object]".

import { describe, it, expect, vi, beforeEach } from 'vitest';

const h = vi.hoisted(() => ({
  invoke: vi.fn(async (..._a: unknown[]): Promise<unknown> => undefined),
}));

vi.mock('@tauri-apps/api/core', () => ({ invoke: h.invoke }));

import { apiProxy } from './index';
import { IpcError, errCode, errMsg, errStatus } from '$lib/utils/errors';

async function refusalOf(raw: unknown): Promise<unknown> {
  h.invoke.mockRejectedValueOnce(raw);
  return apiProxy('POST', '/api/x').catch((e: unknown) => e);
}

beforeEach(() => {
  h.invoke.mockReset();
});

describe('bridge invoke refusals', () => {
  it('turns the backend refusal into an IpcError with code and status', async () => {
    const err = await refusalOf({
      code: 'ERR_HTTP',
      message: 'Template already assigned',
      status: 409,
    });
    expect(err).toBeInstanceOf(IpcError);
    expect(errMsg(err)).toBe('Template already assigned');
    expect(errCode(err)).toBe('ERR_HTTP');
    expect(errStatus(err)).toBe(409);
  });

  it("keeps Tauri's own text refusal as an Error with exactly that text", async () => {
    const text = 'invalid args `path` for command `api_proxy`: missing required key path';
    const err = await refusalOf(text);
    expect(err).toBeInstanceOf(Error);
    expect(err).not.toBeInstanceOf(IpcError);
    expect((err as Error).message).toBe(text);
    expect(errCode(err)).toBeUndefined();
  });

  it.each([[{ code: 5, message: 'x' }], [{ message: 'x' }]])(
    'makes no IpcError of a refusal without a string code (%j)',
    async (raw) => {
      const err = await refusalOf(raw);
      expect(err).toBeInstanceOf(Error);
      expect(err).not.toBeInstanceOf(IpcError);
      expect(errMsg(err)).not.toBe('[object Object]');
      expect(errMsg(err)).toContain('x');
    },
  );

  it.each([['409'], [42], [409.5]])(
    'takes no status that is not an HTTP status (%j)',
    async (status) => {
      const err = await refusalOf({ code: 'ERR_HTTP', message: 'm', status });
      expect(err).toBeInstanceOf(IpcError);
      expect(errStatus(err)).toBeUndefined();
    },
  );

  it('passes the answer of a command through', async () => {
    h.invoke.mockResolvedValueOnce({ ok: true });
    await expect(apiProxy('GET', '/api/x')).resolves.toEqual({ ok: true });
    expect(h.invoke).toHaveBeenCalledWith('api_proxy', {
      method: 'GET',
      path: '/api/x',
      body: undefined,
    });
  });
});
