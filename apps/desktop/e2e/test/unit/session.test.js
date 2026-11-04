// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Every spec starts with POST /session to tauri-driver. Under Node 26 the undici 6 that
// webdriver 9 brings returned Node's own Dispatcher1Wrapper as the global dispatcher, and
// webdriver handed it to undici 6's fetch: UND_ERR_INVALID_ARG before the first step of
// every GUI spec (R-1122). A local HTTP stub stands in for tauri-driver: no display.

import { test } from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import WebDriver from 'webdriver';

test('webdriver opens a session against a local driver', async () => {
  const requests = [];
  const server = http.createServer((req, res) => {
    req.resume();
    req.on('end', () => {
      requests.push(`${req.method} ${req.url}`);
      res.setHeader('content-type', 'application/json');
      res.end(JSON.stringify({ value: { sessionId: 's-1', capabilities: { browserName: 'stub' } } }));
    });
  });
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  try {
    const client = await WebDriver.newSession({
      hostname: '127.0.0.1',
      port: server.address().port,
      capabilities: {},
      logLevel: 'silent',
      connectionRetryCount: 0,
    });
    assert.equal(client.sessionId, 's-1');
    assert.deepEqual(requests, ['POST /session']);
  } finally {
    server.close();
  }
});
