// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

import { http } from './client';
import type { FrpProvisionToken, FrpProvisionTokenCreateResult } from './types';

export function listProvisionTokens(serverId: string): Promise<FrpProvisionToken[]> {
  return http.get<FrpProvisionToken[]>(`/api/servers/${serverId}/provision/tokens`);
}

export function createProvisionToken(serverId: string): Promise<FrpProvisionTokenCreateResult> {
  return http.post<FrpProvisionTokenCreateResult>(`/api/servers/${serverId}/provision/token`);
}
