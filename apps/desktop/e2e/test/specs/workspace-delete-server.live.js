// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Live, in the launcher (AH_E2E_WORKSPACE empty): deletes the server workspace "Kunde B" in the
// picker, the one two-installations.workspaces.js registered at stack B, once both of its
// windows are closed. The launcher starts the purge (`--workspace <id> --purge`), which revokes
// the device at stack B with the identity of Kunde B first and then deletes what is left of it
// here. Orchestrated by scripts/tests/desktop_e2e_workspaces.sh, with the app data dir and the
// keyring of the runs before (gnome-keyring keeps it under XDG_DATA_HOME), so the purge finds
// that identity. The picker gives a revoke left undone (`localOnly`) a note of its own, but
// shows a revoke that went through and a workspace without an identity alike: that the device
// is revoked, and by itself, the orchestrator checks at stack B, as it checks that the
// directory of Kunde B is gone.

import { jsClick } from '../lib/live.js';

const WS_B = process.env.AH_E2E_WORKSPACE_B;
const SERVER_URL_B = process.env.AH_E2E_SERVER_URL_B;
// As workspace-add-server.live.js names it.
const NAME = 'Kunde B';
// The question of ConfirmDialog, which App lifts above the picker.
const CONFIRM = '.confirm-layer .modal-backdrop';
// PURGE_TIMEOUT in launcher.rs is 120 s: a purge that runs out says so before this does.
const PURGE_WAIT = 150000;

// A Tauri command through the bridge; a rejection fails the spec with its message. It comes
// back as { rejected }: webdriver takes a script result with an `error` key for a failed
// command (logout.live.js).
async function invoke(cmd, args = {}) {
  const out = await browser.executeAsync(
    (c, a, done) => {
      window.__TAURI__.core
        .invoke(c, a)
        .then((value) => done({ value }))
        .catch((e) => done({ rejected: String((e && e.message) || e) }));
    },
    cmd,
    args,
  );
  if (out.rejected !== undefined) throw new Error(`${cmd} failed: ${out.rejected}`);
  return out.value;
}

// The workspace `id` as Rust lists it; undefined once it is gone.
async function listed(id) {
  const { workspaces } = await invoke('list_workspaces');
  return workspaces.find((ws) => ws.id === id);
}

// The text of `el` as the DOM holds it. WebKitWebDriver gives '' for getText() of a text cut
// off by CSS (overflow hidden, ellipsis, nowrap), as `.picker-name` is: seen on the lane VM.
async function domText(el) {
  return browser.execute((node) => node.textContent.trim(), el);
}

describe('Launcher: deleting a server workspace revokes its device', () => {
  before(() => {
    for (const [name, value] of Object.entries({
      AH_E2E_WORKSPACE_B: WS_B,
      AH_E2E_SERVER_URL_B: SERVER_URL_B,
    })) {
      if (!value) {
        throw new Error(
          `${name} is not set: run the live specs through scripts/tests/desktop_e2e_workspaces.sh`,
        );
      }
    }
  });

  it(`lists "${NAME}" closed, as the server workspace at stack B`, async () => {
    // A session that opened a workspace shows its login, never the picker. Waiting for either
    // and then asking for the context names a set AH_E2E_WORKSPACE as that, not as a missing list.
    await $('.picker-list, .login-card').waitForExist({ timeout: 20000 });
    expect(await invoke('workspace_context')).toMatchObject({ launcher: true });
    const item = await $(`.picker-item[data-id="${WS_B}"]`);
    await item.waitForExist({ timeout: 15000 });
    expect(await domText(await item.$('.picker-name'))).toBe(NAME);
    // Only a closed workspace is deleted: both windows of the run before have ended.
    expect(await item.$('.picker-open').isExisting()).toBe(false);
    const ws = await listed(WS_B);
    expect(ws).toMatchObject({ name: NAME, kind: 'server', open: false });
    // The purge revokes at the URL the workspace has: that of stack B. Rust gives the URL in its
    // own spelling (a path "/" added), so the origins are compared.
    expect(new URL(ws.url).origin).toBe(new URL(SERVER_URL_B).origin);
  });

  it('deletes it after a question that names it, without the note of a revoke left undone', async () => {
    // By its id: the name is in the DOM, but getText() of `.picker-name` gives '' (domText).
    const item = await $(`.picker-item[data-id="${WS_B}"]`);
    await item.click();
    await browser.waitUntil(
      async () => (await item.getAttribute('aria-selected')) === 'true',
      { timeout: 10000, timeoutMsg: `the picker never selected "${NAME}"` },
    );
    await $('[data-action="workspace-delete"]').click();
    const question = await $(`${CONFIRM} .confirm-message`);
    await question.waitForExist({ timeout: 10000 });
    expect(await question.getText()).toContain(NAME);
    await jsClick(await $(`${CONFIRM} .modal-footer .btn.danger`));
    await $(CONFIRM).waitForExist({ reverse: true, timeout: 10000 });

    // The purge runs in a process of its own and asks stack B; the picker says how it ended.
    await browser.waitUntil(
      async () =>
        (await $('[data-msg="deleted"]').isExisting()) ||
        (await $('[data-msg="action-failed"]').isExisting()),
      { timeout: PURGE_WAIT, timeoutMsg: `the picker never said whether "${NAME}" was deleted` },
    );
    const failed = await $('[data-msg="action-failed"]');
    if (await failed.isExisting()) {
      throw new Error(`the delete of "${NAME}" failed: ${await failed.getText()}`);
    }
    expect(await $('[data-msg="deleted"]').getText()).toContain(NAME);
    // `localOnly`: the identity went here only, stack B was not told.
    const localOnly = await $('[data-msg="deleted-local-only"]');
    if (await localOnly.isExisting()) {
      throw new Error(
        `"${NAME}" was deleted without its revoke at stack B: ${await localOnly.getText()}`,
      );
    }
  });

  it('lists it no more, in the picker and in Rust, and keeps Standard', async () => {
    await $(`.picker-item[data-id="${WS_B}"]`).waitForExist({ reverse: true, timeout: 15000 });
    expect(await listed(WS_B)).toBeUndefined();
    expect(await listed('standard')).toMatchObject({ kind: 'server' });
  });
});
