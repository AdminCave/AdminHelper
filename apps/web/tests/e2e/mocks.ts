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

const TOKENS = {
  access_token: 'test-access-token',
  refresh_token: 'test-refresh-token',
  token_type: 'bearer',
};

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
    audit: [
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
    ] as Record<string, unknown>[],
  };
  let seq = 1;

  // Playwright prueft Routes in LIFO-Reihenfolge (zuletzt registriert zuerst),
  // deshalb wird der generische Fallback ZUERST angelegt und von den spezifischen
  // Handlern unten ueberschrieben.
  await page.route(/^https?:\/\/[^/]+\/api\//, async (route) => {
    const method = route.request().method();
    if (method === 'DELETE') {
      return route.fulfill({ status: 204, body: '' });
    }
    return route.fulfill(json({ body: [] }));
  });

  await page.route(api('auth/login'), async (route) => route.fulfill(json({ body: TOKENS })));
  await page.route(api('auth/refresh'), async (route) => route.fulfill(json({ body: TOKENS })));
  await page.route(api('auth/me'), async (route) => route.fulfill(json({ body: ADMIN_USER })));
  await page.route(api('auth/logout'), async (route) => route.fulfill({ status: 204, body: '' }));

  await page.route(api('users'), async (route) => {
    if (route.request().method() === 'POST') {
      const body = route.request().postDataJSON() as Record<string, unknown>;
      const created = {
        id: 100 + seq++,
        username: body.username,
        is_admin: body.is_admin ?? false,
        created_at: '2026-01-01T00:00:00Z',
        server_ids: body.server_ids ?? [],
      };
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
      db.apikeys.push({
        id,
        name: body.name,
        permission: body.permission,
        created_at: '2026-01-01T00:00:00Z',
      });
      // The create response carries the secret exactly once (ApiKeyCreateResult.key).
      return route.fulfill(
        json({
          status: 201,
          body: { id, name: body.name, permission: body.permission, key: `ah_e2e_${id}` },
        }),
      );
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
      const created = {
        id,
        name: body.name,
        hook_type: body.hook_type,
        enabled: true,
        script: body.script,
      };
      db.hooks.push(created);
      // A webhook hook's create response carries a one-time token (revealed once).
      const token = body.hook_type === 'webhook' ? `whk_${id}` : null;
      return route.fulfill(json({ status: 201, body: { ...created, token } }));
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
  const frpPub = (c: Record<string, unknown>) => ({
    id: c.id,
    name: c.name,
    serverAddr: c.serverAddr,
    bindPort: c.bindPort,
  });
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
