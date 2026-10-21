// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Live, in the launcher (AH_E2E_WORKSPACE empty): the picker, which replaces the switch of the
// app mode in the settings (R-0431). It lists "Standard", which the app made of the
// settings.json the orchestrator seeded in server mode, as a server workspace, with the note on
// the migration once. Then it makes the local workspace "E2E Lokal" with a colour, renames it
// and deletes it; the question before the delete names it and warns of the data lost with it.
// Run last by scripts/tests/desktop_e2e_crud.sh, in a wdio run of its own: the specs before it
// open "Standard" and list nothing, so the note is still due; the orchestrator checks afterwards
// that only the directory of "Standard" is left. Opening a workspace from the picker starts a
// process outside WebDriver and ends the launcher, and with it this session: only the launcher
// tests in Rust prove that; desktop_e2e_workspaces.sh starts its workspaces with --workspace.

import fs from 'node:fs';
import { MODAL, clickItemByName, jsClick, texts } from '../lib/live.js';

const NAME = 'E2E Lokal';
const RENAMED = 'E2E Lokal umbenannt';
// Not the first colour of the palette, the one a new workspace has before one is chosen.
const COLOR = '#ec4899';
// The question of ConfirmDialog, which App lifts above the picker.
const CONFIRM = '.confirm-layer .modal-backdrop';

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

// The text of the UI string `key` in each language of the UI, `{var}` filled from `vars`. The
// specs select by structure, but which question the picker asks only its text tells, and the
// language of the app follows the one of the box. One text for each language the type Language
// names: a text missing in one would only fail on a box in that language.
function translations(key, vars = {}) {
  const source = fs.readFileSync(
    new URL('../../../ui/src/lib/i18n/dictionaries.ts', import.meta.url),
    'utf8',
  );
  const languages = [
    ...(source.match(/^export type Language = (.+);$/m)?.[1] ?? '').matchAll(/'(\w+)'/g),
  ].map(([, language]) => language);
  if (languages.length === 0) throw new Error('the dictionaries of the UI name no language');
  // The block of each language, from its `  <language>: {` to the next one.
  const parts = source.split(/^ {2}(\w+): \{$/m);
  const blocks = new Map();
  for (let i = 1; i < parts.length; i += 2) blocks.set(parts[i], parts[i + 1]);
  // In single quotes, or in double ones, where Prettier puts a text with an apostrophe.
  const pattern = new RegExp(
    `'${key.replaceAll('.', '\\.')}':\\s*(?:'((?:[^'\\\\]|\\\\.)*)'|"((?:[^"\\\\]|\\\\.)*)")`,
  );
  return languages.map((language) => {
    const match = blocks.get(language)?.match(pattern);
    if (!match) {
      throw new Error(`the dictionaries of the UI have no text for ${key} in ${language}`);
    }
    return unescapeJs(match[1] ?? match[2]).replace(/\{(\w+)\}/g, (_, name) =>
      String(vars[name] ?? ''),
    );
  });
}

// The text of a JS string literal's body: \n, \r, \t and the code point escapes as JS reads
// them, any other escaped character as itself (\' and \" among them).
const ESCAPES = { n: '\n', r: '\r', t: '\t' };
function unescapeJs(body) {
  return body.replace(/\\(u\{[0-9a-fA-F]+\}|u[0-9a-fA-F]{4}|x[0-9a-fA-F]{2}|.)/g, (_, escape) =>
    escape.length > 1
      ? String.fromCodePoint(parseInt(escape.replace(/[ux{}]/g, ''), 16))
      : (ESCAPES[escape] ?? escape),
  );
}

// The id of the workspace the picker lists under `name`.
async function idOf(name) {
  let id = null;
  await browser.waitUntil(
    async () => {
      for (const item of await $$('.picker-item')) {
        try {
          if ((await item.$('.picker-name').getText()) === name) {
            id = await item.getAttribute('data-id');
            return true;
          }
        } catch {
          return false; // the list rendered anew under the pass: query again
        }
      }
      return false;
    },
    { timeout: 15000, timeoutMsg: `the picker never listed "${name}"` },
  );
  return id;
}

// Saves the open editor; it closes once Rust saved, a refusal stays in it as an alert.
async function save(name) {
  const button = await $(`${MODAL} .modal-footer .btn.primary`);
  await button.waitForEnabled({ timeout: 10000 });
  await jsClick(button);
  try {
    await $(MODAL).waitForExist({ reverse: true, timeout: 15000 });
  } catch (error) {
    const alert = await $(`${MODAL} [role="alert"]`);
    const why = (await alert.isExisting()) ? await alert.getText() : 'no message';
    throw new Error(`the editor did not save "${name}": ${why}`, { cause: error });
  }
}

async function kindShown(id) {
  return $(`.picker-item[data-id="${id}"] .picker-kind`).getAttribute('aria-label');
}

describe('Launcher: the picker replaces the switch of the app mode', () => {
  let made = null;

  it('lists the migrated Standard as a server workspace, with the note on the migration once', async () => {
    // A session that opened a workspace shows its login, never the picker. Waiting for either
    // and then asking for the context names a set AH_E2E_WORKSPACE as that, not as a missing list.
    await $('.picker-list, .login-card').waitForExist({ timeout: 20000 });
    expect(await invoke('workspace_context')).toMatchObject({ launcher: true });
    await $('.picker-list').waitForExist({ timeout: 10000 });
    const standard = await $('.picker-item[data-id="standard"]');
    await standard.waitForExist({ timeout: 15000 });
    expect(await standard.$('.picker-name').getText()).toBe('Standard');
    expect(translations('settings.mode.server')).toContain(await kindShown('standard'));
    expect((await $$('[data-msg="migrated"]')).length).toBe(1);

    // Rust gives the note in the first listing only, the one of the picker.
    const listing = await invoke('list_workspaces');
    expect(listing.migratedNotice).toBe(false);
    expect(listing.workspaces.find((ws) => ws.id === 'standard')).toMatchObject({
      name: 'Standard',
      kind: 'server',
      open: false,
    });
  });

  it(`makes the local workspace "${NAME}" with a colour`, async () => {
    await $('[data-action="workspace-new"]').click();
    const kind = await $(`${MODAL} select`);
    await kind.waitForExist({ timeout: 10000 });
    await kind.selectByAttribute('value', 'local');
    expect(await kind.getValue()).toBe('local');
    // A local workspace has no URL to ask for.
    await $(`${MODAL} input[name="url"]`).waitForExist({ reverse: true, timeout: 10000 });
    await $(`${MODAL} input[name="name"]`).setValue(NAME);
    const swatch = await $(`${MODAL} .ws-swatch[aria-label="${COLOR}"]`);
    await swatch.click();
    expect(await swatch.getAttribute('aria-checked')).toBe('true');
    await save(NAME);

    made = await idOf(NAME);
    const dot = await $(`.picker-item[data-id="${made}"] .picker-dot`);
    expect((await dot.getCSSProperty('background-color')).parsed.hex).toBe(COLOR);
    expect(translations('settings.mode.local')).toContain(await kindShown(made));
    expect(await listed(made)).toMatchObject({
      name: NAME,
      kind: 'local',
      color: COLOR,
      url: null,
      open: false,
    });
  });

  it('renames it in the editor, which keeps its kind and its colour', async () => {
    await clickItemByName('.picker-item', '.picker-name', NAME);
    await browser.waitUntil(
      async () =>
        (await $(`.picker-item[data-id="${made}"]`).getAttribute('aria-selected')) === 'true',
      { timeout: 10000, timeoutMsg: `the picker never selected "${NAME}"` },
    );
    await $('[data-action="workspace-edit"]').click();
    const kind = await $(`${MODAL} select`);
    await kind.waitForExist({ timeout: 10000 });
    expect(await kind.isEnabled()).toBe(false);
    expect(await kind.getValue()).toBe('local');
    const name = await $(`${MODAL} input[name="name"]`);
    expect(await name.getValue()).toBe(NAME);
    expect(
      await $(`${MODAL} .ws-swatch[aria-label="${COLOR}"]`).getAttribute('aria-checked'),
    ).toBe('true');
    await name.setValue(RENAMED);
    await save(RENAMED);

    expect(await idOf(RENAMED)).toBe(made);
    expect(await texts('.picker-name')).not.toContain(NAME);
    expect(await listed(made)).toMatchObject({ name: RENAMED, kind: 'local', color: COLOR });
  });

  it('deletes it after a question that names it and warns of the data lost', async () => {
    // Still the one selected: the rename did not change the selection.
    await $('[data-action="workspace-delete"]').click();
    const question = await $(`${CONFIRM} .confirm-message`);
    await question.waitForExist({ timeout: 10000 });
    expect(translations('workspace.picker.delete.confirm.local', { name: RENAMED })).toContain(
      await question.getText(),
    );
    await jsClick(await $(`${CONFIRM} .modal-footer .btn.danger`));
    await $(CONFIRM).waitForExist({ reverse: true, timeout: 10000 });

    // The purge runs in a process of its own; the picker says how it ended.
    await browser.waitUntil(
      async () =>
        (await $('[data-msg="deleted"]').isExisting()) ||
        (await $('[data-msg="action-failed"]').isExisting()),
      { timeout: 60000, timeoutMsg: `the picker never said whether "${RENAMED}" was deleted` },
    );
    const failed = await $('[data-msg="action-failed"]');
    if (await failed.isExisting()) {
      throw new Error(`the delete of "${RENAMED}" failed: ${await failed.getText()}`);
    }
    expect(await $('[data-msg="deleted"]').getText()).toContain(RENAMED);
    // A local workspace has no device identity whose revoke could fail.
    expect(await $('[data-msg="deleted-local-only"]').isExisting()).toBe(false);
    await $(`.picker-item[data-id="${made}"]`).waitForExist({ reverse: true, timeout: 15000 });
    expect(await listed(made)).toBeUndefined();
    expect(await listed('standard')).toMatchObject({ kind: 'server' });
    // The note stays once through every listing since.
    expect((await $$('[data-msg="migrated"]')).length).toBe(1);
  });
});
