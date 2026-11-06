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
//
// The second journey follows one incident (R-1079): events of one key fold into
// it. A new one pings (toast), the detail of the center acknowledges it, a repeat
// only counts ×2 and pings nobody (no toast, and no push either: the poll brings
// the count), the recovery resolves it and pings the all-clear. The detail's
// buttons show the state, so the checks hold in either language.

import {
  login,
  injectEvent,
  ensureAllSubscription,
  clickItemByName,
  jsClick,
  textContentOf,
  texts,
} from "../lib/live.js";

// Over the 30s poll: whatever the push misses, the poll brings within this.
const POLL_BOUND = 45000;

async function toastsTitled(title) {
  return (await texts(".toast .title")).filter((t) => t === title).length;
}

async function dismissToasts() {
  for (const button of await $$(".toast .dismiss")) await jsClick(button);
  await browser.waitUntil(async () => (await $$(".toast")).length === 0, {
    timeout: 5000,
    timeoutMsg: "the toasts did not close",
  });
}

describe("Notification bell — SSE push", () => {
  it("shows a pushed notification in real time (well under the 30s poll)", async () => {
    await login();

    // Fresh DB -> no unread badge yet.
    await browser.pause(500);
    await expect($(".notif-badge")).not.toBeExisting();

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
        notified = injectEvent("E2E SSE push notification").notified;
        return notified >= 1 && (await $(".notif-badge").isExisting());
      },
      {
        timeout: 20000,
        interval: 1500,
        timeoutMsg: "the pushed notification never reached the bell within 20s",
      },
    );
    expect(notified).toBe(1); // admin (scope=all subscription) was the recipient
    const elapsed = Date.now() - t0;
    console.log(
      `[sse-e2e] badge appeared ${elapsed}ms after the first injection`,
    );
    expect(elapsed).toBeLessThan(30000); // under the poll interval → this is the push

    // Open the panel and verify the pushed item is shown. The rows render from
    // the feed store, which the panel-open path can still be refreshing — assert
    // with a bounded wait like the badge check above (a one-shot $$ raced it and
    // saw an empty list intermittently). A real regression still fails here: the
    // list never fills within 10s.
    await $(".notif-bell").click();
    await $(".notif-panel").waitForExist({ timeout: 5000 });
    await browser.waitUntil(async () => (await $$(".notif-item")).length > 0, {
      timeout: 10000,
      interval: 500,
      timeoutMsg:
        "the notification panel stayed empty although the bell showed unread items",
    });
    const items = await $$(".notif-item");
    await expect(items[0].$(".notif-item-title")).toHaveText("E2E SSE push", {
      containing: true,
    });
  });

  it("folds a keyed event into one incident: ack, a silent repeat ×2, the recovery", async () => {
    // bail stops the spec after a failed first journey, so this one follows a
    // passed one; run on its own (mocha grep) it logs in itself.
    if (!(await $(".sidebar-nav").isExisting())) await login();
    ensureAllSubscription();
    if (await $(".notif-panel").isExisting()) {
      await jsClick(await $(".notif-backdrop"));
    }
    await dismissToasts();

    const stamp = Date.now();
    const key = `e2e:incident:${stamp}`;
    const title = `E2E incident ${stamp}`;
    const event = { event_type: "e2e.incident", incident_key: key };

    // A new incident pings the admin: a toast.
    expect(injectEvent(title, "critical", event).notified).toBe(1);
    await browser.waitUntil(async () => (await toastsTitled(title)) === 1, {
      timeout: POLL_BOUND,
      interval: 500,
      timeoutMsg: "the new incident never showed a toast",
    });
    await dismissToasts();

    // From the bell into the center; the detail acknowledges it: resolving stays.
    await $(".notif-bell").click();
    await $(".notif-panel").waitForExist({ timeout: 5000 });
    await clickItemByName(".notif-item-main", ".notif-item-title", title);
    await $(".nc-detail .nd-ack").waitForExist({ timeout: 15000 });
    expect(await textContentOf(await $(".nc-detail .nd-title"))).toBe(title);
    await jsClick(await $(".nc-detail .nd-ack"));
    await $(".nc-detail .nd-ack").waitForExist({
      reverse: true,
      timeout: 15000,
    });
    await expect($(".nc-detail .nd-resolve")).toBeExisting();

    // A repeat folds in silently: nobody notified, the count turns ×2, no toast.
    expect(injectEvent(title, "critical", event).notified).toBe(0);
    await browser.waitUntil(
      async () =>
        (await $(".nc-detail .nd-count").isExisting()) &&
        (await textContentOf(await $(".nc-detail .nd-count"))) === "×2",
      {
        timeout: POLL_BOUND,
        interval: 1000,
        timeoutMsg: "the repeat never counted ×2 in the detail",
      },
    );
    // The poll that brought ×2 would have raised the toast first (loadFeed).
    expect(await toastsTitled(title)).toBe(0);

    // The recovery resolves it and pings the all-clear; the detail offers to reopen.
    const cleared = `${title} recovered`;
    const recovery = { ...event, new_status: "ok" };
    expect(injectEvent(cleared, "critical", recovery).notified).toBe(1);
    await browser.waitUntil(async () => (await toastsTitled(cleared)) === 1, {
      timeout: POLL_BOUND,
      interval: 500,
      timeoutMsg: "the all-clear never showed a toast",
    });
    await $(".nc-detail .nd-reopen").waitForExist({ timeout: 15000 });
    await expect($(".nc-detail .nd-resolve")).not.toBeExisting();
    await expect($(".nc-detail .nd-ack")).not.toBeExisting();
  });
});
