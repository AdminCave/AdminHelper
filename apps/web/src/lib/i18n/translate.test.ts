// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

import { describe, it, expect } from 'vitest';
import { tNow, language } from './index';

// The existing i18n.test only checks dictionary key parity; the actual translate logic — {var}
// interpolation (incl. null/undefined -> '') and the fallback to the key itself — was untested. A regex
// slip in the interpolation would render broken text app-wide with nothing to catch it (6.153).
// detect()/subscribe are typeof-guarded, so this runs in the node env without a localStorage stub.
describe('i18n tNow', () => {
  it('interpolates a {var} into the translated text', () => {
    language.set('de');
    const out = tNow('page.hooks.next', { time: '12:00' });
    expect(out).toContain('12:00');
    expect(out).not.toContain('{time}');
  });

  it('renders a null var as empty, never the literal placeholder or "null"', () => {
    language.set('de');
    const out = tNow('page.hooks.next', { time: null });
    expect(out).not.toContain('{time}');
    expect(out).not.toContain('null');
  });

  it('renders an undefined var as empty, never the literal placeholder', () => {
    language.set('de');
    const out = tNow('page.hooks.next', { time: undefined });
    expect(out).not.toContain('{time}');
    expect(out).not.toContain('undefined');
  });

  it('drops a placeholder whose var is absent from the vars object', () => {
    language.set('de');
    // text has {time}; vars supplies something else -> {time} resolves to '' (not left raw).
    expect(tNow('page.hooks.next', { other: 'x' })).not.toContain('{time}');
  });

  it('falls back to the key itself when it exists in no dictionary', () => {
    expect(tNow('does.not.exist.xyz', {})).toBe('does.not.exist.xyz');
  });
});
