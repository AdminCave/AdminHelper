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
    .filter((connection) => filter === "all" || connection.kind === filter)
    .filter((connection) => {
      const tagText = (connection.tags || []).join(" ");
      const haystack = `${connection.name} ${connection.host} ${connection.url} ${connection.domain || ""} ${tagText}`.toLowerCase();
      return haystack.includes(query);
    })
    .sort((a, b) => String(a.name || "").localeCompare(String(b.name || "")));
}
