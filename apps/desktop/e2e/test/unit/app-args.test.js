// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// AH_E2E_WORKSPACE picks what the session opens: a workspace with `--workspace <id>`,
// or the launcher without arguments. The id follows WorkspaceId::parse in workspace.rs;
// a bad one has to stop wdio while it loads the config, not after a build of minutes.
// A fake `cargo` stands in for the build and leaves a marker: no display, no Rust.

import { test, after } from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { appArgs } from '../lib/app-args.js';

const e2eDir = fileURLToPath(new URL('../..', import.meta.url));
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'ah-app-args-'));

after(() => {
  fs.rmSync(tmp, { recursive: true, force: true });
});

test('a set AH_E2E_WORKSPACE opens that workspace', () => {
  for (const id of ['standard', 'w-0a1b2c3d', 'a'.repeat(32)]) {
    assert.deepEqual(appArgs({ AH_E2E_WORKSPACE: id }), ['--workspace', id]);
  }
});

test('an empty or unset AH_E2E_WORKSPACE opens the launcher', () => {
  assert.deepEqual(appArgs({ AH_E2E_WORKSPACE: '' }), []);
  assert.deepEqual(appArgs({}), []);
});

test('an id the app would refuse is an error', () => {
  // The bad ids of bad_ids_are_usage_errors in workspace.rs, one character too many,
  // and blanks around a good id.
  const bads = ['../x', 'a/b', 'Standard', 'STANDARD', 'über', 'a b', 'a_b', 'a.b', 'a|b', '\u0000'];
  for (const bad of [...bads, 'a'.repeat(33), 'standard\n', ' standard']) {
    assert.throws(
      () => appArgs({ AH_E2E_WORKSPACE: bad }),
      (err) => err.message.startsWith(`AH_E2E_WORKSPACE=${JSON.stringify(bad)} is no workspace id`),
      JSON.stringify(bad),
    );
  }
});

test('the session capabilities carry the arguments', async () => {
  const before = process.env.AH_E2E_WORKSPACE;
  process.env.AH_E2E_WORKSPACE = 'standard';
  try {
    const { config } = await import('../../wdio.conf.js');
    assert.deepEqual(config.capabilities[0]['tauri:options'].args, ['--workspace', 'standard']);
  } finally {
    if (before === undefined) delete process.env.AH_E2E_WORKSPACE;
    else process.env.AH_E2E_WORKSPACE = before;
  }
});

// `wdio run` as run.sh starts it; `built` tells whether onPrepare reached the build.
function wdioRun(workspace) {
  const dir = fs.mkdtempSync(path.join(tmp, 'run-'));
  const bin = path.join(dir, 'bin');
  const marker = path.join(dir, 'cargo-ran');
  fs.mkdirSync(bin);
  fs.writeFileSync(path.join(bin, 'cargo'), `#!/bin/sh\ntouch '${marker}'\nexit 1\n`, { mode: 0o755 });
  const r = spawnSync(
    process.execPath,
    [
      path.join(e2eDir, 'node_modules/@wdio/cli/bin/wdio.js'),
      'run',
      'wdio.conf.js',
      '--spec',
      'test/specs/smoke.e2e.js',
    ],
    {
      cwd: e2eDir,
      encoding: 'utf8',
      timeout: 60000,
      env: {
        ...process.env,
        PATH: `${bin}${path.delimiter}${process.env.PATH}`,
        AH_OUT_DIR: path.join(dir, 'out'),
        // Never the real driver, should a run get that far.
        TAURI_DRIVER_BIN: path.join(dir, 'no-tauri-driver'),
        AH_E2E_WORKSPACE: workspace,
      },
    },
  );
  return {
    status: r.status,
    log: `exit ${r.status} (${r.error ?? r.signal ?? ''}):\n${r.stdout}${r.stderr}`,
    built: fs.existsSync(marker),
  };
}

test('a bad id stops wdio while it loads the config, before the build', () => {
  const bad = wdioRun('../x');
  assert.equal(bad.status, 1, bad.log);
  assert.match(bad.log, /AH_E2E_WORKSPACE="\.\.\/x" is no workspace id/, bad.log);
  assert.equal(bad.built, false, `the build ran:\n${bad.log}`);

  // A good id gets to the build: the marker does show up.
  const good = wdioRun('standard');
  assert.equal(good.built, true, `the build did not run:\n${good.log}`);
});
