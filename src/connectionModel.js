export const DEFAULT_PORTS = {
  ssh: 22,
  rdp: 3389
};

export function normalizeConnection(connection) {
  const normalized = { ...connection };
  normalized.name = (normalized.name || "").trim();
  normalized.kind = normalized.kind || "ssh";
  normalized.host = (normalized.host || "").trim();
  normalized.username = (normalized.username || "").trim();
  normalized.domain = (normalized.domain || "").trim();
  normalized.keyPath = (normalized.keyPath || "").trim();
  normalized.url = (normalized.url || "").trim();
  normalized.notes = (normalized.notes || "").trim();
  normalized.trustCert = Boolean(normalized.trustCert);
  normalized.tags = Array.isArray(normalized.tags) ? normalized.tags : [];
  normalized.tags = normalized.tags
    .map((tag) => String(tag).trim())
    .filter((tag) => tag.length > 0);
  if (!normalized.port || Number.isNaN(Number(normalized.port))) {
    normalized.port = null;
  } else {
    normalized.port = Number(normalized.port);
  }
  return normalized;
}

export function parseTags(raw) {
  return raw
    .split(",")
    .map((tag) => tag.trim())
    .filter((tag) => tag.length > 0);
}

export function validateConnection(connection, t) {
  if (!connection.name) {
    return { ok: false, message: t("validation.name") };
  }
  if (connection.kind === "web") {
    if (!connection.url) {
      return { ok: false, message: t("validation.url") };
    }
    return { ok: true };
  }
  if (!connection.host) {
    return { ok: false, message: t("validation.host") };
  }
  return { ok: true };
}

export function toCardMeta(connection) {
  if (connection.kind === "web") {
    return connection.url || "-";
  }
  const host = connection.host || "-";
  const port = connection.port || DEFAULT_PORTS[connection.kind] || "-";
  const user = connection.username ? `${connection.username}@` : "";
  return `${user}${host}:${port}`;
}

export function filterConnections(connections, filter, search) {
  const query = (search || "").toLowerCase();
  return connections
    .filter(
      (connection) =>
        filter === "single" || filter === "all" || connection.kind === filter
    )
    .filter((connection) => {
      const tagText = (connection.tags || []).join(" ");
      const haystack = `${connection.name} ${connection.host} ${connection.url} ${connection.domain || ""} ${tagText}`.toLowerCase();
      return haystack.includes(query);
    })
    .sort((a, b) => String(a.name || "").localeCompare(String(b.name || "")));
}

function parseUrlHost(rawUrl) {
  const trimmed = String(rawUrl || "").trim();
  if (!trimmed) {
    return "";
  }
  try {
    return new URL(trimmed).hostname || "";
  } catch (_err) {
    try {
      return new URL(`https://${trimmed}`).hostname || "";
    } catch (_err2) {
      return "";
    }
  }
}

function connectionGroupingHost(connection) {
  const host = String(connection.host || "").trim();
  if (host) {
    return host;
  }
  if (connection.kind === "web") {
    return parseUrlHost(connection.url);
  }
  return "";
}

function connectionHaystack(connection) {
  const tagText = (connection.tags || []).join(" ");
  return `${connection.name} ${connection.host} ${connection.url} ${connection.domain || ""} ${tagText}`.toLowerCase();
}

function pickPreferredConnection(connections) {
  return [...connections].sort((a, b) => {
    const aTime = a.lastUsed ? Date.parse(a.lastUsed) || 0 : 0;
    const bTime = b.lastUsed ? Date.parse(b.lastUsed) || 0 : 0;
    if (aTime !== bTime) {
      return bTime - aTime;
    }
    return String(a.name || "").localeCompare(String(b.name || ""));
  })[0];
}

export function groupConnectionsByHost(connections, search) {
  const groups = new Map();
  const query = (search || "").toLowerCase();

  connections.forEach((connection) => {
    const host = connectionGroupingHost(connection);
    const normalizedHost = host.toLowerCase();
    const key = normalizedHost || `__${connection.id}`;
    const displayHost = host || connection.name || connection.id;

    if (!groups.has(key)) {
      groups.set(key, {
        key,
        host: displayHost,
        connections: [],
        kindBuckets: {
          ssh: [],
          rdp: [],
          web: []
        }
      });
    }
    const group = groups.get(key);
    group.connections.push(connection);
    if (group.kindBuckets[connection.kind]) {
      group.kindBuckets[connection.kind].push(connection);
    }
  });

  return Array.from(groups.values())
    .map((group) => {
      const byKind = {};
      ["ssh", "rdp", "web"].forEach((kind) => {
        if (group.kindBuckets[kind].length > 0) {
          byKind[kind] = pickPreferredConnection(group.kindBuckets[kind]);
        }
      });
      const preferred = pickPreferredConnection(group.connections);
      const displayName = String(preferred?.name || "").trim();
      const haystack = `${group.host} ${group.connections.map(connectionHaystack).join(" ")}`.toLowerCase();
      return {
        key: group.key,
        host: group.host,
        displayName,
        connections: group.connections,
        byKind,
        haystack
      };
    })
    .filter((group) => !query || group.haystack.includes(query))
    .sort((a, b) => String(a.host || "").localeCompare(String(b.host || "")));
}
