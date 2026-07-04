// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Form model for FRP tunnels managed in the infrastructure hub. The server is
// fixed (the hub's selected server); the FRP server-config is picked (it stays an
// instance-admin concern, configured in the web admin). Pure, unit-testable logic.

import type { FrpProtocol, FrpTunnel, FrpTunnelInput, FrpTunnelType } from '$lib/api/types';
import { tNow } from '$lib/i18n';
import { parseTags, type ValidationResult } from './shared';
export { parseTags };

export const TUNNEL_TYPES: FrpTunnelType[] = ['stcp', 'https'];
export const TUNNEL_PROTOCOLS: FrpProtocol[] = ['ssh', 'rdp', 'web'];
export const PROTOCOL_DEFAULT_PORT: Record<FrpProtocol, number> = { ssh: 22, rdp: 3389, web: 8006 };

export interface TunnelForm {
  id: string | null;
  serverId: string;
  frpConfigId: string;
  name: string;
  tunnelType: FrpTunnelType;
  protocol: FrpProtocol;
  localIp: string;
  localPort: number | null;
  secretKey: string;
  visitorPort: number | null;
  customDomains: string;
  tags: string[];
  autoCreateConnection: boolean;
  autoConnectionUsername: string;
}

export function emptyTunnelForm(serverId: string, frpConfigId = ''): TunnelForm {
  return {
    id: null,
    serverId,
    frpConfigId,
    name: '',
    tunnelType: 'stcp',
    protocol: 'ssh',
    localIp: '127.0.0.1',
    localPort: null,
    secretKey: '',
    visitorPort: null,
    customDomains: '',
    tags: [],
    autoCreateConnection: false,
    autoConnectionUsername: '',
  };
}

export function tunnelToForm(t: FrpTunnel): TunnelForm {
  return {
    id: t.id,
    serverId: t.serverId,
    frpConfigId: t.frpConfigId,
    name: t.name,
    tunnelType: t.tunnelType,
    protocol: t.protocol,
    localIp: t.localIp ?? '127.0.0.1',
    localPort: t.localPort ?? null,
    secretKey: t.secretKey ?? '',
    visitorPort: t.visitorPort ?? null,
    customDomains: t.customDomains ?? '',
    tags: [...(t.tags ?? [])],
    autoCreateConnection: !!t.connectionId,
    autoConnectionUsername: '',
  };
}

/** Builds the server payload. Type-irrelevant fields are nulled (an stcp tunnel
 * never carries customDomains; an https one never carries secret/visitor port) so
 * stale values from a type switch don't leak to the server. */
export function formToInput(form: TunnelForm): FrpTunnelInput {
  const isStcp = form.tunnelType === 'stcp';
  return {
    server_id: form.serverId,
    frp_config_id: form.frpConfigId,
    name: form.name.trim(),
    tunnel_type: form.tunnelType,
    protocol: form.protocol,
    local_ip: form.localIp.trim() || '127.0.0.1',
    local_port: form.localPort ?? 0,
    secret_key: isStcp ? form.secretKey.trim() || null : null,
    custom_domains: isStcp ? null : form.customDomains.trim() || null,
    visitor_port: isStcp ? (form.visitorPort ?? null) : null,
    auto_create_connection: form.autoCreateConnection,
    auto_connection_username: form.autoConnectionUsername.trim() || null,
    tags: [...new Set(form.tags.map((t) => t.trim()).filter((t) => t.length > 0))],
  };
}

export function validateTunnelForm(form: TunnelForm): ValidationResult {
  if (!form.frpConfigId) return { ok: false, message: tNow('infra.tun.validation.configRequired') };
  if (!form.name.trim()) return { ok: false, message: tNow('infra.tun.validation.nameRequired') };
  if (!form.localPort || form.localPort <= 0) {
    return { ok: false, message: tNow('infra.tun.validation.portRequired') };
  }
  return { ok: true };
}
