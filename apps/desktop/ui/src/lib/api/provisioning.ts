// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Provisioning API: one-time tokens that bootstrap a server agent (it redeems
// the token to obtain its API keys, FRP bundle and enrollment token). Desktop-only
// — the web panel has no provisioning API; admin-only on the server side and tied
// to a specific server, so it lives next to server management in the desktop.

import { apiRequest } from '$lib/api/request';
import type { AuthSession } from '$lib/bridge/types';
import type { FrpProvisionToken, FrpProvisionTokenCreateResult } from '$lib/api/types';

export const provisioningApi = {
  listTokens(session: AuthSession, serverId: string): Promise<FrpProvisionToken[]> {
    return apiRequest<FrpProvisionToken[]>(
      session,
      'GET',
      `/api/servers/${encodeURIComponent(serverId)}/provision/tokens`,
    );
  },
  createToken(session: AuthSession, serverId: string): Promise<FrpProvisionTokenCreateResult> {
    return apiRequest<FrpProvisionTokenCreateResult>(
      session,
      'POST',
      `/api/servers/${encodeURIComponent(serverId)}/provision/token`,
    );
  },
};
