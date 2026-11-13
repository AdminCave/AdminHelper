// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// What the live monitoring specs (monitoring-server-page.live.js, monitoring-services.live.js)
// share: the theme switch and the screenshot of a step in both themes, and the three helpers
// that seed a fixture agent's server: its monitor.conf, a check through the app's API proxy and
// the agent's push with its key.

import path from "node:path";
import https from "node:https";
import { spawnSync } from "node:child_process";
import { ahOutDir } from "../../wdio.conf.js";
import { jsClick } from "./live.js";

async function themeIs(theme) {
  return (await browser.execute(() => document.documentElement.dataset.theme ?? "dark")) === theme;
}

export async function setTheme(theme, timeout) {
  if (await themeIs(theme)) return;
  // The only item of the sidebar footer with an aria-label (theme-toggle.live.js).
  await jsClick(await $(".sidebar-bottom .sidebar-item[aria-label]"));
  await browser.waitUntil(() => themeIs(theme), {
    timeout,
    timeoutMsg: `the theme did not switch to ${theme}`,
  });
}

// An alarm toast sits in the corner of the screenshot and hides what is below it.
async function dismissToasts() {
  for (const button of await $$(".toast .dismiss")) await jsClick(button);
  await browser.waitUntil(async () => (await $$(".toast")).length === 0, {
    timeout: 30000,
    timeoutMsg: "the toasts did not close",
  });
}

// The screenshot function of one spec: the file names start with `prefix` and count the
// steps of that spec alone. Each step is taken in the dark and the light theme, back in dark
// afterwards; `themeTimeout` bounds the wait for a theme switch.
export function makeShot(prefix, themeTimeout) {
  let step = 0;
  return async function shot(name) {
    step += 1;
    const base = `${prefix}-${String(step).padStart(2, "0")}-${name}`;
    for (const theme of ["dark", "light"]) {
      await setTheme(theme, themeTimeout);
      // Let the theme's transitions settle before the capture.
      await browser.pause(400);
      await dismissToasts();
      await browser.saveScreenshot(path.join(ahOutDir, "screenshots", `${base}-${theme}.png`));
    }
    await setTheme("dark", themeTimeout);
  };
}

// The provisioned fixture agent's monitor.conf (KEY="value" lines). Its output holds the
// agent's API key: an error names the exit code only.
export function fixtureAgentConf(container) {
  const run = spawnSync("docker", ["exec", container, "cat", "/etc/adminhelper/monitor.conf"], {
    encoding: "utf8",
    timeout: 30000,
  });
  if (run.status !== 0) throw new Error(`cannot read the fixture agent's config (exit ${run.status})`);
  const conf = {};
  for (const line of run.stdout.split("\n")) {
    const m = /^([A-Z_]+)="(.*)"$/.exec(line);
    if (m) conf[m[1]] = m[2];
  }
  for (const key of ["MONITOR_URL", "API_KEY", "SERVER_ID"]) {
    if (!conf[key]) throw new Error(`the fixture agent's config has no ${key}`);
  }
  return conf;
}

// Creates a check through the app's own API proxy, as the check editor does. The first bad
// report rates it (consecutive_fails 1), so the views show their problem state.
export async function createCheck(serverId, name, checkType, config = {}) {
  const body = JSON.stringify({
    name,
    server_id: serverId,
    check_type: checkType,
    interval: "5m",
    consecutive_fails: 1,
    config,
  });
  const result = await browser.execute(
    async (b) =>
      window.__TAURI__.core
        .invoke("api_proxy", { method: "POST", path: "/api/monitoring/checks", body: b })
        .then((value) => ({ value }))
        .catch((e) => ({ rejected: String((e && e.message) || e) })),
    body,
  );
  if (result.rejected !== undefined) throw new Error(`creating ${name}: ${result.rejected}`);
}

// The agent's push, with its key as the agent sends it. The local test stack's gateway has a
// self-signed certificate, which the app accepts with allowSelfSignedCerts.
export function postReport(url, apiKey, report) {
  const data = JSON.stringify(report);
  return new Promise((resolve, reject) => {
    const req = https.request(
      url,
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Content-Length": Buffer.byteLength(data),
          "X-API-Key": apiKey,
        },
        rejectUnauthorized: false,
        timeout: 30000,
      },
      (res) => {
        let text = "";
        res.setEncoding("utf8");
        res.on("data", (chunk) => (text += chunk));
        res.on("end", () => resolve({ status: res.statusCode, text }));
      },
    );
    req.on("timeout", () => req.destroy(new Error("the report timed out")));
    req.on("error", reject);
    req.end(data);
  });
}
