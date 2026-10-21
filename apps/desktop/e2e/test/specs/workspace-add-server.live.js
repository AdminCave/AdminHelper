// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Live, in the launcher (AH_E2E_WORKSPACE empty): makes the server workspace "Kunde B" of the
// second installation through the picker and its editor, and hands its id on. Orchestrated by
// scripts/tests/desktop_e2e_workspaces.sh, which seeds the settings.json of a version before
// workspaces with the URL of stack A, so the app moves it into "Standard". The id goes into
// the file AH_E2E_WS_B_FILE names; the orchestrator opens that workspace as wsB in
// two-installations.workspaces.js. Opening it from the picker would end the launcher, and with
// it this session: the spec only makes it.

import fs from 'node:fs';
import { MODAL, jsClick } from '../lib/live.js';

const SERVER_URL_B = process.env.AH_E2E_SERVER_URL_B;
const WS_B_FILE = process.env.AH_E2E_WS_B_FILE;
// two-installations.workspaces.js expects wsB under this name.
const NAME = 'Kunde B';

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

describe('Launcher: a server workspace for the second installation', () => {
  before(() => {
    for (const [name, value] of Object.entries({
      AH_E2E_SERVER_URL_B: SERVER_URL_B,
      AH_E2E_WS_B_FILE: WS_B_FILE,
    })) {
      if (!value) {
        throw new Error(
          `${name} is not set: run the live specs through scripts/tests/desktop_e2e_workspaces.sh`,
        );
      }
    }
  });

  it('opens the picker, which lists the migrated Standard', async () => {
    // A session that opened a workspace shows its login, never the picker. Waiting for either
    // and then asking for the context names a set AH_E2E_WORKSPACE as that, not as a missing list.
    await $('.picker-list, .login-card').waitForExist({ timeout: 20000 });
    expect(await invoke('workspace_context')).toMatchObject({ launcher: true });
    await $('.picker-list').waitForExist({ timeout: 10000 });
    await $('.picker-item[data-id="standard"]').waitForExist({ timeout: 15000 });
  });

  it('makes "Kunde B" in the editor and writes its id for the orchestrator', async () => {
    // An enabled kind below proves the editor is that of a new workspace: the one of "Edit"
    // keeps the kind of the selected Standard and would move Standard to stack B.
    await $('[data-action="workspace-new"]').click();
    const kind = await $(`${MODAL} select`);
    await kind.waitForExist({ timeout: 10000 });
    expect(await kind.isEnabled()).toBe(true);
    await kind.selectByAttribute('value', 'server');
    expect(await kind.getValue()).toBe('server');

    // The URL first: until a name is typed, the editor names the workspace after its host.
    await $(`${MODAL} input[name="url"]`).setValue(SERVER_URL_B);
    const name = await $(`${MODAL} input[name="name"]`);
    await name.setValue(NAME);
    expect(await name.getValue()).toBe(NAME);

    const save = await $(`${MODAL} .modal-footer .btn.primary`);
    await save.waitForEnabled({ timeout: 10000 });
    await jsClick(save);
    // The editor closes once Rust saved the workspace; a refusal stays in it as an alert.
    try {
      await $(MODAL).waitForExist({ reverse: true, timeout: 15000 });
    } catch (error) {
      const alert = await $(`${MODAL} [role="alert"]`);
      const why = (await alert.isExisting()) ? await alert.getText() : 'no message';
      throw new Error(`the editor did not save "${NAME}": ${why}`, { cause: error });
    }

    // The picker lists it; its id is that of the option.
    let id = null;
    await browser.waitUntil(
      async () => {
        for (const item of await $$('.picker-item')) {
          try {
            if ((await item.$('.picker-name').getText()) === NAME) {
              id = await item.getAttribute('data-id');
              return true;
            }
          } catch {
            return false; // the list rendered anew under the pass: query again
          }
        }
        return false;
      },
      { timeout: 15000, timeoutMsg: `the picker never listed "${NAME}"` },
    );

    // Once, as a server workspace at stack B. Rust gives the URL in its own spelling (a path
    // "/" added), so the origins are compared.
    const { workspaces } = await invoke('list_workspaces');
    expect(workspaces.filter((ws) => ws.name === NAME)).toHaveLength(1);
    const made = workspaces.find((ws) => ws.id === id);
    expect(made).toMatchObject({ name: NAME, kind: 'server', open: false });
    expect(new URL(made.url).origin).toBe(new URL(SERVER_URL_B).origin);

    fs.writeFileSync(WS_B_FILE, `${id}\n`);
  });
});
