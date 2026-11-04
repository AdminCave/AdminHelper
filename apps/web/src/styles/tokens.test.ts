// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// A misspelled custom property does not fail anywhere: var() falls back to the
// browser default and the page just looks wrong. These tests pin the DS token set
// of global.css (AdminCave/DesignSystem@244e890, as in the desktop's app.css) and the old AH names that alias it.
import { describe, expect, it } from 'vitest';
import { readFileSync } from 'fs';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';

const CSS = readFileSync(join(dirname(fileURLToPath(import.meta.url)), 'global.css'), 'utf-8');

function block(selector: string): Map<string, string> {
  const start = CSS.indexOf(`${selector} {`);
  expect(start, `${selector} block`).toBeGreaterThanOrEqual(0);
  const body = CSS.slice(start, CSS.indexOf('\n}', start));
  const decls = new Map<string, string>();
  for (const m of body.matchAll(/^\s*(--[a-z0-9-]+):\s*([^;]+);/gm)) decls.set(m[1], m[2].trim());
  return decls;
}

const dark = block(':root');
const light = block(":root[data-theme='light']");

// Tokens whose value differs between the themes: both blocks must set them.
const THEMED = [
  '--bg',
  '--bg-subtle',
  '--surface',
  '--surface-raised',
  '--surface-inset',
  '--surface-hover',
  '--surface-active',
  '--border',
  '--border-strong',
  '--border-faint',
  '--text',
  '--text-strong',
  '--text-muted',
  '--text-subtle',
  '--text-inverse',
  '--accent',
  '--accent-hover',
  '--accent-muted',
  '--accent-border',
  '--link',
  '--fill-solid',
  '--fill-solid-hover',
  '--fill-solid-text',
  ...['success', 'warning', 'danger', 'info'].flatMap((s) => [
    `--${s}`,
    `--${s}-bg`,
    `--${s}-border`,
  ]),
  '--shadow-sm',
  '--shadow-md',
  '--shadow-lg',
  '--shadow-pop',
  '--ring',
];

// Theme-independent tokens: set once in :root, inherited by the light theme.
const SHARED = [
  '--ring-width',
  '--ring-shadow',
  ...['xs', 'sm', 'md', 'lg', 'xl', '2xl', 'pill', 'field'].map((r) => `--radius-${r}`),
  ...['instant', 'fast', 'base', 'slow'].map((d) => `--dur-${d}`),
  '--ease-out',
  '--ease-in-out',
  '--ease-standard',
  ...[1, 2, 3, 4, 5, 6, 8, 10, 12, 16].map((n) => `--space-${n}`),
];

const ALIASES = ['--border-hover', '--hover', ...[2, 3, 4, 5, 6, 7].map((n) => `--sp-${n}`)];

describe('global.css design tokens', () => {
  it.each(THEMED)('%s is set in the dark and the light block', (name) => {
    expect(dark.has(name), `:root ${name}`).toBe(true);
    expect(light.has(name), `light ${name}`).toBe(true);
  });

  it.each(SHARED)('%s is set in :root', (name) => {
    expect(dark.has(name)).toBe(true);
  });

  it.each(ALIASES)('old name %s aliases a defined DS token', (name) => {
    const m = /^var\((--[a-z0-9-]+)\)$/.exec(dark.get(name) ?? '');
    expect(m, `${name} = ${dark.get(name)}`).not.toBeNull();
    expect(dark.has(m![1]), `${name} -> ${m![1]}`).toBe(true);
    expect(ALIASES).not.toContain(m![1]);
  });

  it('the light block overrides no alias, so aliases follow the theme', () => {
    for (const name of ALIASES) expect(light.has(name), name).toBe(false);
  });

  it('every var() inside the token blocks points at a token of :root', () => {
    for (const decls of [dark, light])
      for (const [name, value] of decls)
        for (const ref of value.matchAll(/var\((--[a-z0-9-]+)\)/g))
          expect(dark.has(ref[1]), `${name} -> ${ref[1]}`).toBe(true);
  });

  it('reduced motion zeroes every duration', () => {
    const media = /@media \(prefers-reduced-motion: reduce\) \{\s*:root \{([^}]*)\}/.exec(CSS);
    expect(media).not.toBeNull();
    for (const d of ['instant', 'fast', 'base', 'slow'])
      expect(media![1]).toMatch(new RegExp(`--dur-${d}: 0ms;`));
  });

  it('focus-visible draws the DS ring as outline without beating page rules', () => {
    // An outline survives class rules that set their own box-shadow.
    expect(CSS).toMatch(
      /:where\(:focus-visible\) \{[^}]*outline: var\(--ring-width\) solid var\(--ring\);/,
    );
  });
});
