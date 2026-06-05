// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

import type { HookType } from '$lib/api/types';

export const HOOK_EVENTS = [
  'connection.created',
  'connection.updated',
  'connection.deleted',
  'connections.imported',
  'user.created',
  'user.deleted',
  'server.created',
  'server.updated',
  'server.deleted',
  'server.startup',
  'frp.config.created',
  'frp.config.updated',
  'frp.config.deleted',
  'frp.tunnel.created',
  'frp.tunnel.updated',
  'frp.tunnel.deleted',
] as const;

export const HOOK_INTERVAL_PRESETS = ['5m', '15m', '30m', '1h', '6h', '12h', '24h'] as const;

export const HOOK_TYPE_LABEL: Record<HookType, string> = {
  webhook: 'Webhook',
  event: 'Event',
  schedule: 'Schedule',
};
