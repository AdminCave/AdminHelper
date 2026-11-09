// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Ansible model: pure transformations without side effects.

import type { Server } from '$lib/api/types';
import type {
  AnsibleTarget,
  Connection,
  ResolvedConnection,
  TunnelMapping,
} from '$lib/bridge/types';

/**
 * The targets of a run: each server under its hostname with its tags as groups, and the
 * connection Ansible goes over (resolved, R-1202) where `reached` has one for it; a server
 * without one is reached at its hostname.
 */
export function buildAnsibleTargets(
  servers: Server[],
  reached: ReadonlyMap<string, Connection> = new Map(),
): AnsibleTarget[] {
  return servers.map((s) => {
    const connection = reached.get(s.id);
    return {
      hostname: s.hostname,
      groups: s.tags ?? [],
      ...(connection ? { connection } : {}),
    };
  });
}

/** The SSH connections of `server`, by name: the first is the default for Ansible. */
export function sshConnectionsOf(server: Server, connections: Connection[]): Connection[] {
  return connections
    .filter((c) => c.kind === 'ssh' && c.serverId === server.id)
    .sort((a, b) => a.name.localeCompare(b.name));
}

/**
 * The SSH connection Ansible takes for `server`: the one chosen in `choice` while it still is one
 * of the server's, else the first by name; `null` when the server has none.
 */
export function ansibleConnectionOf(
  server: Server,
  connections: Connection[],
  choice: Readonly<Record<string, string>>,
): Connection | null {
  const own = sshConnectionsOf(server, connections);
  return own.find((c) => c.id === choice[server.id]) ?? own[0] ?? null;
}

/**
 * Whether `connection` needs a tunnel visitor that does not run: an STCP mapping that left the
 * target as it was, or a target at `127.0.0.1`/`localhost` and the visitor port of an STCP
 * tunnel without a running visitor (the form of the server's automatic connections). Ansible
 * would reach nothing there, or something else (R-1202).
 */
export function visitorMissing(
  connection: Connection,
  resolved: ResolvedConnection,
  mappings: TunnelMapping[],
): boolean {
  const unchanged =
    resolved.connection.host === connection.host && resolved.connection.port === connection.port;
  if (resolved.viaTunnel) return resolved.tunnelType === 'stcp' && unchanged;
  const host = (connection.host ?? '').trim().toLowerCase();
  if (host !== '127.0.0.1' && host !== 'localhost') return false;
  return mappings.some(
    (m) => m.enabled && m.tunnelType === 'stcp' && m.visitorPort === connection.port,
  );
}

export function groupServersByTag(servers: Server[]): Record<string, Server[]> {
  const groups: Record<string, Server[]> = {};
  for (const server of servers) {
    for (const tag of server.tags ?? []) {
      if (!groups[tag]) groups[tag] = [];
      groups[tag].push(server);
    }
  }
  return groups;
}
