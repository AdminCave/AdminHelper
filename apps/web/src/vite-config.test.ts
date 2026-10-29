// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// @vitest-environment node
/// <reference types="node" />

// Dev-server proxy (R-0669): every prefix Vite forwards has to reach a route of the server,
// and every route of the server has to be reachable through a prefix. The server's routes
// are its OpenAPI snapshot (apps/server/tests/openapi.snapshot.json); a prefix with no
// route behind it (the old /auth and /health) is exactly the drift this pins.

import { beforeAll, describe, it, expect } from 'vitest';
import { loadConfigFromFile, type ProxyOptions } from 'vite';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

// src -> apps/web
const WEB_DIR = join(dirname(fileURLToPath(import.meta.url)), '..');
const CONFIG_FILE = join(WEB_DIR, 'vite.config.ts');
const SNAPSHOT_FILE = join(WEB_DIR, '..', 'server', 'tests', 'openapi.snapshot.json');
// Where DEVELOPMENT.md starts the server: `uvicorn … --host 127.0.0.1 --port 8080`.
const DEV_SERVER = 'http://127.0.0.1:8080';

const under = (path: string, prefix: string): boolean =>
  path === prefix || path.startsWith(`${prefix}/`);

describe('vite.config.ts server.proxy', () => {
  let proxy: Record<string, string | ProxyOptions>;
  let paths: string[];

  beforeAll(async () => {
    const loaded = await loadConfigFromFile({ command: 'serve', mode: 'development' }, CONFIG_FILE);
    proxy = loaded?.config.server?.proxy ?? {};
    const snapshot = JSON.parse(readFileSync(SNAPSHOT_FILE, 'utf8')) as {
      paths?: Record<string, unknown>;
    };
    paths = Object.keys(snapshot.paths ?? {});
  });

  it('reads a real snapshot', () => {
    // A missing or misread snapshot must not make the parity checks below pass vacuously.
    expect(paths.length).toBeGreaterThanOrEqual(40);
  });

  it('forwards only prefixes that some server route lives under', () => {
    const keys = Object.keys(proxy);
    expect(keys.length).toBeGreaterThan(0);
    for (const key of keys) {
      expect(
        paths.some((p) => under(p, key)),
        `${key} matches no path`,
      ).toBe(true);
    }
  });

  it('forwards every server route', () => {
    const keys = Object.keys(proxy);
    for (const path of paths) {
      expect(
        keys.some((k) => under(path, k)),
        `${path} is under no prefix`,
      ).toBe(true);
    }
  });

  it('forwards to the locally started server', () => {
    for (const [key, value] of Object.entries(proxy)) {
      expect(typeof value === 'string' ? value : value.target, key).toBe(DEV_SERVER);
    }
  });
});
