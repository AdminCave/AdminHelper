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
//
// The second part (arch-monitoring-ui-2 T11, R-1227) shows the detail views on a second
// server: its agent is provisioned and never runs, and the spec pushes a fixed report through
// the real agent route with that agent's own key, so every view has data a test box does not
// have (compose projects, Proxmox guests, ZFS pools, package and process names).

import { spawnSync } from "node:child_process";
import { login, clickItemByName, jsClick, textContentOf } from "../lib/live.js";
import { makeShot, fixtureAgentConf, createCheck, postReport } from "../lib/monitoring-live.js";

const AGENT = process.env.AH_E2E_AGENT;
const FINDING = process.env.AH_E2E_FINDING;
const FIXTURE_AGENT = process.env.AH_E2E_FIXTURE_AGENT;
const SERVER_NAME = "e2e-server";
const FIXTURE_SERVER = "e2e-fixture";
// One check per detail view; every type is push only, so only the pushed report rates it.
const FIXTURE_CHECKS = {
  "fixture-live": "agent_resources",
  "fixture-system": "system_state",
  "fixture-zfs": "zfs_health",
  "fixture-docker": "docker_health",
  "fixture-backups": "proxmox_backup",
};
const SECURITY_PACKAGES = [
  "openssl",
  "libssl3",
  "linux-image-amd64",
  "libc6",
  "curl",
  "libcurl4",
  "sudo",
];
const CARD = ".mon-card";
const SILENT = '.status-footer [data-field="silent"]';
// The System card's title, the same in every language of the app.
const SYSTEM_TITLE = "System";
const CROSS_TABS = ["certs", "backups", "updates", "findings"];
// The auto-refresh of the monitoring page is 30 s, the pulse of the status bar 60 s.
const REFRESH_WAIT = 75000;

const shot = makeShot("server-page", 5000);

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

describe("Monitoring detail views with a fixture report (arch-monitoring-ui-2 T11)", () => {
  before(async () => {
    if (!FIXTURE_AGENT) {
      throw new Error(
        "AH_E2E_FIXTURE_AGENT is not set: run the spec through scripts/tests/desktop_e2e_monitoring.sh",
      );
    }
    const conf = fixtureAgentConf(FIXTURE_AGENT);
    for (const [name, type] of Object.entries(FIXTURE_CHECKS)) {
      await createCheck(conf.SERVER_ID, name, type);
    }
    const url = `${conf.MONITOR_URL}/agent/${encodeURIComponent(conf.SERVER_ID)}/report`;
    const res = await postReport(url, conf.API_KEY, fixtureReport());
    if (res.status !== 200) throw new Error(`the fixture report was refused: ${res.status} ${res.text}`);
    expect(JSON.parse(res.text).checksUpdated).toBe(Object.keys(FIXTURE_CHECKS).length);
  });

  it("opens the fixture server's page with every check of the report", async () => {
    await $('.mon-tabs [data-tab="overview"]').click();
    await $('.mon-overview-toolbar [role="radio"]').click();
    // The checks were made past the app's store: the list names the server, and its page shows
    // them, only after the store's refresh, which is slower than clickItemByName waits.
    await browser.waitUntil(
      async () =>
        (
          await browser.execute(() =>
            [...document.querySelectorAll(".mon-srv-item .mon-srv-name")].map((el) =>
              el.textContent.trim(),
            ),
          )
        ).includes(FIXTURE_SERVER),
      { timeout: REFRESH_WAIT, timeoutMsg: `the server list does not name ${FIXTURE_SERVER}` },
    );
    await clickItemByName(".mon-srv-item", ".mon-srv-name", FIXTURE_SERVER);
    await $(".mon-dashboard-name").waitForExist({ timeout: 30000 });
    expect(await textContentOf(await $(".mon-dashboard-name"))).toBe(FIXTURE_SERVER);
    await browser.waitUntil(
      async () => {
        const names = await openCardsAndListLines();
        return Object.keys(FIXTURE_CHECKS).every((n) => names.includes(n));
      },
      { timeout: REFRESH_WAIT, timeoutMsg: "the fixture checks are not on the server page" },
    );
  });

  it("shows the top processes of a warning resource check", async () => {
    await expandLine("fixture-live");
    const top = await browser.execute(() =>
      ["cpu", "memory"].map((key) =>
        [...document.querySelectorAll(`table.top-table[data-top="${key}"] tbody tr`)].map(
          (tr) => tr.querySelector("td").textContent.trim(),
        ),
      ),
    );
    expect(top[0]).toEqual(["php-fpm8.2", "mysqld", "clamd", "dovecot", "nginx"]);
    expect(top[1]).toEqual(["mysqld", "clamd", "php-fpm8.2", "redis-server", "dovecot"]);
    await shot("fixture-live");
  });

  it("names the packages and the killed process behind the system state", async () => {
    await expandLine("fixture-system");
    const points = await browser.execute(() =>
      Object.fromEntries(
        [...document.querySelectorAll(".mon-expand-names[data-point]")].map((el) => [
          el.dataset.point,
          [...el.querySelectorAll(".ui-tag")].map((t) => t.textContent.trim()),
        ]),
      ),
    );
    expect(points.reboot).toEqual(["linux-image-amd64"]);
    expect(points.security_updates).toEqual(SECURITY_PACKAGES);
    expect(points.oom).toEqual(["php-fpm8.2 (PID 48213)"]);
    await shot("fixture-system");
  });

  it("shows scrub, fragmentation and vdev errors under each ZFS pool", async () => {
    await expandLine("fixture-zfs");
    const pools = await browser.execute(() =>
      Object.fromEntries(
        [...document.querySelectorAll(".mon-expand-names.under-bar[data-pool]")].map((el) => [
          el.dataset.pool,
          [...el.querySelectorAll(".mon-chip")].map((c) => c.textContent.trim()),
        ]),
      ),
    );
    expect(Object.keys(pools).sort()).toEqual(["rpool", "tank"]);
    expect(pools.rpool.length).toBe(2);
    // Scrub, fragmentation and the one vdev with errors.
    expect(pools.tank.length).toBe(3);
    expect(pools.tank[2]).toContain("sdc");
    expect(pools.tank[2]).toContain("14");
    await shot("fixture-zfs");
  });

  it("groups the containers by compose project with uptime and ports", async () => {
    await expandLine("fixture-docker");
    const groups = await browser.execute(() =>
      [...document.querySelectorAll("details.mon-expand-group")].map((g) => ({
        project: g.dataset.project,
        open: g.open,
      })),
    );
    // A project with a problem first and open, a healthy one closed.
    expect(groups[0]).toEqual({ project: "shop", open: true });
    expect(groups.find((g) => g.project === "mailcow")).toEqual({ project: "mailcow", open: false });
    expect(groups.map((g) => g.project)).toContain("");
    const web = await browser.execute(() => {
      const el = document.querySelector('.mon-expand-names[data-container="id:5b0e7d21c4a9"]');
      return el && { uptime: el.querySelector("[data-uptime]") !== null, text: el.textContent };
    });
    expect(web).not.toBeNull();
    expect(web.uptime).toBe(true);
    expect(web.text).toContain("127.0.0.1:8080->80/tcp");
    await scrollToLine("fixture-docker");
    await shot("fixture-docker");

    await browser.execute(() => {
      document.querySelector('details.mon-expand-group[data-project="mailcow"]').open = true;
    });
    const mailcow = await browser.execute(
      () =>
        document.querySelector('.mon-expand-names[data-container="id:9c41f0a7be32"]')?.textContent ??
        "",
    );
    expect(mailcow).toContain("0.0.0.0:443->443/tcp");
    await scrollToLine("fixture-docker");
    await shot("fixture-docker-mailcow");
  });

  it("shows storage, jobs, verification and the last error of each guest", async () => {
    await expandLine("fixture-backups");
    const guests = await browser.execute(() =>
      Object.fromEntries(
        [...document.querySelectorAll(".mon-expand-names[data-vm]")].map((el) => [
          el.dataset.vm,
          {
            text: el.textContent,
            error: el.querySelector(".mon-expand-error")?.textContent ?? null,
            muted: el.querySelectorAll(".mon-chip.chip-muted").length,
          },
        ]),
      ),
    );
    expect(guests["101"].text).toContain("pbs-main");
    expect(guests["101"].text).toContain("backup-nightly");
    expect(guests["101"].error).toBeNull();
    expect(guests["104"].error).toContain("ERROR: Backup of VM 104 failed");
    // No job covers the container: its one chip says so.
    expect(guests["110"].muted).toBe(1);
    await shot("fixture-backups");
  });

  it("lists the guests and the last error in the backups tab", async () => {
    await $('.mon-tabs [data-tab="backups"]').click();
    const content = '.mon-tab-content[data-tab="backups"]';
    await browser.waitUntil(
      async () =>
        (await browser.execute((sel) => document.querySelectorAll(`${sel} [data-state]`).length, content)) >= 3,
      { timeout: 30000, timeoutMsg: "the backups tab does not list the fixture guests" },
    );
    const tab = await browser.execute(
      (sel) => ({
        states: [...document.querySelectorAll(`${sel} [data-state]`)].map((el) => el.dataset.state),
        text: document.querySelector(sel).textContent,
      }),
      content,
    );
    expect([...tab.states].sort()).toEqual(["missing", "ok", "outdated"]);
    expect(tab.text).toContain("No space left on device");
    await shot("fixture-tab-backups");
  });

  it("names the first packages with updates in the updates tab", async () => {
    await $('.mon-tabs [data-tab="updates"]').click();
    const content = '.mon-tab-content[data-tab="updates"]';
    await $(`${content} .packages`).waitForExist({
      timeout: 30000,
      timeoutMsg: "the updates tab names no packages",
    });
    const cell = await browser.execute(
      (sel) => ({
        shown: document.querySelector(`${sel} .packages`).textContent.trim(),
        more: document.querySelector(`${sel} .packages-more`)?.textContent.trim() ?? "",
      }),
      content,
    );
    expect(cell.shown).toBe(SECURITY_PACKAGES.slice(0, 5).join(", "));
    expect(cell.more).toMatch(new RegExp(`^\\+${SECURITY_PACKAGES.length - 5} `));
    await shot("fixture-tab-updates");
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

// A fixed report in the agent's wire form, invented for the look of the views: a mail and a
// shop stack, three guests (one backed up, one outdated with a failed run, one never), a
// healthy and a degraded pool, pending security updates with a reboot and an OOM kill, and a
// busy CPU. Times are relative to the push.
function fixtureReport() {
  const now = Math.floor(Date.now() / 1000);
  const hour = 3600;
  const day = 24 * hour;
  const mib = 1024 * 1024;
  const container = (fields) => ({
    state: "running",
    restart_count: 0,
    exit_code: 0,
    oom_killed: false,
    restart_policy: "unless-stopped",
    ports: [],
    ...fields,
  });
  const mailcow = (id, service, image, ports) =>
    container({
      id,
      name: `mailcowdockerized-${service}-mailcow-1`,
      image,
      compose_project: "mailcow",
      compose_service: `${service}-mailcow`,
      ports,
      started_at: now - 12 * day,
    });
  return {
    uptime_seconds: 3 * day,
    docker: {
      available: true,
      containers: [
        mailcow("3f8a1c6d2e07", "postfix", "ghcr.io/mailcow/postfix:1.80", [
          "0.0.0.0:25->25/tcp",
          "0.0.0.0:587->587/tcp",
        ]),
        mailcow("9c41f0a7be32", "nginx", "ghcr.io/mailcow/nginx:1.03", [
          "0.0.0.0:80->80/tcp",
          "0.0.0.0:443->443/tcp",
        ]),
        mailcow("d27b5e90a1f4", "dovecot", "ghcr.io/mailcow/dovecot:2.33", ["0.0.0.0:993->993/tcp"]),
        container({
          id: "5b0e7d21c4a9",
          name: "shop-web-1",
          image: "nginx:1.27",
          compose_project: "shop",
          compose_service: "web",
          ports: ["127.0.0.1:8080->80/tcp"],
          started_at: now - 2 * hour,
        }),
        container({
          id: "e61c09b47d58",
          name: "shop-worker-1",
          image: "registry.example.com/shop/worker:2.4",
          state: "exited",
          exit_code: 1,
          restart_policy: "no",
          compose_project: "shop",
          compose_service: "worker",
          started_at: now - 40 * 60,
        }),
        container({
          id: "a90d3b7c55e1",
          name: "watchtower",
          image: "containrrr/watchtower:latest",
          started_at: now - 3 * day,
        }),
      ],
    },
    proxmox: {
      available: true,
      vms: [
        {
          vmid: 101,
          name: "mail",
          type: "qemu",
          status: "running",
          last_backup_ts: now - 6 * hour,
          backup_storage: "pbs-main",
          backup_size: 18_400 * mib,
          backup_verify: "ok",
          backup_jobs: [{ id: "backup-nightly", schedule: "21:00", storage: "pbs-main" }],
        },
        {
          vmid: 104,
          name: "shop-db",
          type: "qemu",
          status: "running",
          last_backup_ts: now - 50 * hour,
          backup_storage: "pbs-main",
          backup_size: 41_200 * mib,
          backup_verify: "failed",
          backup_jobs: [{ id: "backup-nightly", schedule: "21:00", storage: "pbs-main" }],
          backup_error:
            "ERROR: Backup of VM 104 failed - vma_queue_write: write error - No space left on device",
          backup_error_ts: now - 3 * hour,
        },
        { vmid: 110, name: "ci-runner", type: "lxc", status: "running", backup_jobs: [] },
      ],
    },
    zfs: {
      available: true,
      pools: [
        {
          name: "rpool",
          health: "ONLINE",
          capacity_percent: 41,
          fragmentation_percent: 12,
          scrub: { state: "FINISHED", errors: 0, end: now - 4 * day },
          vdev_errors: [],
        },
        {
          name: "tank",
          health: "DEGRADED",
          capacity_percent: 83,
          fragmentation_percent: 37,
          scrub: { state: "SCANNING", errors: 0 },
          vdev_errors: [{ name: "sdc", read: 0, write: 0, checksum: 14 }],
        },
      ],
    },
    system_state: {
      reboot_required: true,
      time_synchronized: true,
      security_updates: SECURITY_PACKAGES.length,
      oom_kills: 1,
      security_packages: SECURITY_PACKAGES,
      reboot_packages: ["linux-image-amd64"],
      oom_processes: [{ pid: 48213, name: "php-fpm8.2" }],
    },
    resources: {
      cpu_percent: 93.4,
      memory_percent: 71.2,
      memory_used_mb: 11665,
      memory_total_mb: 16384,
      swap_percent: 4.1,
      swap_total_mb: 2048,
      swap_used_mb: 84,
      load_1m: 7.9,
      load_5m: 5.2,
      load_15m: 3.4,
      cpu_count: 8,
      disks: [{ mount: "/", percent: 58, used_gb: 116, total_gb: 200, free_gb: 84, fstype: "ext4" }],
      top_processes: {
        cpu: [
          { pid: 48213, name: "php-fpm8.2", cpu_pct: 41.7 },
          { pid: 2210, name: "mysqld", cpu_pct: 22.3 },
          { pid: 31877, name: "clamd", cpu_pct: 12.9 },
          { pid: 1543, name: "dovecot", cpu_pct: 6.1 },
          { pid: 912, name: "nginx", cpu_pct: 3.8 },
        ],
        memory: [
          { pid: 2210, name: "mysqld", rss: 4300 * mib },
          { pid: 31877, name: "clamd", rss: 1330 * mib },
          { pid: 48213, name: "php-fpm8.2", rss: 512 * mib },
          { pid: 4411, name: "redis-server", rss: 310 * mib },
          { pid: 1543, name: "dovecot", rss: 96 * mib },
        ],
      },
    },
  };
}

// Opens every closed card of the server page (a closed card renders no lines) and returns the
// names of the check lines shown.
async function openCardsAndListLines() {
  return browser.execute(() => {
    for (const toggle of document.querySelectorAll('.mon-card-toggle[aria-expanded="false"]')) {
      toggle.click();
    }
    return [...document.querySelectorAll(".mon-line-name")].map((el) => el.textContent.trim());
  });
}

// Expands the line of the named check (the page keeps one line open) and scrolls it to the
// top, retried in one call per round: the page re-renders on its refresh.
async function expandLine(name) {
  await browser.waitUntil(
    () =>
      browser.execute((n) => {
        const wrapper = [...document.querySelectorAll(".mon-line-wrapper")].find(
          (w) => w.querySelector(".mon-line-name")?.textContent.trim() === n,
        );
        if (!wrapper) return false;
        if (!wrapper.classList.contains("open")) {
          wrapper.querySelector(".mon-line").click();
          return false;
        }
        return wrapper.querySelector(".mon-line-expand") !== null;
      }, name),
    { timeout: 30000, interval: 500, timeoutMsg: `the line ${name} did not open` },
  );
  await scrollToLine(name);
}

async function scrollToLine(name) {
  await browser.execute((n) => {
    [...document.querySelectorAll(".mon-line-wrapper")]
      .find((w) => w.querySelector(".mon-line-name")?.textContent.trim() === n)
      ?.scrollIntoView({ block: "start" });
  }, name);
}
