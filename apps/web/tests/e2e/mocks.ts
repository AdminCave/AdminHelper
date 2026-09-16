// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

import type { Page, Route } from '@playwright/test';

interface JsonOk {
  status?: number;
  body: unknown;
}

function json({ status = 200, body }: JsonOk): Parameters<Route['fulfill']>[0] {
  return {
    status,
    contentType: 'application/json',
    body: JSON.stringify(body),
  };
}

// Baut Regex, der NUR Origin-gebundene /api/... Pfade matcht (nicht Vite-Source
// wie /src/lib/api/*). Grund: der Glob `**/api/**` ist nicht pfad-anchored und
// verschluckt auch Source-Module, wodurch JS mit JSON-MIME geliefert wird und
// main.ts nicht bootet.
export function api(path: string): RegExp {
  const escaped = path.replace(/[.+?^${}()|[\]\\]/g, '\\$&').replace(/\*/g, '.*');
  return new RegExp(`^https?://[^/]+/api/${escaped}(\\?.*)?$`);
}

const ADMIN_USER = {
  id: 1,
  username: 'admin',
  is_admin: true,
  created_at: '2025-01-01T00:00:00Z',
  server_ids: [],
};

// GET /api/auth/me answers UserMe — three fields, not the full user row. The
// mock used to hand back ADMIN_USER here, so the suite could not have caught a
// UI that reads created_at/server_ids from a place that never sends them.
/** A UserMe body — three fields, the shape GET /api/auth/me declares. Exported so
 * a spec that overrides the route describes it once, here, and not a second time
 * beyond the reach of mocks.contract.test.ts. */
export const userMe = (id: number, username: string, isAdmin: boolean) => ({
  id,
  username,
  is_admin: isAdmin,
});

const ADMIN_ME = userMe(ADMIN_USER.id, ADMIN_USER.username, ADMIN_USER.is_admin);

const TOKENS = {
  access_token: 'test-access-token',
  refresh_token: 'test-refresh-token',
  token_type: 'bearer',
};

const AUDIT_ROWS: Record<string, unknown>[] = [
  {
    id: 2,
    timestamp: '2026-01-02T00:00:00Z',
    actorType: 'user',
    actorLabel: 'admin',
    action: 'server.created',
    objectType: 'server',
    objectLabel: 'srv-a',
  },
  {
    id: 1,
    timestamp: '2026-01-01T00:00:00Z',
    actorType: 'user',
    actorLabel: 'admin',
    action: 'user.created',
    objectType: 'user',
    objectLabel: 'bob',
  },
];

// The response shapes, as functions, so mockApi and MOCK_FIXTURES below cannot
// drift apart: the fixture table is these same builders called with example
// input, not a hand-kept second copy of the bodies.
const makeUser = (body: Record<string, unknown>, id: number): Record<string, unknown> => ({
  id,
  username: body.username,
  is_admin: body.is_admin ?? false,
  created_at: '2026-01-01T00:00:00Z',
  server_ids: body.server_ids ?? [],
});

const makeApiKey = (body: Record<string, unknown>, id: number): Record<string, unknown> => ({
  id,
  name: body.name,
  permission: body.permission,
  created_at: '2026-01-01T00:00:00Z',
});

// The create response carries the secret exactly once (ApiKeyCreateResult.key).
const makeApiKeyCreated = (body: Record<string, unknown>, id: number): Record<string, unknown> => ({
  id,
  name: body.name,
  permission: body.permission,
  key: `ah_e2e_${id}`,
});

// HookResponse — what the list and the toggle answer with. No `script`: that
// field lives on HookDetailResponse, which the UI fetches per hook when editing.
const makeHook = (body: Record<string, unknown>, id: string): Record<string, unknown> => ({
  id,
  name: body.name,
  hook_type: body.hook_type,
  enabled: true,
});

// HookCreatedResponse — the script plus a one-time token (revealed once).
const makeHookCreated = (body: Record<string, unknown>, id: string): Record<string, unknown> => ({
  ...makeHook(body, id),
  script: body.script,
  token: body.hook_type === 'webhook' ? `whk_${id}` : null,
});

// GET never returns the stored secret (`_token`).
const frpPub = (c: Record<string, unknown>): Record<string, unknown> => ({
  id: c.id,
  name: c.name,
  serverAddr: c.serverAddr,
  bindPort: c.bindPort,
});

const FRP_EXAMPLE = {
  id: 'frp-1',
  name: 'edge',
  serverAddr: 'frp.example.com',
  bindPort: 7000,
  _token: 'secret',
};

export interface MockFixture {
  method: 'GET' | 'POST' | 'PUT' | 'DELETE';
  /** Path below /api, in OpenAPI template form where it carries an id. */
  path: string;
  status: number;
  body: unknown;
}

/**
 * Every mockApi response body with checkable content, as data.
 *
 * The E2E mocks are a second description of the server API, and nothing checked
 * them against the first — a renamed response field kept the Playwright suite
 * green while the real app broke. src/lib/api/mocks.contract.test.ts pins this
 * table to apps/server/tests/openapi.snapshot.json. 204 responses are absent on
 * purpose: they have no body to compare.
 */
export const MOCK_FIXTURES: MockFixture[] = [
  { method: 'POST', path: 'auth/login', status: 200, body: TOKENS },
  { method: 'POST', path: 'auth/refresh', status: 200, body: TOKENS },
  { method: 'GET', path: 'auth/me', status: 200, body: ADMIN_ME },
  { method: 'GET', path: 'users', status: 200, body: [ADMIN_USER] },
  {
    method: 'POST',
    path: 'users',
    status: 201,
    body: makeUser({ username: 'bob', is_admin: false, server_ids: [] }, 101),
  },
  {
    method: 'GET',
    path: 'api-keys',
    status: 200,
    body: [makeApiKey({ name: 'ci', permission: 'read' }, 201)],
  },
  {
    method: 'POST',
    path: 'api-keys',
    status: 201,
    body: makeApiKeyCreated({ name: 'ci', permission: 'read' }, 201),
  },
  {
    method: 'GET',
    path: 'hooks',
    status: 200,
    body: [makeHook({ name: 'h', hook_type: 'webhook', script: 'print(1)' }, 'hook-1')],
  },
  {
    method: 'POST',
    path: 'hooks',
    status: 201,
    body: makeHookCreated({ name: 'h', hook_type: 'webhook', script: 'print(1)' }, 'hook-1'),
  },
  {
    method: 'POST',
    path: 'hooks/{hook_id}/toggle',
    status: 200,
    body: makeHook({ name: 'h', hook_type: 'webhook', script: 'print(1)' }, 'hook-1'),
  },
  { method: 'GET', path: 'frp/server-config', status: 200, body: [frpPub(FRP_EXAMPLE)] },
  { method: 'POST', path: 'frp/server-config', status: 201, body: frpPub(FRP_EXAMPLE) },
  {
    method: 'PUT',
    path: 'frp/server-config/{config_id}',
    status: 200,
    body: frpPub(FRP_EXAMPLE),
  },
  { method: 'GET', path: 'audit', status: 200, body: AUDIT_ROWS },
  { method: 'GET', path: 'frp/status', status: 200, body: { proxies: [], total: 0 } },
];

export async function mockApi(page: Page): Promise<void> {
  // Stateful In-Memory-"DB" pro Test: POST/DELETE mutieren den Stand, GET
  // liefert ihn aus — noetig fuer CRUD-Roundtrips (anlegen -> Liste -> loeschen).
  const db = {
    users: [{ ...ADMIN_USER }] as Record<string, unknown>[],
    apikeys: [] as Record<string, unknown>[],
    hooks: [] as Record<string, unknown>[],
    // FRP server-config is a singleton (0 or 1). `_token` is the stored secret,
    // never returned by GET — used to prove an edit with an empty token keeps it.
    frp: [] as Record<string, unknown>[],
    audit: AUDIT_ROWS.map((row) => ({ ...row })),
  };
  let seq = 1;

  // Playwright prueft Routes in LIFO-Reihenfolge (zuletzt registriert zuerst),
  // deshalb wird der generische Fallback ZUERST angelegt und von den spezifischen
  // Handlern unten ueberschrieben.
  // An unmocked API call must break the test loudly, not silently return [] — else a
  // forgotten mock (or a new endpoint) renders an empty list and the test passes blind (6.93).
  await page.route(/^https?:\/\/[^/]+\/api\//, async (route) => {
    return route.fulfill({
      status: 500,
      contentType: 'application/json',
      body: JSON.stringify({
        detail: `unmocked: ${route.request().method()} ${route.request().url()}`,
      }),
    });
  });

  await page.route(api('auth/login'), async (route) => route.fulfill(json({ body: TOKENS })));
  await page.route(api('auth/refresh'), async (route) => route.fulfill(json({ body: TOKENS })));
  await page.route(api('auth/me'), async (route) => route.fulfill(json({ body: ADMIN_ME })));
  await page.route(api('auth/logout'), async (route) => route.fulfill({ status: 204, body: '' }));

  // The user modal fetches the servers list; empty is fine for the current suites.
  // Any other unmocked /api call now 500s loudly instead of silently returning [] (6.93).
  await page.route(api('servers'), async (route) => route.fulfill(json({ body: [] })));

  await page.route(api('users'), async (route) => {
    if (route.request().method() === 'POST') {
      const body = route.request().postDataJSON() as Record<string, unknown>;
      const created = makeUser(body, 100 + seq++);
      db.users.push(created);
      return route.fulfill(json({ status: 201, body: created }));
    }
    return route.fulfill(json({ body: db.users }));
  });
  await page.route(api('users/*'), async (route) => {
    if (route.request().method() === 'DELETE') {
      const id = Number(new URL(route.request().url()).pathname.split('/').pop());
      db.users = db.users.filter((u) => u.id !== id);
      return route.fulfill({ status: 204, body: '' });
    }
    return route.fallback();
  });
  await page.route(api('api-keys'), async (route) => {
    if (route.request().method() === 'POST') {
      const body = route.request().postDataJSON() as Record<string, unknown>;
      const id = 200 + seq++;
      db.apikeys.push(makeApiKey(body, id));
      return route.fulfill(json({ status: 201, body: makeApiKeyCreated(body, id) }));
    }
    return route.fulfill(json({ body: db.apikeys }));
  });
  await page.route(api('api-keys/*'), async (route) => {
    if (route.request().method() === 'DELETE') {
      const id = Number(new URL(route.request().url()).pathname.split('/').pop());
      db.apikeys = db.apikeys.filter((k) => k.id !== id);
      return route.fulfill({ status: 204, body: '' });
    }
    return route.fallback();
  });
  await page.route(api('hooks'), async (route) => {
    if (route.request().method() === 'POST') {
      const body = route.request().postDataJSON() as Record<string, unknown>;
      const id = `hook-${seq++}`;
      db.hooks.push(makeHook(body, id));
      return route.fulfill(json({ status: 201, body: makeHookCreated(body, id) }));
    }
    return route.fulfill(json({ body: db.hooks }));
  });
  await page.route(api('hooks/*'), async (route) => {
    const method = route.request().method();
    const parts = new URL(route.request().url()).pathname.split('/');
    if (method === 'DELETE') {
      db.hooks = db.hooks.filter((h) => h.id !== parts.pop());
      return route.fulfill({ status: 204, body: '' });
    }
    if (method === 'POST' && parts.pop() === 'toggle') {
      const hook = db.hooks.find((h) => h.id === parts.pop());
      if (hook) hook.enabled = !hook.enabled;
      return route.fulfill(json({ body: hook ?? {} }));
    }
    return route.fallback();
  });

  // FRP-Server-Config: a singleton (POST creates, PUT edits). GET never returns
  // the secret; a PUT that omits auth_token must keep the stored one.
  await page.route(api('frp/server-config'), async (route) => {
    if (route.request().method() === 'POST') {
      const body = route.request().postDataJSON() as Record<string, unknown>;
      const id = `frp-${seq++}`;
      db.frp = [
        {
          id,
          name: body.name,
          serverAddr: body.server_addr,
          bindPort: body.bind_port,
          _token: (body.auth_token as string) || `auto_${id}`,
        },
      ];
      return route.fulfill(json({ status: 201, body: frpPub(db.frp[0]) }));
    }
    return route.fulfill(json({ body: db.frp.map(frpPub) }));
  });
  await page.route(api('frp/server-config/*'), async (route) => {
    if (route.request().method() === 'PUT') {
      const body = route.request().postDataJSON() as Record<string, unknown>;
      const cfg = db.frp[0];
      if (cfg) {
        if (body.name !== undefined) cfg.name = body.name;
        if (body.server_addr !== undefined) cfg.serverAddr = body.server_addr;
        if (body.bind_port !== undefined) cfg.bindPort = body.bind_port;
        if (body.auth_token !== undefined && body.auth_token !== null) cfg._token = body.auth_token;
      }
      return route.fulfill(json({ body: cfg ? frpPub(cfg) : {} }));
    }
    return route.fallback();
  });

  // Audit trail (read-only); supports the `action` substring filter.
  await page.route(api('audit'), async (route) => {
    const action = new URL(route.request().url()).searchParams.get('action');
    const rows = action ? db.audit.filter((e) => String(e.action).includes(action)) : db.audit;
    return route.fulfill(json({ body: rows }));
  });
  await page.route(api('frp/status*'), async (route) =>
    route.fulfill(json({ body: { proxies: [], total: 0 } })),
  );
}

// Note: there is no seedAuth() helper anymore. The access token lives only in
// memory now (no localStorage), so a session is established on load via the
// mocked POST /api/auth/refresh (which mockApi answers with valid tokens by
// default). Tests that need to be logged out override that route to 401.
