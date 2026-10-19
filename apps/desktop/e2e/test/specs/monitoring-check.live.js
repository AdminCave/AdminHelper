// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Live: create an agent_resources monitoring check through the GUI on the seeded
// server (which a real agent has already pushed metrics for). The check appears
// in the list after a reload from the monitoring service (GUI → api_proxy →
// gateway → server → monitoring). Orchestrated by desktop_e2e_monitoring.sh.
// The second step (R-0421): the agent's report carried its `host` block, so the
// tab suggests the Linux standard template; assigning it creates the template's
// checks and ends the suggestion. The step removes the assignment again, which
// leaves the server as the first step left it.

import {
  MODAL,
  MODAL_PANEL,
  login,
  gotoInfrastructure,
  openServerTab,
  clickInModal,
  waitForRow,
  texts,
} from "../lib/live.js";

// The built-in linux-base (apps/monitoring/app/builtin_templates.py): its
// checkbox in the suggestion carries the slug, its label the template name.
const LINUX_BASE = "linux-base";
const LINUX_BASE_NAME = "Linux Server — Standard";
// Two of the checks linux-base creates on assignment.
const LINUX_BASE_CHECKS = ["Agent Heartbeat", "System Resources"];
const SUGGEST_BOX = '.tpl-suggest input[type="checkbox"]';
const LINUX_BASE_BOX = `${SUGGEST_BOX}[value="${LINUX_BASE}"]`;
const CHECK_NAMES = ".mon-row .mon-name";

describe("Monitoring check via the GUI", () => {
  it("creates an agent_resources check on the seeded server", async () => {
    await login();
    await gotoInfrastructure();
    await openServerTab("monitoring");

    await $(".mon-toolbar .btn.primary").click();
    await $(`${MODAL} ${MODAL_PANEL}`).waitForExist({ timeout: 10000 });
    await $(`${MODAL} input[type="text"]`).setValue("cpu-check");
    const selects = await $$(`${MODAL} select`); // checkType, interval, severity
    await selects[0].selectByAttribute("value", "agent_resources");
    await clickInModal(".btn.primary"); // save -> POST /api/monitoring/checks

    await waitForRow(".mon-row .mon-name", "cpu-check");
  });

  it("suggests the Linux standard template and assigning it creates its checks (R-0421)", async () => {
    // The tab loaded its suggestions when it opened, after the agent's push.
    await $(LINUX_BASE_BOX).waitForExist({
      timeout: 15000,
      timeoutMsg: `no suggestion ${LINUX_BASE} in the monitoring tab — did the agent's report carry its host block?`,
    });
    expect(await $(LINUX_BASE_BOX).parentElement().getText()).toContain(LINUX_BASE_NAME);
    const before = await texts(CHECK_NAMES);
    for (const name of LINUX_BASE_CHECKS) expect(before).not.toContain(name);

    // Only linux-base: every suggestion starts checked, and on a host with Docker
    // the tab also suggests Docker Host.
    for (const box of await $$(SUGGEST_BOX)) {
      const wanted = (await box.getAttribute("value")) === LINUX_BASE;
      if ((await box.isSelected()) !== wanted) await box.click();
    }
    const assign = await $(".tpl-suggest .btn.primary");
    await assign.waitForEnabled({
      timeout: 10000,
      timeoutMsg: "the Assign button of the suggestion never became enabled",
    });
    await assign.click();

    for (const name of LINUX_BASE_CHECKS) await waitForRow(CHECK_NAMES, name);
    await $(LINUX_BASE_BOX).waitForExist({
      reverse: true,
      timeout: 15000,
      timeoutMsg: `the suggestion ${LINUX_BASE} was still shown after its assignment`,
    });

    // Clean up: removing the assignment deletes the template's checks again. The
    // button's label ends with the template name, whatever the UI language.
    const remove = await $(`.tpl-remove[aria-label$="${LINUX_BASE_NAME}"]`);
    await remove.waitForEnabled({
      timeout: 10000,
      timeoutMsg: `no enabled remove button on the assignment of ${LINUX_BASE_NAME}`,
    });
    await remove.click();
    for (const name of LINUX_BASE_CHECKS) await waitForRow(CHECK_NAMES, name, false);
  });
});
