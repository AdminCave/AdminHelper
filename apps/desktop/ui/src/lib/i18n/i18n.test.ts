// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

import { describe, it, expect, beforeEach } from 'vitest';
import { get } from 'svelte/store';
import { t, language, setLanguage, tNow } from './index';

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
