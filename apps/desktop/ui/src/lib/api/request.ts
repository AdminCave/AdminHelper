// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Shared transport for the server-API modules (servers, connections, frp,
// monitoring, ansible, provisioning). The desktop client cannot use fetch()
// against the server the way the web frontend does — it routes every call
// through the api_proxy Tauri command, which works around the WebView's TLS
// restrictions for self-signed certs and pins the JWT to the logged-in server.
//
// Behaviour mirrors apps/web/src/lib/api/client.ts as far as the proxy allows:
// non-2xx responses reject (with an Error whose message is "HTTP <status>: …",
// produced by the Rust side), and 204/empty bodies resolve to null. Note the
// proxy parses every response as JSON, so text/binary endpoints (TOML/ZIP
// generation) intentionally have no wrapper here.

import { get } from 'svelte/store';
import * as bridge from '$lib/bridge';
import type { AuthSession, HttpMethod } from '$lib/bridge/types';
import { sessionStore } from '$lib/stores/session';

export function apiRequest<T>(
  session: AuthSession,
  method: HttpMethod,
  path: string,
  body?: unknown,
): Promise<T> {
  const allowSelfSigned = get(sessionStore).settings?.allowSelfSignedCerts ?? false;
  return bridge.apiProxy<T>(
    session.serverUrl,
    session.token,
    method,
    path,
    body !== undefined ? JSON.stringify(body) : undefined,
    allowSelfSigned,
  );
}
