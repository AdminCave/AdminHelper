// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// AH_E2E_WORKSPACE picks what the session opens: a workspace with `--workspace <id>`,
// or the launcher without arguments. The id follows WorkspaceId::parse in workspace.rs;
// a bad one has to stop wdio while it loads the config, not after a build of minutes.
// A fake `cargo` stands in for the build and leaves a marker: no display, no Rust.
// wdio.workspaces.conf.js opens two workspaces at once, from AH_E2E_WORKSPACE_A and
// AH_E2E_WORKSPACE_B, each behind a tauri-driver of its own; a fake driver listens on
// its port and writes down its arguments.

import { test, after } from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { appArgs, workspaceSessions } from '../lib/app-args.js';

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
function wdioRun(env, args = ['wdio.conf.js', '--spec', 'test/specs/smoke.e2e.js']) {
  const dir = fs.mkdtempSync(path.join(tmp, 'run-'));
  const bin = path.join(dir, 'bin');
  const marker = path.join(dir, 'cargo-ran');
  fs.mkdirSync(bin);
  fs.writeFileSync(path.join(bin, 'cargo'), `#!/bin/sh\ntouch '${marker}'\nexit 1\n`, { mode: 0o755 });
  const r = spawnSync(
    process.execPath,
    [path.join(e2eDir, 'node_modules/@wdio/cli/bin/wdio.js'), 'run', ...args],
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
        ...env,
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
  const bad = wdioRun({ AH_E2E_WORKSPACE: '../x' });
  assert.equal(bad.status, 1, bad.log);
  assert.match(bad.log, /AH_E2E_WORKSPACE="\.\.\/x" is no workspace id/, bad.log);
  assert.equal(bad.built, false, `the build ran:\n${bad.log}`);

  // A good id gets to the build: the marker does show up.
  const good = wdioRun({ AH_E2E_WORKSPACE: 'standard' });
  assert.equal(good.built, true, `the build did not run:\n${good.log}`);
});

// Node loads wdio.conf.js once per process. The tests below load it through
// wdio.workspaces.conf.js, so they stay after the one above that loads it with
// AH_E2E_WORKSPACE=standard.
const BOTH = { AH_E2E_WORKSPACE_A: 'standard', AH_E2E_WORKSPACE_B: 'w-0a1b2c3d' };

async function withEnv(vars, fn) {
  const before = Object.fromEntries(Object.keys(vars).map((k) => [k, process.env[k]]));
  Object.assign(process.env, vars);
  try {
    return await fn();
  } finally {
    for (const [k, v] of Object.entries(before)) {
      if (v === undefined) delete process.env[k];
      else process.env[k] = v;
    }
  }
}

test('appArgs reads the variable it is given', () => {
  const env = { AH_E2E_WORKSPACE: 'standard', AH_E2E_WORKSPACE_A: 'w-0a1b2c3d' };
  assert.deepEqual(appArgs(env, 'AH_E2E_WORKSPACE_A'), ['--workspace', 'w-0a1b2c3d']);
  assert.deepEqual(appArgs(env, 'AH_E2E_WORKSPACE_B'), []);
  assert.throws(
    () => appArgs({ AH_E2E_WORKSPACE_B: '../x' }, 'AH_E2E_WORKSPACE_B'),
    (err) => err.message.startsWith('AH_E2E_WORKSPACE_B="../x" is no workspace id'),
  );
});

test('two sessions, each with its workspace and tauri-driver ports of its own', () => {
  assert.deepEqual(workspaceSessions(BOTH), [
    {
      name: 'wsA',
      variable: 'AH_E2E_WORKSPACE_A',
      port: 4444,
      nativePort: 4445,
      args: ['--workspace', 'standard'],
    },
    {
      name: 'wsB',
      variable: 'AH_E2E_WORKSPACE_B',
      port: 4446,
      nativePort: 4447,
      args: ['--workspace', 'w-0a1b2c3d'],
    },
  ]);
});

test('each session needs a workspace, and not the one of the other', () => {
  const cases = [
    [{ AH_E2E_WORKSPACE_B: 'w-0a1b2c3d' }, 'AH_E2E_WORKSPACE_A is not set'],
    [{ ...BOTH, AH_E2E_WORKSPACE_A: '' }, 'AH_E2E_WORKSPACE_A is not set'],
    [{ AH_E2E_WORKSPACE_A: 'standard' }, 'AH_E2E_WORKSPACE_B is not set'],
    // The variable of wdio.conf.js opens no session here.
    [{ AH_E2E_WORKSPACE: 'standard' }, 'AH_E2E_WORKSPACE_A is not set'],
    [{ ...BOTH, AH_E2E_WORKSPACE_B: 'Kunde B' }, 'AH_E2E_WORKSPACE_B="Kunde B" is no workspace id'],
    [
      { AH_E2E_WORKSPACE_A: 'standard', AH_E2E_WORKSPACE_B: 'standard' },
      'AH_E2E_WORKSPACE_A and AH_E2E_WORKSPACE_B both name standard',
    ],
  ];
  for (const [env, message] of cases) {
    assert.throws(
      () => workspaceSessions(env),
      (err) => err.message.startsWith(message),
      JSON.stringify(env),
    );
  }
});

test('the multiremote capabilities carry both sessions, the specs are its own', async () => {
  const { config } = await withEnv(BOTH, () => import('../../wdio.workspaces.conf.js'));
  const { application, config: single } = await import('../../wdio.conf.js');
  const session = (port, id) => ({
    hostname: '127.0.0.1',
    port,
    capabilities: { 'tauri:options': { application, args: ['--workspace', id] } },
  });
  assert.deepEqual(config.capabilities, {
    wsA: session(4444, 'standard'),
    wsB: session(4446, 'w-0a1b2c3d'),
  });
  // `npm test` (wdio.conf.js) never runs a multiremote spec, and the reverse.
  assert.deepEqual(config.specs, ['./test/specs/**/*.workspaces.js']);
  assert.deepEqual(single.specs, ['./test/specs/**/*.e2e.js']);
  // The build that stops on failure (onprepare.test.js) is the one of wdio.conf.js.
  assert.equal(config.onPrepare, single.onPrepare);
});

async function waitFor(check, ms) {
  const t0 = Date.now();
  while (!check()) {
    if (Date.now() - t0 > ms) return false;
    await new Promise((res) => setTimeout(res, 50));
  }
  return true;
}

test('beforeSession starts a tauri-driver per session and waits for both, afterSession stops them', async () => {
  const dir = fs.mkdtempSync(path.join(tmp, 'drivers-'));
  const driver = path.join(dir, 'tauri-driver');
  // Notes its arguments and pid at once, and `listening` in the tick it starts to listen:
  // once the port answers, the note is there. It listens on the real ports of the config,
  // 127.0.0.1:4444 and :4446; the one on :4446 a second late, so a beforeSession that
  // waits for the first port only returns before that note.
  fs.writeFileSync(
    driver,
    `#!${process.execPath}
const fs = require('fs');
const net = require('net');
const args = process.argv.slice(2);
const port = args[args.indexOf('--port') + 1];
const note = (what, text) => fs.writeFileSync(${JSON.stringify(dir)} + '/' + port + '.' + what, text);
note('args', JSON.stringify(args));
note('pid', String(process.pid));
process.on('SIGTERM', () => { note('stopped', ''); process.exit(0); });
setTimeout(() => {
  note('listening', '');
  net.createServer((s) => s.destroy()).listen(Number(port), '127.0.0.1');
}, port === '4446' ? 1000 : 0);
`,
    { mode: 0o755 },
  );
  const note = (port, what) => path.join(dir, `${port}.${what}`);
  const { config } = await withEnv(BOTH, () => import('../../wdio.workspaces.conf.js'));

  try {
    await withEnv({ TAURI_DRIVER_BIN: driver }, () => config.beforeSession());
    for (const [port, nativePort] of [[4444, 4445], [4446, 4447]]) {
      assert.deepEqual(
        JSON.parse(fs.readFileSync(note(port, 'args'), 'utf8')),
        ['--port', String(port), '--native-port', String(nativePort)],
      );
      assert.ok(fs.existsSync(note(port, 'listening')), `beforeSession returned before :${port} listened`);
      assert.equal(fs.existsSync(note(port, 'stopped')), false, `driver on :${port} already stopped`);
    }

    config.afterSession();
    const stopped = await waitFor(
      () => fs.existsSync(note(4444, 'stopped')) && fs.existsSync(note(4446, 'stopped')),
      10000,
    );
    assert.ok(stopped, `afterSession left a driver running: ${fs.readdirSync(dir).join(' ')}`);
  } finally {
    // A driver the config left running would keep this test process alive: a hang
    // instead of a red test. afterSession first, or the config ends this process on
    // the exit of a driver it did not stop itself.
    config.afterSession();
    for (const port of [4444, 4446]) {
      if (fs.existsSync(note(port, 'pid')) && !fs.existsSync(note(port, 'stopped'))) {
        try { process.kill(Number(fs.readFileSync(note(port, 'pid'), 'utf8')), 'SIGKILL'); } catch { /* gone */ }
      }
    }
  }
});

test('a missing workspace stops wdio while it loads the multiremote config, before the build', () => {
  const conf = ['wdio.workspaces.conf.js'];
  const missing = wdioRun({ AH_E2E_WORKSPACE_A: 'standard', AH_E2E_WORKSPACE_B: '' }, conf);
  assert.equal(missing.status, 1, missing.log);
  assert.match(missing.log, /AH_E2E_WORKSPACE_B is not set/, missing.log);
  assert.equal(missing.built, false, `the build ran:\n${missing.log}`);

  // Both set: the run gets to the build.
  const good = wdioRun(BOTH, conf);
  assert.equal(good.built, true, `the build did not run:\n${good.log}`);
});

test('ESLint knows the session names in the multiremote specs, and only there', async () => {
  const { ESLint } = await import('eslint');
  const eslint = new ESLint({ cwd: e2eDir });
  const names = workspaceSessions(BOTH).map((s) => s.name);
  const code = names.map((name) => `await ${name}.$('main');\n`).join('');
  const undefinedIn = async (file) =>
    (await eslint.lintText(code, { filePath: path.join(e2eDir, file) }))[0].messages
      .filter((m) => m.ruleId === 'no-undef')
      .map((m) => m.message);
  assert.deepEqual(await undefinedIn('test/specs/two-installations.workspaces.js'), []);
  assert.deepEqual(
    await undefinedIn('test/specs/tunnel-start.live.js'),
    names.map((name) => `'${name}' is not defined.`),
  );
});
