// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Live desktop E2E for the SSE push pipeline: a notification injected into the
// hub appears in the bell in REAL TIME (server -> Redis -> Rust SSE client ->
// `notification` Tauri event -> store loadFeed -> badge), not via the 30s poll.
//
// Proving push vs. poll: activateNotifications() runs one loadFeed() at login
// and arms a 30s timer. We wait for the Rust SSE client to connect, then inject
// the event — the next poll is still ~25s away, so a badge appearing within a
// few seconds can ONLY be the push.

import { login, injectEvent } from '../lib/live.js';

describe('Notification bell — SSE push', () => {
  it('shows a pushed notification in real time (well under the 30s poll)', async () => {
    await login();

    // Fresh DB -> no unread badge yet.
    await browser.pause(500);
    await expect($('.notif-badge')).not.toBeExisting();

    // Give the Rust SSE client time to open + register the stream before the
    // event arrives (otherwise the push would land with no subscriber).
    await browser.pause(5000);

    const t0 = Date.now();
    const res = injectEvent('E2E SSE push notification');
    expect(res.notified).toBe(1); // admin (scope=all subscription) was resolved

    // The badge must appear fast — the next poll is ~25s away, so this proves push.
    await $('.notif-badge').waitForExist({ timeout: 15000 });
    const elapsed = Date.now() - t0;
    console.log(`[sse-e2e] badge appeared ${elapsed}ms after the event injection`);
    expect(elapsed).toBeLessThan(15000);

    // Open the panel and verify the pushed item is shown.
    await $('.notif-bell').click();
    await $('.notif-panel').waitForExist({ timeout: 5000 });
    const items = await $$('.notif-item');
    expect(items.length).toBeGreaterThan(0);
    await expect(items[0].$('.notif-item-title')).toHaveText('E2E SSE push', { containing: true });
  });
});
