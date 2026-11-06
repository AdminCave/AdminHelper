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

// Stands in for Tauri's Channel: what the backend sends on it reaches `onmessage`.
vi.mock('@tauri-apps/api/core', () => ({
  invoke: h.invoke,
  Channel: class {
    constructor(public onmessage: (message: unknown) => void = () => {}) {}
  },
}));

import { apiProxy, terminalBroadcast, terminalOpenSsh, terminalWrite } from './index';
import type { Connection, TerminalExit } from './types';
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

describe('bridge terminal', () => {
  const connection: Connection = {
    id: 'c1',
    name: 'Box',
    kind: 'ssh',
    host: '192.0.2.10',
    port: 22,
    tags: [],
    trustCert: false,
  };

  it('opens a session with a channel whose messages reach the caller', async () => {
    h.invoke.mockResolvedValueOnce(7);
    const seen: unknown[] = [];
    await expect(terminalOpenSsh(connection, 120, 40, (m) => seen.push(m))).resolves.toBe(7);
    expect(h.invoke).toHaveBeenCalledTimes(1);
    const [cmd, args] = h.invoke.mock.calls[0] as [string, Record<string, unknown>];
    expect(cmd).toBe('terminal_open_ssh');
    expect(args).toMatchObject({ connection, cols: 120, rows: 40 });
    const output = args.output as { onmessage: (message: unknown) => void };
    const bytes = new Uint8Array([104, 105]).buffer;
    const end: TerminalExit = { exitCode: 0 };
    output.onmessage(bytes);
    output.onmessage(end);
    expect(seen).toEqual([bytes, end]);
  });

  it('sends typed bytes as the list of numbers a Vec<u8> takes', async () => {
    await terminalWrite(7, new Uint8Array([3, 13, 255]));
    expect(h.invoke).toHaveBeenCalledWith('terminal_write', { id: 7, data: [3, 13, 255] });
  });

  it('broadcasts the bytes without a session id and passes the count on', async () => {
    h.invoke.mockResolvedValueOnce(2);
    await expect(terminalBroadcast(new Uint8Array([108, 115, 10]))).resolves.toBe(2);
    expect(h.invoke).toHaveBeenCalledWith('terminal_broadcast', { data: [108, 115, 10] });
  });
});
