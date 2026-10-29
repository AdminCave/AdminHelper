// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Read-only server summary. The web no longer manages servers (server CRUD moved to
// the desktop client), but user management lives in the web and still needs id, name
// and host name to assign servers to a user (controls what a non-admin sees in the
// desktop). This is the only server endpoint the web calls — there is
// deliberately no create/update/remove here.

import { http } from './client';
import type { ServerSummary } from './types';

export function listSummaries(): Promise<ServerSummary[]> {
  return http.get<ServerSummary[]>('/api/servers/summary');
}
