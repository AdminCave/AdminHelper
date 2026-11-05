// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Live: open the seeded SSH connection through the GUI, once in each console the arrow of the
// connect button offers (R-1069). In the AdminHelper terminal a session tab opens: the spec
// answers ssh's host-key question and password prompt, runs a command, ends the shell,
// reconnects in the same tab and closes the tab after its question. The OS terminal is an
// external process and opens no tab. That the target saw every client, the orchestrator
// (desktop_e2e_connect.sh) reads from the sshd log. The checks read what ssh and the shell
// print, not the language of the UI.

import {
  login,
  CONN_ROW,
  MODAL,
  TERM_PANE,
  jsClick,
  selectByName,
  textContentOf,
  typeInTerminal,
  waitForTerminalLine,
} from '../lib/live.js';

const INSP = '[data-testid="conn-inspector"]';
const SESSION_TAB = '.session-tab-wrap .session-tab';
// The output differs from the line typed: proof that the shell ran it.
const COMMAND = 'echo AH_E2E_$((6*7))';
const OUTPUT = /^AH_E2E_42\s*$/;

// Start the connection in the console at `index` of the arrow's menu: 0 the AdminHelper
// terminal, 1 the OS terminal (ConnectButton.svelte).
async function connectIn(index) {
  await selectByName('ssh-direct');
  const more = await $(`${INSP} .split-more`);
  await more.waitForExist({ timeout: 15000 });
  await jsClick(more);
  const item = `${INSP} [role="menu"] [role="menuitem"]`;
  await $(item).waitForExist({ timeout: 10000 });
  const items = await $$(item);
  expect(items.length).toBe(2);
  await jsClick(items[index]);
}

// One sign-in in the terminal in front: the host-key question when ssh asks it, the password
// of the target, then the command.
async function signIn({ hostKeyAsked }) {
  const first = await waitForTerminalLine(/\(yes\/no|password:/i);
  expect(/\(yes\/no/.test(first)).toBe(hostKeyAsked);
  if (hostKeyAsked) {
    await typeInTerminal('yes');
    await waitForTerminalLine(/password:/i);
  }
  await typeInTerminal('e2e');
  await typeInTerminal(COMMAND);
  await waitForTerminalLine(OUTPUT);
}

describe('Open an SSH connection through the GUI', () => {
  before(async () => {
    await login();
    await $('.sidebar-nav [data-nav="connections"]').click();
    await $(CONN_ROW).waitForExist({ timeout: 15000 });
  });

  it('runs ssh in a session tab of the AdminHelper terminal, again after a reconnect', async () => {
    await connectIn(0);
    const tab = await $(SESSION_TAB);
    await tab.waitForExist({ timeout: 15000 });
    expect(await textContentOf(await tab.$('.session-tab-name'))).toBe('ssh-direct');
    expect(await tab.getAttribute('aria-selected')).toBe('true');

    // The orchestrator removed the target's key from known_hosts: ssh asks and keeps the answer.
    await signIn({ hostKeyAsked: true });
    await typeInTerminal('exit');
    await $(`${TERM_PANE} .term-ended`).waitForExist({ timeout: 15000 });

    // The reconnect starts on an empty screen in the same tab and finds the key known.
    await jsClick(await $(`${TERM_PANE} .term-ended button`));
    await signIn({ hostKeyAsked: false });
    expect((await $$(SESSION_TAB)).length).toBe(1);

    // A tab with a live shell asks before it closes.
    await jsClick(await $('.session-tab-close'));
    await $(`${MODAL} .confirm-message`).waitForExist({ timeout: 10000 });
    await jsClick(await $(`${MODAL} .btn.danger`));
    await browser.waitUntil(
      async () =>
        (await $$('.session-tab-wrap')).length === 0 && (await $$('.terminal-pane')).length === 0,
      { timeout: 10000, timeoutMsg: 'the session tab or its pane stayed after the close' },
    );
  });

  it('starts ssh in the OS terminal without a session tab', async () => {
    await connectIn(1);
    await browser.pause(5000); // the external ssh reaches the target; verified in the sshd log
    expect((await $$('.session-tab-wrap')).length).toBe(0);
  });
});
