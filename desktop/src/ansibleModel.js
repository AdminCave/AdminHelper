/**
 * Transformiert Server-Daten in AnsibleTarget-Format.
 * Nutzt nur hostname + tags (SSH-Auth via lokale ~/.ssh/config).
 */
export function buildAnsibleTargets(servers) {
  return servers.map((s) => ({
    hostname: s.hostname,
    groups: s.tags || [],
  }));
}

/**
 * Gruppiert Server nach Tags fuer die Tag-basierte Selektion.
 * Gibt ein Objekt zurueck: { tagName: [server, ...], ... }
 */
export function groupServersByTag(servers) {
  const groups = {};
  for (const server of servers) {
    for (const tag of server.tags || []) {
      if (!groups[tag]) groups[tag] = [];
      groups[tag].push(server);
    }
  }
  return groups;
}
