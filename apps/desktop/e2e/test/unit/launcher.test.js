// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// The real wdio launcher stops on a failed build before any worker starts (R-0260).
// onprepare.test.js pins our side (a SevereServiceError from the copy @wdio/cli loads);
// this one pins wdio's: a future @wdio/cli that logged the error and ran on would turn
// it red. Exit 1 alone proves nothing: without the fix the run also ends with 1, only
// after the worker started and the driver failed. A fake `cargo` stands in for the
// build and a fake tauri-driver leaves a marker when started: no display, no Rust, no
// network.

import { test, after } from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const e2eDir = fileURLToPath(new URL('../..', import.meta.url));
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'ah-launcher-'));

after(() => {
  fs.rmSync(tmp, { recursive: true, force: true });
});

test('a failed build stops wdio run before any worker starts', () => {
  const bin = path.join(tmp, 'bin');
  const marker = path.join(tmp, 'driver-started');
  const driver = path.join(tmp, 'tauri-driver');
  fs.mkdirSync(bin);
  fs.writeFileSync(path.join(bin, 'cargo'), '#!/bin/sh\nexit 1\n', { mode: 0o755 });
  fs.writeFileSync(driver, `#!/bin/sh\ntouch '${marker}'\nexit 1\n`, { mode: 0o755 });

  // The bin itself, not npx: nothing gets fetched.
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
        AH_OUT_DIR: path.join(tmp, 'out'),
        TAURI_DRIVER_BIN: driver,
      },
    },
  );
  const out = `${r.stdout}${r.stderr}`;

  assert.equal(r.status, 1, `exit ${r.status} (${r.error ?? r.signal ?? ''}):\n${out}`);
  assert.match(out, /HookError \[SevereServiceError\]: tauri build failed \(1\)/, out);
  assert.doesNotMatch(out, /\[0-0\]/, `a worker started:\n${out}`);
  assert.equal(fs.existsSync(marker), false, `the tauri-driver was started:\n${out}`);
});
