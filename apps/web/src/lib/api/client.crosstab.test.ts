// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Refreshes and logouts of several tabs (R-0649). All tabs of an origin share the refresh cookie,
// and the server treats a second refresh with the same token as reuse, which ends every session
// of the user; a logout blocks the cookie, so a refresh that sends it after the logout counts as
// reuse too. Each tab here is its own instance of client.ts (vi.resetModules), so refreshInFlight
// is per tab, as in the browser; a fake LockManager shared by both stands in for the Web Locks
// of the origin.

import { describe, it, expect, afterEach, vi } from 'vitest';

type ClientModule = typeof import('./client');
type AuthModule = typeof import('./auth');

const LOCK_NAME = 'adminhelper-auth-refresh';
const REFRESH = '/api/auth/refresh';
const LOGOUT = '/api/auth/logout';

async function openTab(): Promise<ClientModule> {
  vi.resetModules();
  return import('./client');
}

// A tab whose auth.ts uses the client.ts instance of the same tab.
async function openAuthTab(): Promise<{ client: ClientModule; auth: AuthModule }> {
  vi.resetModules();
  const client = await import('./client');
  return { client, auth: await import('./auth') };
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

interface AuthServer {
  sent: () => string[];
  answer: (path: string, body: unknown, status?: number) => void;
}

// Every request answers only when the test says so; sent() lists the paths in the order the
// fetches went out.
function stubAuthServer(): AuthServer {
  const sent: string[] = [];
  const pending = new Map<string, Array<(res: Response) => void>>();
  vi.stubGlobal(
    'fetch',
    vi.fn((input: RequestInfo | URL) => {
      const path = String(input);
      sent.push(path);
      return new Promise<Response>((resolve) => {
        pending.set(path, [...(pending.get(path) ?? []), resolve]);
      });
    }),
  );
  return {
    sent: () => [...sent],
    answer: (path, body, status = 200) => {
      const next = pending.get(path)?.shift();
      if (!next) throw new Error(`no request to ${path} is waiting for an answer`);
      next(jsonResponse(body, status));
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

describe('logout across tabs', () => {
  afterEach(() => {
    Reflect.deleteProperty(navigator, 'locks');
    vi.unstubAllGlobals();
  });

  it('sends the logout of a tab only after the refresh of another tab has its answer', async () => {
    const locks = installLockManager();
    const server = stubAuthServer();
    const tabA = await openAuthTab();
    const tabB = await openAuthTab();

    const restoredA = tabA.client.restoreSession();
    await vi.waitFor(() => expect(server.sent()).toEqual([REFRESH]));
    const loggedOutB = tabB.auth.logout();
    // Give tab B every chance to send its logout while the refresh of tab A is open.
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(server.sent()).toEqual([REFRESH]);

    server.answer(REFRESH, { access_token: 'access-a' });
    await vi.waitFor(() => expect(server.sent()).toEqual([REFRESH, LOGOUT]));
    server.answer(LOGOUT, { detail: 'Abgemeldet' });

    await expect(restoredA).resolves.toBe(true);
    await expect(loggedOutB).resolves.toBeUndefined();
    expect(locks.requested).toEqual([LOCK_NAME, LOCK_NAME]);
  });

  it('sends the refresh of a tab only after the logout of another tab has its answer', async () => {
    installLockManager();
    const server = stubAuthServer();
    const tabA = await openAuthTab();
    const tabB = await openAuthTab();
    tabB.client.setAccessToken('access-b');

    const loggedOutB = tabB.auth.logout();
    await vi.waitFor(() => expect(server.sent()).toEqual([LOGOUT]));
    const restoredA = tabA.client.restoreSession();
    // Give tab A every chance to send its refresh while the logout of tab B is open.
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(server.sent()).toEqual([LOGOUT]);

    server.answer(LOGOUT, { detail: 'Abgemeldet' });
    await vi.waitFor(() => expect(server.sent()).toEqual([LOGOUT, REFRESH]));
    // The answer of the logout cleared the cookie, so the refresh has none to send.
    server.answer(REFRESH, { detail: 'Not authenticated' }, 401);

    await expect(loggedOutB).resolves.toBeUndefined();
    await expect(restoredA).resolves.toBe(false);
    expect(tabB.client.getAccessToken()).toBeNull();
  });

  it('sends the logout at once when the browser has no Web Locks', async () => {
    expect('locks' in navigator).toBe(false);
    const server = stubAuthServer();
    const tab = await openAuthTab();
    tab.client.setAccessToken('access-a');

    const loggedOut = tab.auth.logout();
    await vi.waitFor(() => expect(server.sent()).toEqual([LOGOUT]));
    server.answer(LOGOUT, { detail: 'Abgemeldet' });

    await expect(loggedOut).resolves.toBeUndefined();
    expect(tab.client.getAccessToken()).toBeNull();
  });

  it('clears the token and frees the lock when the logout fails', async () => {
    installLockManager();
    const server = stubAuthServer();
    const tabA = await openAuthTab();
    const tabB = await openAuthTab();
    tabA.client.setAccessToken('access-a');

    const loggedOutA = tabA.auth.logout();
    const restoredB = tabB.client.restoreSession();
    await vi.waitFor(() => expect(server.sent()).toEqual([LOGOUT]));
    server.answer(LOGOUT, { detail: 'boom' }, 500);

    await expect(loggedOutA).resolves.toBeUndefined();
    expect(tabA.client.getAccessToken()).toBeNull();
    // The lock is free again: the refresh waiting behind the failed logout goes out.
    await vi.waitFor(() => expect(server.sent()).toEqual([LOGOUT, REFRESH]));
    server.answer(REFRESH, { access_token: 'access-b' });
    await expect(restoredB).resolves.toBe(true);
  });

  it('never refreshes for an /auth/ path, so the logout under the lock cannot wait for itself', async () => {
    installLockManager();
    const server = stubAuthServer();
    const tab = await openAuthTab();
    tab.client.setAccessToken('access-a');

    const loggedOut = tab.auth.logout();
    await vi.waitFor(() => expect(server.sent()).toEqual([LOGOUT]));
    // 401 would start a refresh for any other path, which waits for the lock the logout holds.
    server.answer(LOGOUT, { detail: 'Not authenticated' }, 401);

    await expect(loggedOut).resolves.toBeUndefined();
    expect(server.sent()).toEqual([LOGOUT]);
  });

  it('does not refresh after a 401 from an /auth/ path outside the lock either', async () => {
    const server = stubAuthServer();
    const tab = await openAuthTab();
    tab.client.setAccessToken('access-a');

    const me = tab.auth.me();
    const failed = expect(me).rejects.toBeDefined();
    await vi.waitFor(() => expect(server.sent()).toEqual(['/api/auth/me']));
    server.answer('/api/auth/me', { detail: 'Not authenticated' }, 401);

    await failed;
    // Give a refresh every chance to start.
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(server.sent()).toEqual(['/api/auth/me']);
  });
});
