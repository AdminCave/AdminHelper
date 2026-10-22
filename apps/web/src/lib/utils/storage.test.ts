// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Storage helpers (R-0654). With site data blocked, the localStorage getter itself throws a
// SecurityError; client.ts and i18n touch storage at import time, so an unguarded access
// rejected the import of main.ts and left a blank page instead of the login form.

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { get } from 'svelte/store';
import { storageGet, storageRemove, storageSet } from './storage';

let original: PropertyDescriptor | undefined;
let getterHits = 0;

// vitest exposes the jsdom globals as configurable accessors on globalThis; replace the
// getter the way a browser with blocked site data behaves.
function blockStorage(): void {
  Object.defineProperty(globalThis, 'localStorage', {
    configurable: true,
    get() {
      getterHits++;
      throw new DOMException('denied', 'SecurityError');
    },
  });
}

describe('storage helpers', () => {
  beforeEach(() => {
    original = Object.getOwnPropertyDescriptor(globalThis, 'localStorage');
    getterHits = 0;
    localStorage.clear();
  });

  afterEach(() => {
    if (original) Object.defineProperty(globalThis, 'localStorage', original);
    localStorage.clear();
  });

  it('passes reads, writes and removals through to a working storage', () => {
    storageSet('ah-test', 'v');
    expect(localStorage.getItem('ah-test')).toBe('v');
    expect(storageGet('ah-test')).toBe('v');
    storageRemove('ah-test');
    expect(localStorage.getItem('ah-test')).toBeNull();
    expect(storageGet('ah-test')).toBeNull();
  });

  it('never throws when the localStorage getter throws a SecurityError', () => {
    blockStorage();
    // The stub must really throw, or the assertions below prove nothing.
    expect(() => localStorage).toThrow('denied');
    getterHits = 0;

    expect(storageGet('ah-test')).toBeNull();
    expect(() => storageSet('ah-test', 'v')).not.toThrow();
    expect(() => storageRemove('ah-test')).not.toThrow();
    expect(getterHits).toBe(3);
  });

  it('lets client and i18n import with storage blocked; the language comes from the browser', async () => {
    blockStorage();
    vi.resetModules();

    await expect(import('$lib/api/client')).resolves.toBeDefined();
    await expect(import('$lib/i18n')).resolves.toBeDefined();
    // Both modules touch storage at import time, so the blocked getter was reached.
    expect(getterHits).toBeGreaterThan(0);

    const { language } = await import('$lib/i18n');
    const expected = (navigator.language || '').substring(0, 2) === 'en' ? 'en' : 'de';
    expect(get(language)).toBe(expected);
  });
});
