// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Live (arch-monitoring-ui-3 T11, R-1226): the full service list of a server, its filter and
// search, the error lines of a failed service with the switch that turns them off, and "Mehr
// Log", with a screenshot of every step in both themes. desktop_e2e_monitoring.sh runs it after
// monitoring-server-page.live.js and passes the container of the fixture agent and the name of
// an SSH connection of the fixture server.
//
// The containers run no systemd, so the spec pushes a fixed systemd block through the real
// agent route with the fixture agent's own key. Its error lines carry secrets as an older or
// foreign agent would send them: the list must show them redacted. The SSH target of the
// connection runs a stand-in journalctl that prints its arguments, so the terminal shows what
// the remote shell made of the fixed command; the journal itself stays unverified here.

import {
  login,
  clickItemByName,
  jsClick,
  terminalLines,
  textContentOf,
  typeInTerminal,
  waitForTerminalLine,
  TERM_PANE,
} from "../lib/live.js";
import { makeShot, fixtureAgentConf, createCheck, postReport } from "../lib/monitoring-live.js";

const FIXTURE_AGENT = process.env.AH_E2E_FIXTURE_AGENT;
const SSH_CONNECTION = process.env.AH_E2E_SSH_CONNECTION;
const FIXTURE_SERVER = "e2e-fixture";
const CHECK_NAME = "fixture-services";
const LIST = ".svc-list";
const ROWS = `${LIST} table.cross-table tbody tr`;
const SWITCH = `${LIST} .svc-options [role="switch"]`;
// The options of the state filter, in the order of ServiceList.svelte.
const FILTER = `${LIST} [role="radiogroup"] [role="radio"]`;
const FILTER_INDEX = { all: 0, failed: 1, inactive: 2, active: 3 };
const SESSION_TAB = ".session-tab-wrap .session-tab";
// The bound of every wait for a condition (.claude/rules/testing.md).
const WAIT = 30000;
// The auto-refresh of the monitoring page is 30 s.
const REFRESH_WAIT = 75000;

const NGINX = "nginx.service";
// A template instance with an escaped dash: "Mehr Log" must hand both to the remote shell as
// they are.
const BACKUP = "restic-backup@data\\x2dpool.service";
// Secrets in the error lines as a careless program logs them; none may reach the list.
const SECRETS = ["s3cr3t-e2e", "e2e-hidden-value"];
const NGINX_LINES = [
  "nginx: [emerg] bind() to 0.0.0.0:443 failed (98: Address already in use)",
  "deploy hook: fetching https://deploy:s3cr3t-e2e@git.example.com/site.git",
  "deploy hook: retry with token=e2e-hidden-value refused",
  "nginx.service: Main process exited, code=exited, status=1/FAILURE",
  "nginx.service: Failed with result 'exit-code'.",
];
// The stand-in journalctl of the SSH target prints each argument on a line of its own, then
// their count: short lines, which no width of the terminal wraps.
const JOURNAL_ARGS = ["--no-pager", `--unit=${BACKUP}`, "--lines=200"];
const ARG_PREFIX = "AH_E2E_ARG ";
const ARG_COUNT = /^AH_E2E_ARGS (\d+)\s*$/;

const shot = makeShot("services", WAIT);

// The rows of the list in one call, as unit, state and whether error lines or "Mehr Log" are
// offered: the list re-renders under element handles.
async function listRows() {
  return browser.execute(
    (sel) =>
      [...document.querySelectorAll(sel)].map((tr) => ({
        unit: tr.querySelector(".svc-unit")?.textContent.trim() ?? "",
        state: tr.querySelector("[data-state]")?.dataset.state ?? "",
        logToggle: tr.querySelector("button[aria-expanded]") !== null,
        journal: tr.querySelector("td:first-child button") !== null,
      })),
    ROWS,
  );
}

async function waitForUnits(units, what) {
  const want = [...units].sort();
  let got = [];
  await browser.waitUntil(
    async () => {
      got = (await listRows()).map((r) => r.unit).sort();
      return JSON.stringify(got) === JSON.stringify(want);
    },
    { timeout: WAIT, timeoutMsg: `${what}: the list shows ${JSON.stringify(got)}` },
  );
}

// Clicks the button of the row of `unit` that `inner` selects, in one call.
async function clickInRow(unit, inner) {
  const clicked = await browser.execute(
    (sel, u, b) => {
      const tr = [...document.querySelectorAll(sel)].find(
        (row) => row.querySelector(".svc-unit")?.textContent.trim() === u,
      );
      const button = tr?.querySelector(b);
      button?.click();
      return button !== undefined && button !== null;
    },
    ROWS,
    unit,
    inner,
  );
  if (!clicked) throw new Error(`no button ${inner} in the row of ${unit}`);
}

async function openList() {
  await jsClick(await $(".mon-section-foot button"));
  await $(SWITCH).waitForExist({ timeout: 30000, timeoutMsg: "the service list did not load" });
}

async function closeList() {
  await jsClick(await $(".modal-panel .modal-header button"));
  await $(LIST).waitForExist({ timeout: WAIT, reverse: true });
}

async function switchIs(on) {
  return (await $(SWITCH).getAttribute("aria-checked")) === String(on);
}

// The switch flips on the click and stays locked while the server saves it: it is saved once
// it is unlocked in its new place (a failed save flips it back).
async function waitForSwitchSaved(on) {
  await browser.waitUntil(
    () =>
      browser.execute(
        (sel, want) => {
          const sw = document.querySelector(sel);
          return sw !== null && sw.getAttribute("aria-checked") === want && !sw.disabled;
        },
        SWITCH,
        String(on),
      ),
    { timeout: WAIT, timeoutMsg: `the server did not save the switch ${on ? "on" : "off"}` },
  );
}

describe("Monitoring service list of a server (arch-monitoring-ui-3 T11)", () => {
  let conf;

  before(async () => {
    for (const [name, value] of Object.entries({
      AH_E2E_FIXTURE_AGENT: FIXTURE_AGENT,
      AH_E2E_SSH_CONNECTION: SSH_CONNECTION,
    })) {
      if (!value) {
        throw new Error(
          `${name} is not set: run the spec through scripts/tests/desktop_e2e_monitoring.sh`,
        );
      }
    }
    conf = fixtureAgentConf(FIXTURE_AGENT);
    await login();
    // The services card of the server page shows a server's service checks.
    await createCheck(conf.SERVER_ID, CHECK_NAME, "service_process", { mode: "auto" });
    await pushServices(conf);
  });

  it("lists every service of the server, an alias with its unit", async () => {
    await $('.sidebar-nav [data-nav="monitoring"]').click();
    await $('.mon-tabs [data-tab="overview"]').click();
    await $('.mon-overview-toolbar [role="radio"]').click();
    await clickItemByName(".mon-srv-item", ".mon-srv-name", FIXTURE_SERVER);
    await $(".mon-dashboard-name").waitForExist({ timeout: 30000 });
    expect(await textContentOf(await $(".mon-dashboard-name"))).toBe(FIXTURE_SERVER);
    // The check was made past the app's store: its card comes with the page's refresh. A
    // closed card renders no body, so every card is opened on the way.
    await browser.waitUntil(
      () =>
        browser.execute(() => {
          for (const toggle of document.querySelectorAll('.mon-card-toggle[aria-expanded="false"]')) {
            toggle.click();
          }
          return document.querySelector(".mon-section-foot button") !== null;
        }),
      { timeout: REFRESH_WAIT, timeoutMsg: "the server page has no services card" },
    );
    await openList();
    await waitForUnits(ALL_UNITS, "all services");
    const ssh = await browser.execute(
      (sel) =>
        [...document.querySelectorAll(sel)]
          .find((tr) => tr.querySelector(".svc-unit")?.textContent.trim() === "ssh.service")
          ?.querySelector(".svc-aliases")?.textContent ?? "",
      ROWS,
    );
    expect(ssh).toContain("sshd.service");
    // The switch of the error lines is on until an admin turns it off.
    expect(await switchIs(true)).toBe(true);
    await shot("list");
  });

  it("filters by state and finds a service by its alias", async () => {
    const filters = await $$(FILTER);
    expect(filters.length).toBe(4);
    await jsClick(filters[FILTER_INDEX.failed]);
    await waitForUnits([NGINX, BACKUP], "filter failed");
    expect((await listRows()).every((r) => r.state === "failed")).toBe(true);
    await shot("filter-failed");

    await jsClick((await $$(FILTER))[FILTER_INDEX.inactive]);
    await waitForUnits(["apt-daily.service", "fstrim.service"], "filter inactive");
    await jsClick((await $$(FILTER))[FILTER_INDEX.active]);
    await waitForUnits(
      ["ssh.service", "cron.service", "docker.service", "postgresql.service"],
      "filter active",
    );

    await jsClick((await $$(FILTER))[FILTER_INDEX.all]);
    const search = await $(`${LIST} input[type="search"]`);
    await search.setValue("sshd");
    await waitForUnits(["ssh.service"], "search for the alias sshd");
    await shot("search");
    await search.setValue("restic");
    await waitForUnits([BACKUP], "search for restic");
    // WebKitWebDriver's element clear fires no input event, so the bound value would keep
    // "restic"; the field's own clear button is what a user presses anyway.
    await jsClick(await $(`${LIST} .search button.clear`));
    await waitForUnits(ALL_UNITS, "empty search");
  });

  it("shows the error lines of a failed service redacted", async () => {
    const rows = await listRows();
    // Lines go with failed units only, and only the agent's failed units bring any.
    expect(rows.filter((r) => r.logToggle).map((r) => r.unit).sort()).toEqual([NGINX, BACKUP].sort());
    await clickInRow(NGINX, "button[aria-expanded]");
    const pre = await $(`${LIST} .svc-log-lines`);
    await pre.waitForExist({ timeout: WAIT });
    const text = await textContentOf(pre);
    expect(text.split("\n").length).toBe(NGINX_LINES.length);
    expect(text).toContain(NGINX_LINES[0]);
    expect(text).toContain("[REDACTED]");
    for (const secret of SECRETS) expect(text).not.toContain(secret);
    await shot("error-lines");
  });

  it("the switch drops the error lines until it is on and the agent reports again", async () => {
    await jsClick(await $(SWITCH));
    await waitForSwitchSaved(false);
    await browser.waitUntil(async () => (await listRows()).every((r) => !r.logToggle), {
      timeout: WAIT,
      timeoutMsg: "the error lines stayed after the switch went off",
    });
    expect(await $(`${LIST} .svc-log-lines`).isExisting()).toBe(false);
    await shot("switch-off");

    // The server keeps the switch: a new load of the list finds it off and no lines.
    await closeList();
    await openList();
    expect(await switchIs(false)).toBe(true);
    expect((await listRows()).some((r) => r.logToggle)).toBe(false);
    // A report while it is off stores no lines.
    await pushServices(conf);
    await closeList();
    await openList();
    expect((await listRows()).some((r) => r.logToggle)).toBe(false);

    await jsClick(await $(SWITCH));
    // A report before the server saved the switch would store no lines.
    await waitForSwitchSaved(true);
    await pushServices(conf);
    await closeList();
    await openList();
    await browser.waitUntil(
      async () => (await listRows()).filter((r) => r.logToggle).length === 2,
      { timeout: WAIT, timeoutMsg: "the error lines did not come back with the next report" },
    );
  });

  it("opens the journal of a unit over the server's SSH connection", async () => {
    const rows = await listRows();
    // "Mehr Log" at every systemd service, failed or not.
    expect(rows.every((r) => r.journal)).toBe(true);
    await clickInRow(BACKUP, "td:first-child button");
    // The list makes way for the terminal tab.
    await $(LIST).waitForExist({ timeout: WAIT, reverse: true });
    const tab = await $(SESSION_TAB);
    await tab.waitForExist({ timeout: WAIT });
    // The server names a server's connection "{server} · {own}" (R-1210); the tab adds the unit.
    expect(await textContentOf(await tab.$(".session-tab-name"))).toBe(
      `${FIXTURE_SERVER} · ${SSH_CONNECTION} · ${BACKUP}`,
    );
    expect(await tab.getAttribute("aria-selected")).toBe("true");

    // The run gives ssh a known_hosts of its own, empty at the start: ssh asks first.
    const first = await waitForTerminalLine(/\(yes\/no|password:/i);
    if (/\(yes\/no/.test(first)) {
      await typeInTerminal("yes");
      await waitForTerminalLine(/password:/i);
    }
    await typeInTerminal("e2e");
    const count = ARG_COUNT.exec(await waitForTerminalLine(ARG_COUNT))[1];
    // The remote shell split the fixed command into exactly these arguments, the unit's "@"
    // and "\" untouched.
    const args = (await terminalLines())
      .filter((l) => l.startsWith(ARG_PREFIX))
      .map((l) => l.slice(ARG_PREFIX.length).trimEnd());
    expect(args).toEqual(JOURNAL_ARGS);
    expect(Number(count)).toBe(JOURNAL_ARGS.length);
    // The tab runs the one command and no shell: it ends with it, without snippets or files.
    await $(`${TERM_PANE} .term-ended`).waitForExist({ timeout: WAIT });
    const head = `${TERM_PANE} .term-head`;
    // The header's icons carry their Lucide class: the font buttons are there, the shell's not.
    expect(await $(`${head} svg.lucide-a-arrow-down`).isExisting()).toBe(true);
    for (const icon of ["square-code", "folder-open"]) {
      expect(await $(`${head} svg.lucide-${icon}`).isExisting()).toBe(false);
    }
    await shot("journal");
  });
});

// The units of the fixture block, without the alias, which is no row of its own.
const ALL_UNITS = [
  "ssh.service",
  "cron.service",
  "docker.service",
  "postgresql.service",
  NGINX,
  BACKUP,
  "apt-daily.service",
  "fstrim.service",
];

// The systemd block of an agent report, invented for the look of the list: a web server that
// cannot bind its port, a backup that cannot reach its repository, an alias, a oneshot that
// stays active and two that ran and ended. Times are relative to the push.
function servicesBlock() {
  const now = Date.now();
  const iso = (ago) => new Date(now - ago).toISOString();
  const minute = 60000;
  const hour = 60 * minute;
  const day = 24 * hour;
  const mib = 1024 * 1024;
  const unit = (name, active, sub, fields = {}) => ({
    unit: name,
    active_state: active,
    sub_state: sub,
    enabled_state: "enabled",
    result: "success",
    since: iso(3 * day),
    restarts: "0",
    ...fields,
  });
  const failed = {
    [NGINX]: { result: "exit-code", exit: "status=1/FAILURE", since: iso(40 * minute), restarts: "5" },
    [BACKUP]: { result: "exit-code", exit: "status=3", since: iso(3 * hour), restarts: "0" },
  };
  return {
    all_services: [
      unit("ssh.service", "active", "running", { memory_bytes: String(6 * mib) }),
      { unit: "sshd.service", enabled_state: "alias", alias_of: "ssh.service", active_state: "active" },
      unit("cron.service", "active", "running", { memory_bytes: String(2 * mib) }),
      unit("docker.service", "active", "running", {
        memory_bytes: String(118 * mib),
        restarts: "1",
        since: iso(2 * day),
      }),
      unit("postgresql.service", "active", "exited"),
      unit(NGINX, "failed", "failed", failed[NGINX]),
      unit(BACKUP, "failed", "failed", { ...failed[BACKUP], enabled_state: "indirect" }),
      unit("apt-daily.service", "inactive", "dead", { enabled_state: "static", since: iso(9 * hour) }),
      unit("fstrim.service", "inactive", "dead", { enabled_state: "static", since: iso(4 * day) }),
    ],
    failed: [NGINX, BACKUP],
    failed_details: Object.entries(failed).map(([name, d]) => ({ unit: name, ...d })),
    enabled_inactive: [],
    failed_logs: {
      [NGINX]: { lines: NGINX_LINES, since: failed[NGINX].since },
      [BACKUP]: {
        lines: [
          "Fatal: unable to open repository at sftp:backup@203.0.113.7:/srv/restic",
          "ssh: connect to host 203.0.113.7 port 22: No route to host",
          `${BACKUP}: Failed with result 'exit-code'.`,
        ],
        since: failed[BACKUP].since,
      },
    },
  };
}

async function pushServices(c) {
  const url = `${c.MONITOR_URL}/agent/${encodeURIComponent(c.SERVER_ID)}/report`;
  const res = await postReport(url, c.API_KEY, { systemd: servicesBlock() });
  if (res.status !== 200) throw new Error(`the services report was refused: ${res.status} ${res.text}`);
}
