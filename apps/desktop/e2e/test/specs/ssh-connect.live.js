// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Live: open the seeded SSH connection through the GUI, once in each console the arrow of the
// connect button offers (R-1069). In the AdminHelper terminal a session tab opens: the spec
// answers ssh's host-key question and password prompt, runs a command, ends the shell,
// reconnects in the same tab, detaches the session into a window of its own and docks it back
// (R-1070), saves a snippet and runs it (R-1071), creates a folder in the files panel and goes
// into it (R-1072), and closes the tab after its question. The OS terminal is an
// external process and opens no tab. That the target saw every client, the orchestrator
// (desktop_e2e_connect.sh) reads from the sshd log; the files go over the ControlMaster of the
// session, so they add no sign-in there. The checks read what ssh and the shell print, the
// names the host lists and the icons of the buttons, not the language of the UI.

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
// The buttons after a tab: detach (only while its program runs), then close (SessionTabs.svelte).
const DETACH_BUTTON = '.session-tab-wrap .session-tab-close:nth-child(2)';
const CLOSE_BUTTON = '.session-tab-wrap .session-tab-close:last-child';
// The window of a detached session (DetachedTerminal.svelte) and its Dock button in the header.
const DETACHED = '.detached';
const DOCK_BUTTON = `${DETACHED} .term-head > .ui-btn`;
// The output differs from the line typed: proof that the shell ran it.
const COMMAND = 'echo AH_E2E_$((6*7))';
const OUTPUT = /^AH_E2E_42\s*$/;
const DETACHED_COMMAND = 'echo AH_E2E_$((6*8))';
const DETACHED_OUTPUT = /^AH_E2E_48\s*$/;
const DOCKED_COMMAND = 'echo AH_E2E_$((6*9))';
const DOCKED_OUTPUT = /^AH_E2E_54\s*$/;
const SNIPPET_NAME = 'ah-e2e-snippet';
const SNIPPET_COMMAND = 'echo AH_E2E_$((6*10))';
const SNIPPET_OUTPUT = /^AH_E2E_60\s*$/;
// The panel beside the terminal in front (SshTerminal.svelte), with the snippets or the files.
const PANEL = `${TERM_PANE} .term-panel`;

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

// A line of the terminal under `root` that matches `re`, as the DOM renderer of xterm draws it;
// the helpers of live.js read the pane in front of the main window, a detached window has none.
async function waitForLineIn(root, re, timeout = 30000) {
  let lines = [];
  try {
    await browser.waitUntil(
      async () => {
        lines = await browser.execute((r) => {
          const rows = document.querySelector(`${r} .xterm-rows`);
          return rows ? [...rows.children].map((x) => x.textContent.replace(/\u00a0/g, ' ')) : [];
        }, root);
        return lines.some((l) => re.test(l));
      },
      { timeout },
    );
  } catch {
    const screen = lines
      .map((l) => l.trimEnd())
      .filter(Boolean)
      .slice(-8);
    throw new Error(`no line under ${root} matches ${re}; the screen ends with ${JSON.stringify(screen)}`);
  }
}

// Moves the session in front into a window of its own, runs a command there and docks it back:
// the tab then shows what ran before, in the window and after (R-1070).
async function detachAndDock() {
  const main = await browser.getWindowHandle();
  await jsClick(await $(DETACH_BUTTON));
  await browser.waitUntil(async () => (await browser.getWindowHandles()).length === 2, {
    timeout: 15000,
    timeoutMsg: 'no second window opened for the detached session',
  });
  const other = (await browser.getWindowHandles()).find((w) => w !== main);
  await browser.switchToWindow(other);
  await $(`${DETACHED} .xterm-helper-textarea`).waitForExist({ timeout: 15000 });
  // The window took the session over with what it had printed so far.
  await waitForLineIn(DETACHED, OUTPUT);
  await $(`${DETACHED} .xterm-helper-textarea`).addValue(DETACHED_COMMAND);
  await browser.keys('Enter');
  await waitForLineIn(DETACHED, DETACHED_OUTPUT);

  await jsClick(await $(DOCK_BUTTON));
  await browser.waitUntil(async () => (await browser.getWindowHandles()).length === 1, {
    timeout: 15000,
    timeoutMsg: 'the window of the detached session stayed after Dock',
  });
  await browser.switchToWindow(main);
  await $(`${TERM_PANE} .xterm-helper-textarea`).waitForExist({ timeout: 15000 });
  await waitForTerminalLine(OUTPUT);
  await waitForTerminalLine(DETACHED_OUTPUT);
  await typeInTerminal(DOCKED_COMMAND);
  await waitForTerminalLine(DOCKED_OUTPUT);
}

// Clicks the button under `root` that shows the Lucide icon `icon` (its class `lucide-<icon>`):
// the buttons of the terminal header are icons, their names follow the language.
async function clickIcon(root, icon) {
  const svg = await $(`${root} svg.lucide-${icon}`);
  await svg.waitForExist({ timeout: 15000 });
  await browser.execute((node) => node.closest('button').click(), svg);
}

// The text of each `.files-name` in the files panel: the path first, then the entries.
async function filesNames() {
  return browser.execute(
    (panel) => [...document.querySelectorAll(`${panel} .files-name`)].map((n) => n.textContent),
    PANEL,
  );
}

// Saves a snippet in the panel of the terminal in front and runs it: its output then shows in
// the terminal (R-1071).
async function runNewSnippet() {
  await clickIcon(`${TERM_PANE} .term-head`, 'square-code');
  await clickIcon(`${PANEL} .snips-head`, 'plus');
  await $(`${PANEL} .snips-form input`).setValue(SNIPPET_NAME);
  await $(`${PANEL} .snips-form textarea`).setValue(SNIPPET_COMMAND);
  await jsClick(await $(`${PANEL} .snips-form button[type="submit"]`));
  await $(`${PANEL} .snips-form`).waitForExist({ timeout: 15000, reverse: true });
  let card = null;
  await browser.waitUntil(
    async () => {
      for (const run of await $$(`${PANEL} .snip-run`)) {
        if ((await textContentOf(await run.$('.snip-name'))) === SNIPPET_NAME) card = run;
      }
      return card !== null;
    },
    { timeout: 15000, timeoutMsg: `no snippet ${SNIPPET_NAME} in the list after saving it` },
  );
  await jsClick(card);
  await waitForTerminalLine(SNIPPET_OUTPUT);
}

// Opens the files of the session, creates a folder in the login directory, finds it after a
// refresh and goes into it (R-1072).
async function createAndOpenFolder() {
  const folder = `ah-e2e-${Date.now()}`;
  await clickIcon(`${TERM_PANE} .term-head`, 'folder-open');
  // The login directory is listed with `..` on top.
  await browser.waitUntil(async () => (await filesNames()).includes('..'), {
    timeout: 30000,
    timeoutMsg: 'the files panel listed no folder',
  });
  const home = (await filesNames())[0];
  await clickIcon(`${PANEL} .files-head`, 'folder-plus');
  await $(`${PANEL} .files-form input`).setValue(folder);
  await jsClick(await $(`${PANEL} .files-form button[type="submit"]`));
  await $(`${PANEL} .files-form`).waitForExist({ timeout: 15000, reverse: true });
  await clickIcon(`${PANEL} .files-head`, 'refresh-cw');
  let entry = null;
  await browser.waitUntil(
    async () => {
      for (const button of await $$(`${PANEL} .files-list .file`)) {
        if ((await textContentOf(await button.$('.files-name'))) === folder) entry = button;
      }
      return entry !== null && (await entry.isEnabled());
    },
    { timeout: 15000, timeoutMsg: `no folder ${folder} in the list after a refresh` },
  );
  await jsClick(entry);
  const inside = `${home.replace(/\/$/, '')}/${folder}`;
  await browser.waitUntil(async () => (await filesNames())[0] === inside, {
    timeout: 15000,
    timeoutMsg: `the files panel did not go into ${inside}`,
  });
  expect(await $(`${PANEL} .files-error`).isExisting()).toBe(false);
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

    await detachAndDock();
    expect((await $$(SESSION_TAB)).length).toBe(1);

    await runNewSnippet();
    await createAndOpenFolder();

    // A tab with a live shell asks before it closes.
    await jsClick(await $(CLOSE_BUTTON));
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
