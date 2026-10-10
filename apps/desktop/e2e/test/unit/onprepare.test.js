// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// A failed build in onPrepare must stop the wdio run (R-0259). wdio only aborts on a
// SevereServiceError from webdriverio (runLauncherHook in @wdio/cli); any other error is
// logged and the specs run against whatever binary an earlier build left behind.
// A fake `cargo` first in PATH stands in for the build: no display, no Rust.

import { test, before, after } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import { SevereServiceError } from 'webdriverio';

const e2eDir = fileURLToPath(new URL('../..', import.meta.url));
let tmp;
let config;

function fakeCargo(rc) {
  fs.writeFileSync(path.join(tmp, 'bin', 'cargo'), `#!/bin/sh\nexit ${rc}\n`, { mode: 0o755 });
}

before(async () => {
  tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'ah-onprepare-'));
  fs.mkdirSync(path.join(tmp, 'bin'));
  process.env.PATH = `${path.join(tmp, 'bin')}${path.delimiter}${process.env.PATH}`;
  // wdio.conf.js reads AH_OUT_DIR when it is imported, and onPrepare creates screenshots/ there.
  process.env.AH_OUT_DIR = path.join(tmp, 'out');
  ({ config } = await import('../../wdio.conf.js'));
});

after(() => {
  fs.rmSync(tmp, { recursive: true, force: true });
});

test('a failed build stops the run: onPrepare throws a SevereServiceError', () => {
  fakeCargo(1);
  assert.throws(
    () => config.onPrepare(),
    (err) => {
      assert.ok(err instanceof SevereServiceError, `not a SevereServiceError: ${err}`);
      assert.match(err.message, /tauri build failed \(1\)/);
      return true;
    },
  );
});

test('a successful build lets the run go on', () => {
  fakeCargo(0);
  assert.doesNotThrow(() => config.onPrepare());
});

test('@wdio/cli checks against the webdriverio copy the config imports', () => {
  // A second copy would be another class: instanceof in runLauncherHook would fail and
  // the run would go on as before. Node takes the first node_modules/webdriverio on the
  // way up from the importing file.
  const firstCopy = (from) =>
    createRequire(from)
      .resolve.paths('webdriverio')
      .map((dir) => path.join(dir, 'webdriverio'))
      .find((dir) => fs.existsSync(dir));
  const forCli = firstCopy(fileURLToPath(import.meta.resolve('@wdio/cli')));
  const forConfig = firstCopy(path.join(e2eDir, 'wdio.conf.js'));
  assert.ok(forConfig, 'webdriverio is not installed');
  assert.equal(forCli, forConfig);
});
