// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Shared transport for the server-API modules (servers, connections, frp,
// monitoring, ansible, provisioning). The desktop client cannot use fetch()
// against the server the way the web frontend does — it routes every call
// through the api_proxy Tauri command, which works around the WebView's TLS
// restrictions for self-signed certs and sends the request for the session Rust
// holds: its server, its token, renewed there on a 401.
//
// Behaviour mirrors apps/web/src/lib/api/client.ts as far as the proxy allows:
// non-2xx responses reject with an IpcError carrying the status, the server's code
// (or ERR_HTTP) and the text of its `detail` like errorDetail in the web client
// (AppError::http on the Rust side), and 204/empty bodies resolve to null. Note the
// proxy parses every response as JSON, so text/binary endpoints (TOML/ZIP
// generation) intentionally have no wrapper here.

import * as bridge from '$lib/bridge';
import type { AuthSession, HttpMethod } from '$lib/bridge/types';

// Backstop timeout, above what the Rust side takes: a request is capped at connect(10s) +
// read(45s); a 401 adds the renewal (at most 30s, or the wait for one already under way)
// and one retry under the same caps. The 401 itself is a quick answer, so that chain still
// ends before the backstop, and the more informative Rust error wins when it's the network
// (4.4). Only if the Rust command or the Tauri IPC stalls does this fire, so loadServers
// does not stay on loading=true or runPlaybook on running=true forever.
const REQUEST_TIMEOUT_MS = 90_000;

// `_session`: the callers' proof of a sign-in (they guard on it); the request goes out for
// the session Rust holds.
export function apiRequest<T>(
  _session: AuthSession,
  method: HttpMethod,
  path: string,
  body?: unknown,
): Promise<T> {
  const proxy = bridge.apiProxy<T>(
    method,
    path,
    body !== undefined ? JSON.stringify(body) : undefined,
  );
  let timer: ReturnType<typeof setTimeout>;
  const timeout = new Promise<never>((_, reject) => {
    // English like the Rust side's own messages, which reach the user through the same
    // errMsg(err) path.
    timer = setTimeout(() => reject(new Error('Request timed out')), REQUEST_TIMEOUT_MS);
  });
  return Promise.race([proxy, timeout]).finally(() => clearTimeout(timer));
}
