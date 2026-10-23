// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

/// <reference types="node" />

// Theme init (R-0647). The server sends the SPA with `script-src 'self'` as a header, which
// blocks every inline script in index.html; the inline FOUC script never ran, so a reload
// fell back to dark. The init therefore lives in public/theme-init.js, loaded as a classic
// blocking script from <head>. The browser side (build + CSP header) is the E2E project
// chromium-build; this covers the contract of index.html and the script's logic.

import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { existsSync, readFileSync } from 'fs';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';

// src -> apps/web
const WEB_DIR = join(dirname(fileURLToPath(import.meta.url)), '..');
const INIT_SRC = '/theme-init.js';
const INIT_FILE = join(WEB_DIR, 'public', 'theme-init.js');

describe('index.html', () => {
  const doc = new DOMParser().parseFromString(
    readFileSync(join(WEB_DIR, 'index.html'), 'utf8'),
    'text/html',
  );

  it('has no inline script — every <script> loads a file', () => {
    const scripts = [...doc.querySelectorAll('script')];
    expect(scripts.length).toBeGreaterThan(0);
    for (const s of scripts) {
      expect(s.getAttribute('src'), s.outerHTML).toBeTruthy();
      expect(s.textContent?.trim(), s.outerHTML).toBe('');
    }
  });

  it('loads the theme script from <head> as a classic blocking script', () => {
    const init = doc.querySelector(`script[src="${INIT_SRC}"]`);
    expect(init).not.toBeNull();
    expect(init?.parentElement?.tagName).toBe('HEAD');
    // type="module", defer and async all postpone it past the first paint.
    expect(init?.hasAttribute('type')).toBe(false);
    expect(init?.hasAttribute('defer')).toBe(false);
    expect(init?.hasAttribute('async')).toBe(false);
    expect(existsSync(INIT_FILE)).toBe(true);
  });
});

describe('public/theme-init.js', () => {
  let original: PropertyDescriptor | undefined;

  function runInit(): void {
    new Function(readFileSync(INIT_FILE, 'utf8'))();
  }

  beforeEach(() => {
    original = Object.getOwnPropertyDescriptor(globalThis, 'localStorage');
    localStorage.clear();
    document.documentElement.removeAttribute('data-theme');
  });

  afterEach(() => {
    if (original) Object.defineProperty(globalThis, 'localStorage', original);
    localStorage.clear();
    document.documentElement.removeAttribute('data-theme');
  });

  it.each(['light', 'dark'])('applies a stored %s theme', (stored) => {
    localStorage.setItem('ah-theme', stored);
    runInit();
    expect(document.documentElement.getAttribute('data-theme')).toBe(stored);
  });

  it('ignores an unknown stored value (dark default, no attribute)', () => {
    localStorage.setItem('ah-theme', 'x');
    runInit();
    expect(document.documentElement.hasAttribute('data-theme')).toBe(false);
  });

  it('stays on the dark default when the storage getter throws', () => {
    // vitest exposes the jsdom globals as configurable accessors on globalThis; replace the
    // getter the way a browser with blocked site data behaves.
    Object.defineProperty(globalThis, 'localStorage', {
      configurable: true,
      get() {
        throw new DOMException('denied', 'SecurityError');
      },
    });
    // The stub must really throw, or the assertions below prove nothing.
    expect(() => localStorage).toThrow('denied');

    expect(runInit).not.toThrow();
    expect(document.documentElement.hasAttribute('data-theme')).toBe(false);
  });
});
