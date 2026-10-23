// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Refreshes of several tabs (R-0649). All tabs of an origin share the refresh cookie, and the
// server treats a second refresh with the same token as reuse, which ends every session of the
// user. Each tab here is its own instance of client.ts (vi.resetModules), so refreshInFlight
// is per tab, as in the browser; a fake LockManager shared by both stands in for the Web Locks
// of the origin.

import { describe, it, expect, afterEach, vi } from 'vitest';

type ClientModule = typeof import('./client');

const LOCK_NAME = 'adminhelper-auth-refresh';

async function openTab(): Promise<ClientModule> {
  vi.resetModules();
  return import('./client');
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

// A lock is granted once the callback of the previous request for the same name has settled,
// in the order of the requests, like an exclusive Web Lock.
function installLockManager(): { requested: string[] } {
  const requested: string[] = [];
  const tails = new Map<string, Promise<unknown>>();
  const request = (name: string, callback: (lock: Lock | null) => unknown): Promise<unknown> => {
    requested.push(name);
    const lock: Lock = { name, mode: 'exclusive' };
    const run = (tails.get(name) ?? Promise.resolve()).then(() => callback(lock));
    const released = run.catch(() => undefined);
    tails.set(name, released);
    return run;
  };
  Object.defineProperty(navigator, 'locks', { value: { request }, configurable: true });
  return { requested };
}

interface RefreshServer {
  sent: () => number;
  maxOpen: () => number;
  answer: (accessToken: string) => void;
}

// /api/auth/refresh answers only when the test says so, in the order the fetches came in.
function stubRefreshServer(): RefreshServer {
  const pending: Array<(res: Response) => void> = [];
  let sent = 0;
  let open = 0;
  let maxOpen = 0;
  vi.stubGlobal(
    'fetch',
    vi.fn((input: RequestInfo | URL) => {
      if (String(input) !== '/api/auth/refresh') {
        return Promise.resolve(jsonResponse({ detail: 'unexpected' }, 500));
      }
      sent += 1;
      open += 1;
      maxOpen = Math.max(maxOpen, open);
      return new Promise<Response>((resolve) => {
        pending.push((res) => {
          open -= 1;
          resolve(res);
        });
      });
    }),
  );
  return {
    sent: () => sent,
    maxOpen: () => maxOpen,
    answer: (accessToken) => {
      const next = pending.shift();
      if (!next) throw new Error('no refresh is waiting for an answer');
      next(jsonResponse({ access_token: accessToken }));
    },
  };
}

describe('refresh across tabs', () => {
  afterEach(() => {
    Reflect.deleteProperty(navigator, 'locks');
    vi.unstubAllGlobals();
  });

  it('sends the refresh of a second tab only after the first one has its answer', async () => {
    installLockManager();
    const server = stubRefreshServer();
    const tabA = await openTab();
    const tabB = await openTab();

    const restoredA = tabA.restoreSession();
    const restoredB = tabB.restoreSession();

    await vi.waitFor(() => expect(server.sent()).toBe(1));
    // Give tab B every chance to send its own refresh while the first one is open.
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(server.sent()).toBe(1);

    server.answer('access-a');
    await vi.waitFor(() => expect(server.sent()).toBe(2));
    server.answer('access-b');

    await expect(Promise.all([restoredA, restoredB])).resolves.toEqual([true, true]);
    expect(server.maxOpen()).toBe(1);
    expect(tabA.getAccessToken()).toBe('access-a');
    expect(tabB.getAccessToken()).toBe('access-b');
  });

  it('asks for the lock adminhelper-auth-refresh once per tab', async () => {
    const locks = installLockManager();
    const server = stubRefreshServer();
    const tabA = await openTab();
    const tabB = await openTab();

    // Two refreshes in tab A are still bundled into one inside the tab.
    const restored = [tabA.restoreSession(), tabA.restoreSession(), tabB.restoreSession()];
    await vi.waitFor(() => expect(server.sent()).toBe(1));
    server.answer('access-a');
    await vi.waitFor(() => expect(server.sent()).toBe(2));
    server.answer('access-b');

    await expect(Promise.all(restored)).resolves.toEqual([true, true, true]);
    expect(locks.requested).toEqual([LOCK_NAME, LOCK_NAME]);
  });

  it('refreshes within the tab when the browser has no Web Locks', async () => {
    expect('locks' in navigator).toBe(false);
    const server = stubRefreshServer();
    const tab = await openTab();

    const restored = tab.restoreSession();
    await vi.waitFor(() => expect(server.sent()).toBe(1));
    server.answer('access-a');

    await expect(restored).resolves.toBe(true);
    expect(server.sent()).toBe(1);
    expect(tab.getAccessToken()).toBe('access-a');
  });
});
