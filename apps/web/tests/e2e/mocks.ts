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
  await page.route(api('hooks'), async (route) => route.fulfill(json({ body: [] })));

  // FRP-Server-Config (Instanz-Verwaltung): leere Config -> "noConfig"-Zustand.
  await page.route(api('frp/server-config'), async (route) => route.fulfill(json({ body: [] })));
  await page.route(api('frp/status*'), async (route) =>
    route.fulfill(json({ body: { proxies: [], total: 0 } })),
  );
}

// Note: there is no seedAuth() helper anymore. The access token lives only in
// memory now (no localStorage), so a session is established on load via the
// mocked POST /api/auth/refresh (which mockApi answers with valid tokens by
// default). Tests that need to be logged out override that route to 401.
