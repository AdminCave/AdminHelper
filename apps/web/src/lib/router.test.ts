// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Hash router (6.88): the self-built router is core navigation infrastructure with subtle branches
// (readHash normalization, replace without a history push). vitest runs in the 'node' environment, so the module's import-time location/window
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
    const { path } = await importRouter();
    expect(get(path)).toBe('/servers');
  });

  it('defaults to /users when the hash is empty', async () => {
    stubLocation('');
    const { path } = await importRouter();
    expect(get(path)).toBe('/users');
  });

  it('replace updates the store via replaceState (no history push)', async () => {
    stubLocation('#/users');
    const { replace, path } = await importRouter();
    replace('/servers');
    expect(get(path)).toBe('/servers');
    expect(historyStub.replaceState).toHaveBeenCalledWith(null, '', '#/servers');
  });
});
