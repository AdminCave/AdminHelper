// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

/// <reference types="node" />

// app.css still styles the old pages through global classes (.field, .btn, .tag …). In the
// bundle it comes after the component CSS, so a global rule that matches an element of the
// library wins at equal specificity: an FormField label in capitals, a second border around
// its input, a hover frame on a ghost button. jsdom loads no component <style>, but it does
// match selectors, so the test checks that no class-led global rule reaches the library.

import { afterAll, afterEach, beforeAll, describe, expect, it } from 'vitest';
import { cleanup, render } from '@testing-library/svelte';
import { createRawSnippet } from 'svelte';
import { readFileSync } from 'fs';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';
import { setLanguage } from '$lib/i18n';
import Button from './Button.svelte';
import Tag from './Tag.svelte';
import FormsHarness from './__fixtures__/FormsHarness.svelte';

const APP_CSS = readFileSync(
  join(dirname(fileURLToPath(import.meta.url)), '..', '..', 'styles', 'app.css'),
  'utf-8',
);

// Top-level rules whose selector list starts with a class; pseudo-elements are cut,
// Element.matches() does not take them.
const RULES = [...APP_CSS.matchAll(/^(\.[^{@]*)\{([^}]*)\}/gm)].map((m) => ({
  text: m[0],
  selectors: m[1]
    .split(',')
    .map((s) => s.trim().replace(/::[a-z-]+/g, ''))
    .filter(Boolean),
}));

const text = (s: string) => createRawSnippet(() => ({ render: () => `<span>${s}</span>` }));

let sheet: HTMLStyleElement;

beforeAll(() => {
  setLanguage('de');
  sheet = document.createElement('style');
  sheet.textContent = RULES.filter((r) => /^\.(field|btn|tag)\b/.test(r.selectors[0] ?? ''))
    .map((r) => r.text)
    .join('\n');
  document.head.append(sheet);
});

afterAll(() => sheet.remove());
afterEach(() => cleanup());

function renderLibrary(): HTMLElement[] {
  const roots = [
    render(FormsHarness).container,
    ...(['primary', 'secondary', 'ghost', 'accent', 'danger'] as const).map(
      (variant) => render(Button, { variant, children: text('Los') }).container,
    ),
    render(Tag, { children: text('prod') }).container,
  ];
  return roots.flatMap((c) => [...c.querySelectorAll<HTMLElement>('*')]);
}

describe('ui library vs. global app.css', () => {
  it('found the global rules it guards against', () => {
    expect(RULES.some((r) => r.selectors.includes('.field input'))).toBe(true);
    expect(RULES.some((r) => r.selectors.includes('.btn'))).toBe(true);
    expect(RULES.some((r) => r.selectors.includes('.tag'))).toBe(true);
  });

  it('no class-led global rule matches an element of the library', () => {
    const hits: string[] = [];
    for (const el of renderLibrary())
      for (const { selectors } of RULES)
        for (const sel of selectors) {
          let match: boolean;
          try {
            match = el.matches(sel);
          } catch {
            continue; // a selector jsdom cannot parse cannot hit in the test either
          }
          if (match) hits.push(`${sel} -> <${el.tagName.toLowerCase()} class="${el.className}">`);
        }
    expect(hits).toEqual([]);
  });

  it('a FormField label keeps its own case under the global field rule', () => {
    const { getByText } = render(FormsHarness);
    const field = getByText('Farbe').closest('div')!;
    expect(getComputedStyle(field).textTransform).not.toBe('uppercase');
  });
});
