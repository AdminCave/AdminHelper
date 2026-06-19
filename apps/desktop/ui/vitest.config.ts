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
  },
});
