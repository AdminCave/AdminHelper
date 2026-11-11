// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Live (arch-monitoring-ui T11, R-1225): the server page of the seeded server and the
// cross tabs, against a real agent, with a screenshot of every step in both themes for the
// look before the merge. desktop_e2e_monitoring.sh runs it after monitoring-check.live.js,
// whose agent_resources check stays on the server, and passes the container of the agent
// and the port finding its first report made.
//
// The agent runs once per call here (no timer): the spec lets it report before the page
// opens, so the dead man's warning (10 min without a result) does not count the app build
// and the first spec, and again after the adoption, so the new card shows the agent's own
// result for the port.

import path from "node:path";
import { spawnSync } from "node:child_process";
import { ahOutDir } from "../../wdio.conf.js";
import { login, clickItemByName, jsClick, textContentOf } from "../lib/live.js";

const AGENT = process.env.AH_E2E_AGENT;
const FINDING = process.env.AH_E2E_FINDING;
const SERVER_NAME = "e2e-server";
const CARD = ".mon-card";
const SILENT = '.status-footer [data-field="silent"]';
// The System card's title, the same in every language of the app.
const SYSTEM_TITLE = "System";
const CROSS_TABS = ["certs", "backups", "updates", "findings"];
// The auto-refresh of the monitoring page is 30 s, the pulse of the status bar 60 s.
const REFRESH_WAIT = 75000;

let step = 0;

// One run of the agent in its container: it fetches its plan, runs the due probes and
// reports.
function agentReport() {
  const run = spawnSync("docker", ["exec", AGENT, "/agent", "run", "--once"], {
    encoding: "utf8",
    timeout: 120000,
  });
  const out = `${run.stdout ?? ""}${run.stderr ?? ""}`;
  if (run.status !== 0 || !out.includes("Report gesendet")) {
    throw new Error(`the agent did not report (exit ${run.status}):\n${out}`);
  }
}

async function themeIs(theme) {
  return (await browser.execute(() => document.documentElement.dataset.theme ?? "dark")) === theme;
}

async function setTheme(theme) {
  if (await themeIs(theme)) return;
  // The only item of the sidebar footer with an aria-label (theme-toggle.live.js).
  await jsClick(await $(".sidebar-bottom .sidebar-item[aria-label]"));
  await browser.waitUntil(() => themeIs(theme), {
    timeout: 5000,
    timeoutMsg: `the theme did not switch to ${theme}`,
  });
}

// A screenshot of the step in the dark and the light theme, back in dark afterwards.
async function shot(name) {
  step += 1;
  const base = `server-page-${String(step).padStart(2, "0")}-${name}`;
  for (const theme of ["dark", "light"]) {
    await setTheme(theme);
    // Let the theme's transitions settle before the capture.
    await browser.pause(400);
    await browser.saveScreenshot(path.join(ahOutDir, "screenshots", `${base}-${theme}.png`));
  }
  await setTheme("dark");
}

// The card with exactly this title, or null; re-read on every call (the page re-renders).
async function cardByTitle(match) {
  for (const card of await $$(CARD)) {
    const title = await textContentOf(await card.$(".mon-card-title"));
    if (match(title)) return card;
  }
  return null;
}

async function waitForCard(match, what) {
  let found = null;
  await browser.waitUntil(
    async () => {
      try {
        found = await cardByTitle(match);
      } catch {
        found = null; // a card re-rendered under the handle
      }
      return found !== null;
    },
    { timeout: REFRESH_WAIT, timeoutMsg: `no card ${what} on the server page` },
  );
  return found;
}

const moduleCardTitle = (title) => title.endsWith(` · ${FINDING}`);

describe("Monitoring server page with its cards (arch-monitoring-ui T11)", () => {
  before(() => {
    for (const [name, value] of Object.entries({
      AH_E2E_AGENT: AGENT,
      AH_E2E_FINDING: FINDING,
    })) {
      if (!value) {
        throw new Error(
          `${name} is not set: run the spec through scripts/tests/desktop_e2e_monitoring.sh`,
        );
      }
    }
    agentReport();
  });

  it("opens the server page: green cards closed, the agent's port finding open", async () => {
    await login();
    await $('.sidebar-nav [data-nav="monitoring"]').click();
    await $('.mon-tabs [data-tab="overview"]').click();
    // The list view, which holds the server page: the first option of the view switch.
    await $('.mon-overview-toolbar [role="radio"]').click();
    await clickItemByName(".mon-srv-item", ".mon-srv-name", SERVER_NAME);
    await $(".mon-dashboard-name").waitForExist({ timeout: 15000 });
    expect(await textContentOf(await $(".mon-dashboard-name"))).toBe(SERVER_NAME);

    // Concept §3.14: what is green is one line, a problem opens its card.
    const system = await waitForCard((t) => t === SYSTEM_TITLE, SYSTEM_TITLE);
    const status = await system.getAttribute("data-status");
    const open = await system.$(".mon-card-toggle").getAttribute("aria-expanded");
    expect(open).toBe(String(status !== "ok" && status !== "pending"));

    // The findings card opens while it holds findings, and lists the agent's port.
    await browser.waitUntil(
      async () => (await domTexts(".inbox-item .inbox-instance")).includes(FINDING),
      { timeout: REFRESH_WAIT, timeoutMsg: `the finding ${FINDING} is not on the server page` },
    );
    const findingsOpen = await browser.execute(
      () =>
        document
          .querySelector(".inbox")
          ?.closest(".mon-card")
          ?.querySelector(".mon-card-toggle")
          ?.getAttribute("aria-expanded"),
    );
    expect(findingsOpen).toBe("true");
    await shot("overview");
  });

  it("adopts the port finding into a module card that shows the agent's result", async () => {
    const item = await findingItem(FINDING);
    // The first action of a finding adopts it, the second dismisses it.
    await jsClick(await item.$(".inbox-actions button"));
    const card = await waitForCard(moduleCardTitle, `for ${FINDING}`);
    expect(await domTexts(".inbox-item .inbox-instance")).not.toContain(FINDING);
    // Adopted and not run yet: pending, so the card stays closed.
    expect(await card.getAttribute("data-status")).toBe("pending");
    expect(await card.$(".mon-card-toggle").getAttribute("aria-expanded")).toBe("false");
    await shot("adopted");

    agentReport();
    // The port answers: the gateway the agent reports to listens on it.
    await browser.waitUntil(
      async () => {
        try {
          return (await (await cardByTitle(moduleCardTitle))?.getAttribute("data-status")) === "ok";
        } catch {
          return false;
        }
      },
      { timeout: REFRESH_WAIT, timeoutMsg: `the card of ${FINDING} never showed the agent's ok` },
    );
    const done = await cardByTitle(moduleCardTitle);
    await jsClick(await done.$(".mon-card-toggle"));
    await (await done.$(".module-figures")).waitForExist({
      timeout: 5000,
      timeoutMsg: `the open card of ${FINDING} shows no figures`,
    });
    await shot("module-result");
  });

  it("opens the System card on a click", async () => {
    const system = await cardByTitle((t) => t === SYSTEM_TITLE);
    const toggle = await system.$(".mon-card-toggle");
    if ((await toggle.getAttribute("aria-expanded")) !== "true") await jsClick(toggle);
    await (await system.$(".mon-card-body")).waitForExist({ timeout: 5000 });
    await shot("system-open");
  });

  for (const tab of CROSS_TABS) {
    it(`opens the cross tab ${tab}`, async () => {
      await $(`.mon-tabs [data-tab="${tab}"]`).click();
      const content = `.mon-tab-content[data-tab="${tab}"]`;
      // A table or its empty state; nothing while the tab is not the active one.
      await browser.waitUntil(
        async () =>
          (await browser.execute(
            (sel) => document.querySelector(sel)?.childElementCount ?? 0,
            content,
          )) > 0,
        { timeout: 15000, timeoutMsg: `the tab ${tab} shows nothing` },
      );
      if (tab === "findings") {
        // The adopted finding left the inbox of every server.
        const text = await browser.execute((sel) => document.querySelector(sel).textContent, content);
        expect(text).not.toContain(FINDING);
      }
      await shot(`tab-${tab}`);
    });
  }

  it("shows no dead man's warning while the agent reports", async () => {
    // The positive half: the status bar loaded the monitoring state, and the checks are
    // enabled, so the warning would be shown (it is never shown without an enabled check).
    await $('.status-footer [data-field="problems"]').waitForExist({ timeout: REFRESH_WAIT });
    const summary = await browser.execute(async () =>
      window.__TAURI__.core
        .invoke("api_proxy", { method: "GET", path: "/api/monitoring/status/summary" })
        .then((value) => ({ value }))
        .catch((e) => ({ rejected: String((e && e.message) || e) })),
    );
    if (summary.rejected !== undefined) throw new Error(`status summary: ${summary.rejected}`);
    expect(summary.value.minIntervalS).not.toBeNull();
    expect(Date.now() - Date.parse(summary.value.lastResultAt)).toBeLessThan(10 * 60000);
    expect(await $(SILENT).isExisting()).toBe(false);
    expect(await $(".mon-silent").isExisting()).toBe(false);
    await $('.mon-tabs [data-tab="overview"]').click();
    await shot("status-bar");
  });
});

// The texts of every match in one call: the page re-renders on its refresh, and a handle per
// element (texts() of live.js) can go stale between two of them.
async function domTexts(selector) {
  return browser.execute(
    (sel) => [...document.querySelectorAll(sel)].map((el) => el.textContent.trim()),
    selector,
  );
}

async function findingItem(instance) {
  for (const item of await $$(".inbox-item")) {
    if ((await textContentOf(await item.$(".inbox-instance"))) === instance) return item;
  }
  throw new Error(`no finding ${instance} in the inbox`);
}
