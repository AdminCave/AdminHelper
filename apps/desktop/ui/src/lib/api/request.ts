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

// Backstop timeout, above the Rust reqwest client's own connect(10s)+read(45s) caps: the
// Rust side normally times out the network itself, but if the Rust command or the Tauri
// IPC stalls, the UI must still fail instead of leaving loadServers on loading=true or
// runPlaybook on running=true forever. The higher value lets the more informative Rust
// error win when it's the network (4.4).
const REQUEST_TIMEOUT_MS = 90_000;

export function apiRequest<T>(
  session: AuthSession,
  method: HttpMethod,
  path: string,
  body?: unknown,
): Promise<T> {
  const allowSelfSigned = get(sessionStore).settings?.allowSelfSignedCerts ?? false;
  const proxy = bridge.apiProxy<T>(
    session.serverUrl,
    session.token,
    method,
    path,
    body !== undefined ? JSON.stringify(body) : undefined,
    allowSelfSigned,
  );
  let timer: ReturnType<typeof setTimeout>;
  const timeout = new Promise<never>((_, reject) => {
    // English like the neighbouring raw Rust error details (HTTP <status>: …), which
    // reach the user through the same errMsg(err) path.
    timer = setTimeout(() => reject(new Error('Request timed out')), REQUEST_TIMEOUT_MS);
  });
  return Promise.race([proxy, timeout]).finally(() => clearTimeout(timer));
}
