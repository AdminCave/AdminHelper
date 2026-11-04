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
// The last two steps (R-1103): the history of the server, whose agent_resources
// check the first step made, and the comparison tab show the agent's push.

import {
  MODAL,
  MODAL_PANEL,
  login,
  gotoInfrastructure,
  openServerTab,
  clickInModal,
  clickItemByName,
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
// desktop_e2e_monitoring.sh seeds it; its agent pushes once before the specs run.
const SERVER_NAME = "e2e-server";
const HISTORY = ".history-panel";
const COMPARE = ".compare-view";
// The period group is the last of the header (after the history tabs or the metrics).
const PERIOD_BUTTONS = ".mon-segmented:last-of-type .mon-seg-btn";
const EMPTY_VALUE = "—"; // formatValue of a series without a value
const OLD_CHART = "data-e2e-old";

// The chart is drawn only once a series holds a value. load() empties the panel at
// once and fills it on the response, so a chart right after a period switch may be
// the old one still standing. Its node is marked before the switch and the wait
// takes only an unmarked chart: a handle would not do, isExisting() queries again.
async function waitForChart(scope) {
  const selector = `${scope} .time-chart:not([${OLD_CHART}])`;
  await $(selector).waitForExist({
    timeout: 20000,
    timeoutMsg: `no chart in ${scope}: no value of the agent's push in the period?`,
  });
}

async function switchPeriod(scope, index) {
  await browser.execute(
    (sel, attr) => document.querySelector(sel)?.setAttribute(attr, ""),
    `${scope} .time-chart`,
    OLD_CHART,
  );
  await (await periodButton(scope, index)).click();
  await waitForChart(scope);
}

// The period buttons by position (1h, 24h, 7d, 30d); their labels are translated.
async function periodButton(scope, index) {
  return (await $$(`${scope} ${PERIOD_BUTTONS}`))[index];
}

describe("Monitoring check via the GUI", () => {
  it("creates an agent_resources check on the seeded server", async () => {
    await login();
    await gotoInfrastructure();
    await openServerTab("monitoring");

    await $('[data-action="check-new"]').click();
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
    const assign = await $('[data-action="tpl-suggest-assign"]');
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

  it("shows the server's resource history for 24 hours, then for 1 hour (R-1103)", async () => {
    await $('.sidebar-nav [data-nav="monitoring"]').click();
    await $('.mon-tabs [data-tab="overview"]').click();
    // The list view, which holds the dashboard: the first option of the view switch.
    await $('.mon-overview-toolbar [role="radio"]').click();
    await clickItemByName(".mon-srv-item", ".mon-srv-name", SERVER_NAME);

    await waitForChart(HISTORY);
    expect(await (await periodButton(HISTORY, 1)).getAttribute("aria-pressed")).toBe("true");
    // The first row of the statistics is CPU, with a value.
    const cpu = await $(`${HISTORY} .history-stats tbody tr`);
    expect(await cpu.$("th").getText()).toContain("CPU");
    expect(await cpu.$("td").getText()).not.toBe(EMPTY_VALUE);
    // The CSV export, the last tool; disabled without data.
    expect(await $(`${HISTORY} .history-tools > .btn.small:last-child`).isEnabled()).toBe(true);

    await switchPeriod(HISTORY, 0);
    expect(await (await periodButton(HISTORY, 0)).getAttribute("aria-pressed")).toBe("true");
    expect(await $(`${HISTORY} .history-stats tbody tr td`).getText()).not.toBe(EMPTY_VALUE);
  });

  it("ranks the server in the comparison tab, for 24 hours, then for 1 hour (R-1103)", async () => {
    await $('.mon-tabs [data-tab="history"]').click();

    await waitForChart(COMPARE);
    expect(await (await periodButton(COMPARE, 1)).getAttribute("aria-pressed")).toBe("true");
    await waitForRow(`${COMPARE} .compare-name`, SERVER_NAME);

    await switchPeriod(COMPARE, 0);
    expect(await (await periodButton(COMPARE, 0)).getAttribute("aria-pressed")).toBe("true");
    await waitForRow(`${COMPARE} .compare-name`, SERVER_NAME);
  });
});
