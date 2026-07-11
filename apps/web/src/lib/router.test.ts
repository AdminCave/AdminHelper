// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Hash router (6.88): the self-built router is core navigation infrastructure with subtle branches
// (readHash normalization, navigate's manual store-set on the already-active hash, replace without a
// history push). vitest runs in the 'node' environment, so the module's import-time location/window
// access is stubbed here (like client.test.ts stubs localStorage) rather than pulling in jsdom.

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { get } from 'svelte/store';

let historyStub: { replaceState: ReturnType<typeof vi.fn> };

function stubLocation(hash: string): { hash: string } {
  const loc = { hash };
  vi.stubGlobal('location', loc);
  return loc;
}

async function importRouter() {
  vi.resetModules();
  return import('./router');
}

describe('hash router (6.88)', () => {
  beforeEach(() => {
    // A no-op window so the module-level hashchange wiring doesn't throw on import.
    vi.stubGlobal('window', { addEventListener: vi.fn() });
    historyStub = { replaceState: vi.fn() };
    vi.stubGlobal('history', historyStub);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('readHash normalizes "#/servers" to "/servers" on init', async () => {
    stubLocation('#/servers');
    const { currentPath } = await importRouter();
    expect(currentPath()).toBe('/servers');
  });

  it('defaults to /users when the hash is empty', async () => {
    stubLocation('');
    const { currentPath } = await importRouter();
    expect(currentPath()).toBe('/users');
  });

  it('navigate to a new hash writes location.hash (normalizing a missing leading slash)', async () => {
    const loc = stubLocation('#/users');
    const { navigate } = await importRouter();
    navigate('servers'); // no leading slash -> /servers
    expect(loc.hash).toBe('/servers'); // location write (a real browser re-adds '#')
  });

  it('navigate on the already-active hash does not rewrite location.hash (the guard holds)', async () => {
    const loc = stubLocation('#/servers');
    const { navigate, currentPath } = await importRouter();
    navigate('/servers'); // already active -> else branch: _path.set, no location write
    expect(loc.hash).toBe('#/servers'); // NOT rewritten (this is what separates it from a new hash)
    expect(currentPath()).toBe('/servers');
  });

  it('replace updates the store via replaceState (no history push)', async () => {
    stubLocation('#/users');
    const { replace, currentPath } = await importRouter();
    replace('/servers');
    expect(currentPath()).toBe('/servers');
    expect(historyStub.replaceState).toHaveBeenCalledWith(null, '', '#/servers');
  });

  it('segments splits the path and drops empty parts', async () => {
    stubLocation('#/servers/42');
    const { segments } = await importRouter();
    expect(get(segments)).toEqual(['servers', '42']);
  });
});
