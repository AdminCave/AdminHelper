// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

/// <reference types="node" />

import { describe, it, expect } from 'vitest';
import { readFileSync, readdirSync, statSync } from 'fs';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';
import { translations } from './dictionaries';

// src/lib/i18n -> src
const SRC_DIR = join(dirname(fileURLToPath(import.meta.url)), '..', '..');
// Keys assembled at runtime from a suffix (t(`hook.event.${x}`)); grep can't see them.
const DYNAMIC_PREFIXES = ['hook.event.'];

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

describe('dictionary parity', () => {
  it('de and en dictionaries have exactly the same keys', () => {
    const deKeys = new Set(Object.keys(translations.de));
    const enKeys = new Set(Object.keys(translations.en));
    const missingInEn = [...deKeys].filter((k) => !enKeys.has(k)).sort();
    const missingInDe = [...enKeys].filter((k) => !deKeys.has(k)).sort();
    expect(missingInEn).toEqual([]);
    expect(missingInDe).toEqual([]);
  });

  // Guards against re-accumulating dead keys from the 1:1 frontend port (2.53).
  it('has no unused translation keys', () => {
    const used = new Set<string>();
    collectUsedStrings(SRC_DIR, used);
    const dead = Object.keys(translations.de).filter(
      (k) => !used.has(k) && !DYNAMIC_PREFIXES.some((p) => k.startsWith(p)),
    );
    expect(dead).toEqual([]);
  });
});
