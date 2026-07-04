// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

import js from '@eslint/js';
import globals from 'globals';

export default [
  {
    ignores: ['node_modules/**'],
  },
  js.configs.recommended,
  {
    languageOptions: {
      ecmaVersion: 2023,
      sourceType: 'module',
      globals: {
        ...globals.node,
        ...globals.mocha,
        // document/window appear inside browser.execute() callbacks (run in the
        // webview, serialized from here) — the file itself runs in Node.
        ...globals.browser,
        // WebdriverIO test-runner globals (injected by @wdio/*).
        $: 'readonly',
        $$: 'readonly',
        browser: 'readonly',
        expect: 'readonly',
      },
    },
  },
];
