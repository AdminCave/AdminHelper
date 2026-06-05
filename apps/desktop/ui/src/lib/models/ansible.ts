// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Ansible model: pure transformations without side effects.

import type { Server } from '$lib/api/types';
import type { AnsibleTarget } from '$lib/bridge/types';

export function buildAnsibleTargets(servers: Server[]): AnsibleTarget[] {
  return servers.map((s) => ({
    hostname: s.hostname,
    groups: s.tags ?? [],
  }));
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
