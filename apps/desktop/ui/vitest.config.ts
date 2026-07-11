// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

import { defineConfig } from 'vitest/config';
import { svelte } from '@sveltejs/vite-plugin-svelte';
import { svelteTesting } from '@testing-library/svelte/vite';
import path from 'node:path';

export default defineConfig({
  // svelteTesting() resolves the browser build so tests can mount real
  // components (not just SSR), enabling component-level regression tests.
  plugins: [svelte(), svelteTesting()],
  resolve: {
    alias: {
      $lib: path.resolve(__dirname, './src/lib'),
      $modals: path.resolve(__dirname, './src/modals'),
    },
  },
  test: {
    environment: 'jsdom',
    globals: false,
    include: ['src/**/*.test.ts'],
    setupFiles: ['./vitest.setup.ts'],
    // @vitest/coverage-v8 is a devDependency but was never wired up, so the 0%-coverage blind spots
    // (connectFlow, stores) stayed invisible. `npm run test:coverage` now surfaces them. No threshold
    // gate here — enforcing one (and in CI) is a separate call once coverage is raised (6.122).
    coverage: {
      provider: 'v8',
      include: ['src/lib/**/*.ts'],
      exclude: ['src/lib/**/types.ts', 'src/lib/i18n/dictionaries.ts'],
    },
  },
});
