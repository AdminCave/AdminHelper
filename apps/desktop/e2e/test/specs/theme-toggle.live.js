// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Live: the sidebar-footer theme toggle flips dark<->light (data-theme + the app
// background) and the choice survives a reload — the FOUC inline <head> script
// re-applies the persisted theme before the first paint. Orchestrated by
// scripts/tests/desktop_e2e_*.sh (crabbox_iter.sh --desktop theme-toggle.live.js).

import { login } from '../lib/live.js';

describe('Theme toggle', () => {
  it('flips dark<->light from the sidebar footer and survives a reload', async () => {
    await login();

    // default = dark (no explicit data-theme attribute, or "dark")
    const initial = await browser.execute(() => document.documentElement.dataset.theme ?? null);
    expect(initial === null || initial === 'dark').toBe(true);

    // The theme toggle is the only sidebar-footer item carrying an aria-label
    // (settings has only a title; nav items only titles) — language-independent.
    const toggle = await $('.sidebar-bottom .sidebar-item[aria-label]');
    await toggle.waitForExist({ timeout: 15000 });
    await toggle.click();

    await browser.waitUntil(
      async () => (await browser.execute(() => document.documentElement.dataset.theme)) === 'light',
      { timeout: 5000, timeoutMsg: 'theme did not switch to light after toggle' },
    );
    // light tokens are actually active: pure-white app background
    const bg = await browser.execute(() => getComputedStyle(document.body).backgroundColor);
    expect(bg).toBe('rgb(255, 255, 255)');

    // survives a reload — the FOUC <head> script re-applies the persisted theme
    await browser.refresh();
    await $('.sidebar-nav, .login-card').waitForExist({ timeout: 20000 });
    const afterReload = await browser.execute(() => document.documentElement.dataset.theme);
    expect(afterReload).toBe('light');
  });
});
