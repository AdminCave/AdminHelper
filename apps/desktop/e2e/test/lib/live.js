// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Shared helpers for the live (real-stack) desktop specs: login + Infrastructure
// navigation + a few robust click/read primitives. Selectors are by structure
// (not i18n text) so they stay language-independent. All three editor modals
// (server / server-connection / tunnel) share the `.editor-overlay` container,
// so modal interactions are scoped to it.

import { execFileSync } from 'node:child_process';

export const SERVER_URL = process.env.AH_SERVER_URL;
export const USER = process.env.AH_ADMIN_USER;
export const PASS = process.env.AH_ADMIN_PASS;

export async function login() {
  await $('.login-card').waitForExist({ timeout: 20000 });
  const inputs = await $$('.login-card input'); // serverUrl, username, password
  await inputs[0].setValue(SERVER_URL);
  await inputs[1].setValue(USER);
  await inputs[2].setValue(PASS);
  await browser.keys('Enter');
  await $('.sidebar-nav').waitForExist({ timeout: 20000 });
}

// Inject one event into the hub from the test runner (Node context, not the
// webview — the webview can't reach the self-signed gateway). Runs curl with -k;
// MONITOR_API_KEY comes from the env the orchestration script exports. Returns
// the parsed { notified: N } so a spec can assert the admin was a recipient.
export function injectEvent(title, severity = 'critical') {
  const out = execFileSync(
    'curl',
    [
      '-sk',
      '-X',
      'POST',
      `${SERVER_URL}/api/internal/events`,
      '-H',
      `X-Internal-Key: ${process.env.MONITOR_API_KEY}`,
      '-H',
      'Content-Type: application/json',
      '-d',
      JSON.stringify({ event_type: 'e2e.sse.push', severity, category: 'monitoring', title }),
    ],
    { encoding: 'utf8' },
  );
  return JSON.parse(out);
}

export async function gotoInfrastructure() {
  const nav = await $$('.sidebar-nav .sidebar-item'); // dashboard(0), connections(1), infrastructure(2)
  await nav[2].click();
  await $('.srv-item').waitForExist({ timeout: 15000 }); // the seeded server auto-selects
}

// Server-detail tabs: overview(0), connections(1), tunnels(2).
export async function openServerTab(index) {
  await $('.srv-tab').waitForExist({ timeout: 15000 });
  const tabs = await $$('.srv-tab');
  await tabs[index].click();
}

// JS .click() bypasses the WebDriver hit-test — the fixed status bar overlaps
// the modal's bottom action row, so a coordinate click is intercepted.
export async function jsClick(el) {
  await browser.execute((node) => node.click(), el);
}

export async function clickInModal(selector) {
  await jsClick(await $(`.editor-overlay ${selector}`));
}

// Text of every element matching `selector`.
export async function texts(selector) {
  const out = [];
  for (const el of await $$(selector)) {
    out.push(await el.getText());
  }
  return out;
}

export async function waitForRow(selector, name, present = true) {
  await browser.waitUntil(async () => (await texts(selector)).includes(name) === present, {
    timeout: 15000,
    timeoutMsg: `row "${name}" ${present ? 'never appeared' : 'never disappeared'} (${selector})`,
  });
}

// Open the row whose name matches by clicking its edit button (`.btn.small`).
export async function openRowByName(rowSel, nameSel, name) {
  const rows = await $$(rowSel);
  for (const row of rows) {
    if ((await row.$(nameSel).getText()) === name) {
      await row.$('.btn.small').click();
      return;
    }
  }
  throw new Error(`row "${name}" not found (${rowSel})`);
}

// Click the item (e.g. a server card) whose name matches.
export async function clickItemByName(itemSel, nameSel, name) {
  const items = await $$(itemSel);
  for (const item of items) {
    if ((await item.$(nameSel).getText()) === name) {
      await item.click();
      return;
    }
  }
  throw new Error(`item "${name}" not found (${itemSel})`);
}
