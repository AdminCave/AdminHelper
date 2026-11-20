// SPDX-FileCopyrightText: Kevin Stenzel
// SPDX-License-Identifier: GPL-3.0-or-later

import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

// A browser loads an SVG favicon as XML and drops the whole file on the first parse error (R-1658):
// a `<` inside the CSS comment once did that and left the app without an icon.
describe('public/logo.svg', () => {
  it('is well-formed XML with the logo path', () => {
    const svg = readFileSync(resolve(process.cwd(), 'public/logo.svg'), 'utf8');
    const doc = new DOMParser().parseFromString(svg, 'image/svg+xml');
    expect(doc.getElementsByTagName('parsererror')).toHaveLength(0);
    expect(doc.documentElement.tagName).toBe('svg');
    expect(doc.getElementsByTagName('path')).toHaveLength(1);
  });
});
