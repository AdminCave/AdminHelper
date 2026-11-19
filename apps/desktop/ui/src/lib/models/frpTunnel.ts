// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Form model for FRP tunnels managed in the infrastructure hub. The server is
// fixed (the hub's selected server); the FRP server-config is picked (it stays an
// instance-admin concern, configured in the web admin). Pure, unit-testable logic.

import type { FrpProtocol, FrpTunnel, FrpTunnelInput, FrpTunnelType } from '$lib/api/types';
import { tNow } from '$lib/i18n';
import { DEFAULT_PORTS } from './connection';
import { parseTags, type ValidationResult } from './shared';
export { parseTags };

export const TUNNEL_TYPES: FrpTunnelType[] = ['stcp', 'https'];
export const TUNNEL_PROTOCOLS: FrpProtocol[] = ['ssh', 'rdp', 'web'];
export const PROTOCOL_DEFAULT_PORT: Record<FrpProtocol, number> = { ...DEFAULT_PORTS, web: 8006 };
export type WebScheme = 'http' | 'https';
export const WEB_SCHEMES: WebScheme[] = ['http', 'https'];
const HTTPS_PORTS = new Set([443, 8006, 8443, 9443]);

/** The scheme a web target on this port most likely speaks (R-1540). */
export function defaultWebScheme(port: number | null): WebScheme {
  return port !== null && HTTPS_PORTS.has(port) ? 'https' : 'http';
}

export interface TunnelForm {
  id: string | null;
  serverId: string;
  frpConfigId: string;
  /** The own text of the display name the server derives (R-1210); not the proxy name. */
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
  /** Picked by the user; null follows the target port (defaultWebScheme). */
  autoConnectionScheme: WebScheme | null;
  autoConnectionPath: string;
  /** Protocol and type when the dialog opened; null for a new tunnel. */
  initialShape: { protocol: FrpProtocol; tunnelType: FrpTunnelType } | null;
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
    autoConnectionScheme: null,
    autoConnectionPath: '',
    initialShape: null,
  };
}

export function tunnelToForm(t: FrpTunnel): TunnelForm {
  return {
    id: t.id,
    serverId: t.serverId,
    frpConfigId: t.frpConfigId,
    // A server from before R-1210 sends no label: its name is the stored one.
    name: t.label ?? t.name,
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
    autoConnectionScheme: null,
    autoConnectionPath: '',
    initialShape: { protocol: t.protocol, tunnelType: t.tunnelType },
  };
}

/** Builds the server payload. Type-irrelevant fields are nulled (an stcp tunnel
 * never carries customDomains; an https one never carries secret/visitor port) so
 * stale values from a type switch don't leak to the server. The own text goes as
 * `label`; `name` carries it as well, or "{server}-{protocol}" without one, which a
 * server from R-1210 on stores as no own text and an older one as the unique proxy
 * name it requires. */
/** Whether the server builds a web URL from this save: a new tunnel, or one whose protocol or
 * type changes (the server then takes the linked connection along). Otherwise it ignores
 * scheme and path, so the dialog neither asks for nor sends them. */
export function asksWebTarget(form: TunnelForm): boolean {
  if (form.protocol !== 'web' || !form.autoCreateConnection) return false;
  const was = form.initialShape;
  return was === null || was.protocol !== form.protocol || was.tunnelType !== form.tunnelType;
}

export function effectiveScheme(form: TunnelForm): WebScheme {
  return form.autoConnectionScheme ?? defaultWebScheme(form.localPort);
}

export function formToInput(form: TunnelForm, serverName = ''): FrpTunnelInput {
  const isStcp = form.tunnelType === 'stcp';
  const own = form.name.trim();
  const web = asksWebTarget(form)
    ? {
        auto_connection_scheme: effectiveScheme(form),
        auto_connection_path: form.autoConnectionPath.trim() || null,
      }
    : {};
  return {
    server_id: form.serverId,
    frp_config_id: form.frpConfigId,
    name: own || `${serverName}-${form.protocol}`,
    label: own,
    tunnel_type: form.tunnelType,
    protocol: form.protocol,
    local_ip: form.localIp.trim() || '127.0.0.1',
    local_port: form.localPort ?? 0,
    secret_key: isStcp ? form.secretKey.trim() || null : null,
    custom_domains: isStcp ? null : form.customDomains.trim() || null,
    visitor_port: isStcp ? (form.visitorPort ?? null) : null,
    auto_create_connection: form.autoCreateConnection,
    // A web connection has no user (R-1540).
    auto_connection_username:
      form.protocol === 'web' ? null : form.autoConnectionUsername.trim() || null,
    ...web,
    tags: [...new Set(form.tags.map((t) => t.trim()).filter((t) => t.length > 0))],
  };
}

// Starts with "/", at most 255 characters, no whitespace, control character or "#".
// eslint-disable-next-line no-control-regex
const WEB_PATH = /^\/[^\s\x00-\x1f\x7f-\x9f#]{0,254}$/;

export function validateTunnelForm(form: TunnelForm): ValidationResult {
  if (!form.frpConfigId) return { ok: false, message: tNow('infra.tun.validation.configRequired') };
  if (!form.localPort || form.localPort <= 0) {
    return { ok: false, message: tNow('infra.tun.validation.portRequired') };
  }
  // An empty field (null) lets the server assign a port; https never sends one (formToInput).
  const vp = form.visitorPort;
  if (
    form.tunnelType === 'stcp' &&
    vp !== null &&
    !(Number.isInteger(vp) && vp >= 1 && vp <= 65535)
  ) {
    return { ok: false, message: tNow('infra.tun.validation.visitorPortRange') };
  }
  // The server's rule (check_auto_path), so the user sees it before the 422.
  const path = form.autoConnectionPath.trim();
  if (asksWebTarget(form) && path && !WEB_PATH.test(path)) {
    return { ok: false, message: tNow('infra.tun.validation.path') };
  }
  return { ok: true };
}
