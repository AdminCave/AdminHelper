// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

import { defineConfig } from 'vitest/config';
import { svelte } from '@sveltejs/vite-plugin-svelte';
import { svelteTesting } from '@testing-library/svelte/vite';
import path from 'node:path';

// jsdom + @testing-library/svelte (wie apps/desktop/ui), damit neben der reinen
// Logik in src/lib/{utils,stores} auch Komponenten real gemountet und interagiert
// werden können — eine schnelle Unit-Ebene unter den Playwright-Journeys (6.94).
export default defineConfig({
  plugins: [svelte(), svelteTesting()],
  resolve: {
    // Mirror vite.config.ts so component tests can resolve $modals/* imports too —
    // the modals are exactly the components 6.94 targets (HookModal, KeyRevealModal, …).
    alias: {
      $lib: path.resolve(__dirname, './src/lib'),
      $modals: path.resolve(__dirname, './src/modals'),
    },
  },
  test: {
    environment: 'jsdom',
    include: ['src/**/*.test.ts'],
    setupFiles: ['./vitest.setup.ts'],
  },
});
