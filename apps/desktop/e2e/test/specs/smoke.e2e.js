// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Smoke E2E: prove the whole chain works — the Tauri window opens, loads the
// embedded Svelte frontend, and mounts it. This is the cheapest meaningful
// end-to-end check and needs NO backend (it asserts only the launch + render,
// which happen before any server call). The live "create a tunnel and test it"
// flow — which needs the real stack (see scripts/tests/integration_stack_test.sh)
// plus frpc — is the next increment built on this harness.

describe('AdminHelper desktop app', () => {
  before(async () => {
    // Wait for the embedded frontend to load and Svelte to mount before
    // asserting — the webview takes a beat to render after the session starts.
    await browser.waitUntil(
      async () =>
        browser.execute(
          () =>
            document.readyState === 'complete' &&
            !!document.querySelector('#app')?.firstElementChild,
        ),
      { timeout: 20000, timeoutMsg: 'embedded frontend did not load / Svelte did not mount' },
    );
  });

  it('opens a window titled AdminHelper', async () => {
    expect(await browser.getTitle()).toBe('AdminHelper');
  });

  it('mounts the Svelte app into #app', async () => {
    await expect($('#app')).toExist();
  });
});
