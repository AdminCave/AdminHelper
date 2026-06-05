// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

import { defineConfig } from 'vitest/config';
import path from 'node:path';

// Schlankes Unit-Test-Setup: nur reine Logik in src/lib/{utils,stores}.
// Kein jsdom — die getesteten Module brauchen kein DOM.
export default defineConfig({
  resolve: {
    alias: {
      $lib: path.resolve(__dirname, './src/lib'),
    },
  },
  test: {
    environment: 'node',
    include: ['src/lib/**/*.test.ts'],
  },
});
