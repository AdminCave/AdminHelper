// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

/// <reference types="node" />

import { describe, it, expect, beforeEach } from 'vitest';
import { readFileSync, readdirSync, statSync } from 'fs';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';
import { get } from 'svelte/store';
import { t, language, setLanguage, tNow } from './index';
import { translations } from './dictionaries';

// src/lib/i18n -> src
const SRC_DIR = join(dirname(fileURLToPath(import.meta.url)), '..', '..');
// Keys assembled at runtime from a suffix (t(`prefix.${x}`)); grep can't see them.
const DYNAMIC_PREFIXES = ['notifPrefs.scope.', 'notifPrefs.sev.', 'settings.mode.'];

function collectUsedStrings(dir: string, acc: Set<string>): void {
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) collectUsedStrings(full, acc);
    else if ((entry.endsWith('.svelte') || entry.endsWith('.ts')) && entry !== 'dictionaries.ts') {
      for (const m of readFileSync(full, 'utf8').matchAll(/['"`]([a-zA-Z][a-zA-Z0-9._-]*)['"`]/g)) {
        acc.add(m[1]);
      }
    }
  }
}

describe('i18n engine', () => {
  beforeEach(() => {
    setLanguage('de');
  });

  it('translates known keys', () => {
    expect(get(t)('nav.dashboard')).toBe('Dashboard');
    expect(get(t)('settings.mode.local')).toBe('Lokal');
  });

  it('resolves correctly after switching language', () => {
    setLanguage('en');
    expect(get(t)('settings.mode.local')).toBe('Local');
  });

  it('replaces {placeholder} tokens with provided vars', () => {
    const translate = get(t);
    expect(translate('page.connections.count', { count: 5 })).toBe('5 Verbindung');
  });

  it('returns key itself when not found in any dict', () => {
    expect(get(t)('definitely.nonexistent.key.xyz')).toBe('definitely.nonexistent.key.xyz');
  });

  it('switches language reactively via the store', () => {
    const deLabel = get(t)('settings.mode.server');
    setLanguage('en');
    const enLabel = get(t)('settings.mode.server');
    expect(deLabel).toBe('Server');
    expect(enLabel).toBe('Server');
    // both are "Server" but the engine should not throw and store should update
    expect(get(language)).toBe('en');
  });

  it('normalizes unknown language to en', () => {
    setLanguage('fr-FR');
    expect(get(language)).toBe('en');
  });

  it('tNow resolves with current language', () => {
    setLanguage('de');
    expect(tNow('nav.dashboard')).toBe('Dashboard');
    setLanguage('en');
    expect(tNow('nav.dashboard')).toBe('Dashboard');
  });
});

describe('dictionary parity', () => {
  it('de and en dictionaries have exactly the same keys', () => {
    const deKeys = new Set(Object.keys(translations.de));
    const enKeys = new Set(Object.keys(translations.en));
    const missingInEn = [...deKeys].filter((k) => !enKeys.has(k)).sort();
    const missingInDe = [...enKeys].filter((k) => !deKeys.has(k)).sort();
    expect(missingInEn).toEqual([]);
    expect(missingInDe).toEqual([]);
  });

  // Guards against re-accumulating dead keys from the web frontend (audit 2.21).
  it('has no unused translation keys', () => {
    const used = new Set<string>();
    collectUsedStrings(SRC_DIR, used);
    const dead = Object.keys(translations.de).filter(
      (k) => !used.has(k) && !DYNAMIC_PREFIXES.some((p) => k.startsWith(p)),
    );
    expect(dead).toEqual([]);
  });
});
