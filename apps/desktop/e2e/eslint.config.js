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
    rules: {
      'no-restricted-syntax': [
        'error',
        {
          selector:
            "CallExpression[callee.name='done'] > ObjectExpression > Property[key.name='error']",
          message:
            'Hand a rejection to done() as { rejected }, not { error }: webdriver takes a script ' +
            'result with an `error` key for a failed command (isSuccessfulResponse), retries it ' +
            "and throws a WebDriverError, so the text never reaches the spec's own check.",
        },
      ],
    },
  },
  {
    // The multiremote sessions of wdio.workspaces.conf.js, globals only in its specs.
    files: ['test/specs/**/*.workspaces.js'],
    languageOptions: {
      globals: {
        wsA: 'readonly',
        wsB: 'readonly',
      },
    },
  },
];
