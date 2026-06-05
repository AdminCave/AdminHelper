// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

import { http } from './client';
import type { ProvisionToken, ProvisionTokenCreateResult } from './types';

export function listProvisionTokens(serverId: string): Promise<ProvisionToken[]> {
  return http.get<ProvisionToken[]>(`/api/servers/${serverId}/provision/tokens`);
}

export function createProvisionToken(serverId: string): Promise<ProvisionTokenCreateResult> {
  return http.post<ProvisionTokenCreateResult>(`/api/servers/${serverId}/provision/token`);
}
