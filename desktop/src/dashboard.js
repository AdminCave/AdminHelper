export function initDashboard(state, t, callbacks) {
  const container = document.getElementById("dashboardContent");

  function getRecentConnections(count) {
    return [...state.connections]
      .filter((c) => c.lastUsed)
      .sort((a, b) => new Date(b.lastUsed) - new Date(a.lastUsed))
      .slice(0, count);
  }

  function getConnectionStats() {
    const total = state.connections.length;
    const ssh = state.connections.filter((c) => c.kind === "ssh").length;
    const rdp = state.connections.filter((c) => c.kind === "rdp").length;
    const web = state.connections.filter((c) => c.kind === "web").length;
    return { total, ssh, rdp, web };
  }

  function getMonitoringStats() {
    const checks = state.monitorChecks || [];
    const total = checks.length;
    const ok = checks.filter((c) => c.status === "ok").length;
    const warning = checks.filter((c) => c.status === "warning").length;
    const critical = checks.filter((c) => c.status === "critical").length;
    return { total, ok, warning, critical };
  }

  function formatTimeAgo(dateStr) {
    if (!dateStr) return "-";
    const diff = Date.now() - new Date(dateStr).getTime();
    if (diff < 0) return "-";
    const secs = Math.floor(diff / 1000);
    if (secs < 60) return t("dashboard.justNow");
    const mins = Math.floor(secs / 60);
    if (mins < 60) return t("dashboard.timeAgo.minutes", { count: mins });
    const hours = Math.floor(mins / 60);
    if (hours < 24) return t("dashboard.timeAgo.hours", { count: hours });
    const days = Math.floor(hours / 24);
    if (days === 1) return t("dashboard.timeAgo.yesterday");
    if (days < 30) return t("dashboard.timeAgo.days", { count: days });
    const months = Math.floor(days / 30);
    if (months >= 12) {
      const years = Math.floor(months / 12);
      return t("dashboard.timeAgo.years", { count: years });
    }
    return t("dashboard.timeAgo.months", { count: months });
  }

  function isServerMode() {
    const mode = (state.settings || {}).mode;
    return mode === "server" && state.session;
  }

  function render() {
    const connStats = getConnectionStats();
    const recent = getRecentConnections(5);
    const hasMonitoring = isServerMode();
    const monStats = hasMonitoring ? getMonitoringStats() : null;

    let html = "";

    // Connection Stats
    html += `<div class="dash-stats">`;
    html += `<div class="stat-card --accent"><div class="stat-value">${connStats.total}</div><div class="stat-label">${t("dashboard.totalConnections")}</div></div>`;
    html += `<div class="stat-card"><div class="stat-value">${connStats.ssh}</div><div class="stat-label">SSH</div></div>`;
    html += `<div class="stat-card"><div class="stat-value">${connStats.rdp}</div><div class="stat-label">RDP</div></div>`;
    html += `<div class="stat-card"><div class="stat-value">${connStats.web}</div><div class="stat-label">Web</div></div>`;

    if (monStats && monStats.total > 0) {
      html += `<div class="stat-card --ok"><div class="stat-value">${monStats.ok}</div><div class="stat-label">${t("monitoring.ok")}</div></div>`;
      html += `<div class="stat-card --warning"><div class="stat-value">${monStats.warning}</div><div class="stat-label">${t("monitoring.warning")}</div></div>`;
      html += `<div class="stat-card --critical"><div class="stat-value">${monStats.critical}</div><div class="stat-label">${t("monitoring.critical")}</div></div>`;
    }
    html += `</div>`;

    // Grid: Recent + Monitoring
    html += `<div class="dash-grid">`;

    // Recent Connections
    html += `<div class="dash-panel">`;
    html += `<div class="dash-panel-title">${t("dashboard.recentConnections")}</div>`;
    if (recent.length > 0) {
      html += `<div class="dash-list">`;
      recent.forEach((conn) => {
        const kindColor = conn.kind === "ssh" ? "var(--accent)" : conn.kind === "rdp" ? "var(--warning)" : "var(--success)";
        html += `<div class="dash-list-item" data-action="connect" data-id="${conn.id}">`;
        html += `<div class="dash-list-item-dot" style="background:${kindColor}"></div>`;
        html += `<div class="dash-list-item-name">${escapeHtml(conn.name || conn.host || "-")}</div>`;
        html += `<span class="mon-type-badge" style="font-size:10px">${conn.kind.toUpperCase()}</span>`;
        html += `<div class="dash-list-item-meta">${formatTimeAgo(conn.lastUsed)}</div>`;
        html += `</div>`;
      });
      html += `</div>`;
    } else {
      html += `<div class="dash-empty">${t("dashboard.noRecent")}</div>`;
    }
    html += `</div>`;

    // Monitoring Status (only in server mode)
    if (hasMonitoring && (state.monitorChecks || []).length > 0) {
      const problemChecks = (state.monitorChecks || [])
        .filter((c) => c.status === "critical" || c.status === "warning")
        .slice(0, 5);

      html += `<div class="dash-panel">`;
      html += `<div class="dash-panel-title">${t("dashboard.monitoringStatus")}</div>`;
      if (problemChecks.length > 0) {
        html += `<div class="dash-list">`;
        problemChecks.forEach((check) => {
          const dotClass = check.status === "critical" ? "mon-critical" : "mon-warning";
          html += `<div class="dash-list-item" data-action="monitoring">`;
          html += `<div class="dash-list-item-dot ${dotClass}"></div>`;
          html += `<div class="dash-list-item-name">${escapeHtml(check.name || "-")}</div>`;
          html += `<span class="mon-type-badge badge-${check.type || "ping"}">${(check.type || "ping").toUpperCase()}</span>`;
          html += `</div>`;
        });
        html += `</div>`;
      } else {
        html += `<div class="mon-all-ok"><span>&#10003;</span> ${t("dashboard.allOk")}</div>`;
      }
      html += `</div>`;
    }

    html += `</div>`;

    // Quick Actions
    html += `<div class="dash-actions">`;
    html += `<button class="btn primary" data-action="new-connection">${t("connections.new")}</button>`;
    if (hasMonitoring) {
      html += `<button class="btn" data-action="open-monitoring">${t("nav.monitoring")}</button>`;
    }
    html += `</div>`;

    container.innerHTML = html;

    // Event listeners
    container.querySelectorAll("[data-action='connect']").forEach((el) => {
      el.addEventListener("click", () => {
        const conn = state.connections.find((c) => c.id === el.dataset.id);
        if (conn) callbacks.initiateConnect(conn);
      });
    });

    container.querySelectorAll("[data-action='monitoring']").forEach((el) => {
      el.addEventListener("click", () => callbacks.switchView("monitoring"));
    });

    const newBtn = container.querySelector("[data-action='new-connection']");
    if (newBtn) {
      newBtn.addEventListener("click", () => {
        callbacks.switchView("connections");
        callbacks.openEditor();
      });
    }

    const monBtn = container.querySelector("[data-action='open-monitoring']");
    if (monBtn) {
      monBtn.addEventListener("click", () => callbacks.switchView("monitoring"));
    }
  }

  function escapeHtml(str) {
    const div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
  }

  return { render };
}
