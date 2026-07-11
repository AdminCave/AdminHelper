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

import { login, injectEvent, ensureAllSubscription } from '../lib/live.js';

describe('Notification bell — SSE push', () => {
  it('shows a pushed notification in real time (well under the 30s poll)', async () => {
    await login();

    // Fresh DB -> no unread badge yet.
    await browser.pause(500);
    await expect($('.notif-badge')).not.toBeExisting();

    // A fresh admin carries no subscription, so the hub resolves 0 recipients and
    // the push has no destination — seed a scope=all subscription first (4.32).
    ensureAllSubscription();

    // Retry the inject until the badge appears, rather than a fixed pause that raced
    // the (variably slow, headless) SSE connect and dropped the event (4.32). Each
    // inject now resolves the admin (subscription seeded), so the first one the
    // connected client receives paints the badge; the badge landing well before the
    // ~30s poll is what proves this is the push, not the poll.
    const t0 = Date.now();
    let notified = 0;
    await browser.waitUntil(
      async () => {
        notified = injectEvent('E2E SSE push notification').notified;
        return notified >= 1 && (await $('.notif-badge').isExisting());
      },
      {
        timeout: 20000,
        interval: 1500,
        timeoutMsg: 'the pushed notification never reached the bell within 20s',
      },
    );
    expect(notified).toBe(1); // admin (scope=all subscription) was the recipient
    const elapsed = Date.now() - t0;
    console.log(`[sse-e2e] badge appeared ${elapsed}ms after the first injection`);
    expect(elapsed).toBeLessThan(30000); // under the poll interval → this is the push

    // Open the panel and verify the pushed item is shown.
    await $('.notif-bell').click();
    await $('.notif-panel').waitForExist({ timeout: 5000 });
    const items = await $$('.notif-item');
    expect(items.length).toBeGreaterThan(0);
    await expect(items[0].$('.notif-item-title')).toHaveText('E2E SSE push', { containing: true });
  });
});
