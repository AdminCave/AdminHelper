// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// arch-monitoring-neu-p0 T1 (R-1558): the mockup must never ship. `vite build` builds the
// index.html entry only as long as the config names no further input, and the product reaches
// the mockup only if a product source imports it.

import { describe, expect, it } from 'vitest';
import { readFileSync, readdirSync } from 'fs';
import { fileURLToPath } from 'url';
import { dirname, join, relative } from 'path';

const HERE = dirname(fileURLToPath(import.meta.url));
const SRC = join(HERE, '..', '..');
const UI = join(SRC, '..');
// Static (`from '…'`), side-effect (`import '…'`) and dynamic (`import('…')`) imports.
const IMPORTS_MOCKUP = /(?:\bfrom\s+|\bimport\s*\(?\s*)['"][^'"]*mockups\//;

function sources(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((e) => {
    const p = join(dir, e.name);
    if (e.isDirectory()) return p === join(SRC, 'mockups') ? [] : sources(p);
    return /\.(svelte|ts)$/.test(e.name) ? [p] : [];
  });
}

describe('mockup isolation', () => {
  it('vite.config.ts names no build input besides index.html', () => {
    const config = readFileSync(join(UI, 'vite.config.ts'), 'utf-8');
    expect(config).not.toMatch(/rollupOptions|rolldownOptions|\binput\s*:/);
    expect(config).not.toMatch(/mockup/);
  });

  it('index.html loads the product entry, not the mockup', () => {
    const html = readFileSync(join(UI, 'index.html'), 'utf-8');
    expect(html).toContain('src="/src/main.ts"');
    expect(html).not.toMatch(/mockup/);
  });

  it('the import guard sees static, side-effect and dynamic imports', () => {
    for (const line of [
      "import X from './mockups/monitoring-neu/model';",
      "import '../mockups/monitoring-neu/main';",
      "const m = await import('./mockups/monitoring-neu/main');",
    ])
      expect(IMPORTS_MOCKUP.test(line), line).toBe(true);
    expect(IMPORTS_MOCKUP.test("import X from './lib/monitoring';")).toBe(false);
  });

  it('no product source imports from src/mockups', () => {
    const offenders = sources(SRC)
      .filter((f) => IMPORTS_MOCKUP.test(readFileSync(f, 'utf-8')))
      .map((f) => relative(SRC, f));
    expect(offenders).toEqual([]);
  });

  it('mockup.html loads the mockup entry', () => {
    const html = readFileSync(join(UI, 'mockup.html'), 'utf-8');
    expect(html).toContain('src="/src/mockups/monitoring-neu/main.ts"');
  });
});
