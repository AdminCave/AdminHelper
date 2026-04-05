const STATUS_PRIORITY = { critical: 4, warning: 3, unknown: 2, pending: 1, ok: 0 };

export function worstStatus(checks) {
  let worst = "ok";
  for (const c of checks) {
    const s = c.state?.status || "pending";
    if ((STATUS_PRIORITY[s] || 0) > (STATUS_PRIORITY[worst] || 0)) {
      worst = s;
    }
  }
  return worst;
}

export function groupChecksByServer(checks, connections = []) {
  const map = new Map();
  for (const c of checks) {
    const key = c.serverId || "__none";
    if (!map.has(key)) {
      const match = c.serverId ? connections.find((conn) => conn.serverId === c.serverId) : null;
      const serverName = match ? (match.name || match.host || c.serverId) : c.serverId;
      map.set(key, { serverId: c.serverId, serverName, checks: [] });
    }
    map.get(key).checks.push(c);
  }
  const groups = Array.from(map.values());
  groups.sort((a, b) => {
    const nameA = a.serverName || a.serverId || "";
    const nameB = b.serverName || b.serverId || "";
    return nameA.localeCompare(nameB);
  });
  return groups;
}

export function filterChecks(checks, filters) {
  const query = (filters.search || "").toLowerCase();
  return checks.filter((c) => {
    if (filters.server && c.serverId !== filters.server) return false;
    if (filters.type && c.checkType !== filters.type) return false;
    if (filters.status) {
      const s = c.state?.status || "pending";
      if (s !== filters.status) return false;
    }
    if (query) {
      const hay = `${c.name} ${c.description || ""} ${c.checkType} ${c.state?.message || ""}`.toLowerCase();
      if (!hay.includes(query)) return false;
    }
    return true;
  });
}

export function statusClass(status) {
  const s = status || "pending";
  return `mon-${s}`;
}

export function formatCheckTime(isoStr) {
  if (!isoStr) return "-";
  const d = new Date(isoStr);
  if (isNaN(d.getTime())) return "-";
  return d.toLocaleString("de-DE", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit"
  });
}

export function formatCheckConfig(check) {
  const c = check.config || {};
  const type = check.checkType;
  const kv = [];

  if (type === "ping") {
    kv.push(["Ziel", c.target], ["Timeout", `${c.timeout || 5}s`]);
  } else if (type === "tcp") {
    kv.push(["Ziel", `${c.target}:${c.port}`], ["Timeout", `${c.timeout || 5}s`]);
  } else if (type === "http") {
    kv.push(["URL", c.url], ["Methode", c.method || "GET"], ["Expected", c.expected_status || 200]);
    if (c.verify_ssl === false) kv.push(["SSL", "deaktiviert"]);
    if (c.search_string) kv.push(["Suchtext", c.search_string]);
  } else if (type === "agent_ping") {
    kv.push(["Stale-Schwelle", `${c.stale_minutes || 5} min`]);
  } else if (type === "agent_resources") {
    kv.push(
      ["CPU", `Warn ${c.cpu_warn || 80}% / Crit ${c.cpu_crit || 95}%`],
      ["RAM", `Warn ${c.memory_warn || 80}% / Crit ${c.memory_crit || 95}%`],
      ["Disk", `Warn ${c.disk_warn || 85}% / Crit ${c.disk_crit || 95}%`],
    );
  } else if (type === "service_process") {
    kv.push(["Modus", c.mode || "auto"]);
    if (c.services?.length) kv.push(["Services", c.services.join(", ")]);
    if (c.ignore?.length) kv.push(["Ignoriert", c.ignore.join(", ")]);
  } else if (type === "proxmox_backup") {
    kv.push(["Max. Alter", `${c.max_backup_age_hours || 26}h`]);
    if (c.exclude_vmids?.length) kv.push(["Exclude VMIDs", c.exclude_vmids.join(", ")]);
  } else if (type === "zfs_health") {
    kv.push(
      ["Kapazität", `Warn ${c.capacity_warn || 80}% / Crit ${c.capacity_crit || 90}%`],
    );
  } else if (type === "docker_health") {
    if (c.ignore_containers?.length) kv.push(["Ignoriert", c.ignore_containers.join(", ")]);
    kv.push(["Restart-Check", c.check_restarts !== false ? "aktiv" : "aus"]);
  }

  return kv;
}

/** Bestimmt die Y-Achsen-Einheit je nach Check-Typ. */
export function checkTypeUnit(checkType) {
  if (["ping", "tcp", "http"].includes(checkType)) return "ms";
  if (["agent_resources", "zfs_health"].includes(checkType)) return "%";
  if (["service_process", "proxmox_backup", "docker_health"].includes(checkType)) return "";
  if (checkType === "agent_ping") return "s";
  return "";
}

/** Prüft ob die Y-Achse auf 0-100 fixiert werden soll (Prozent-Checks). */
export function isPercentCheck(checkType) {
  return ["agent_resources", "zfs_health"].includes(checkType);
}

export function computeSummary(checks) {
  const s = { total: 0, ok: 0, warning: 0, critical: 0, unknown: 0, pending: 0 };
  for (const c of checks) {
    s.total++;
    const status = c.state?.status || "pending";
    if (s[status] !== undefined) s[status]++;
  }
  return s;
}
