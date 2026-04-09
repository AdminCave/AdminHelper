import {
  groupChecksByServer,
  filterChecks,
  worstStatus,
  statusClass,
  formatCheckTime,
  computeSummary,
  formatCheckConfig,
  checkTypeUnit,
  isPercentCheck
} from "./monitoringModel.js";

export function initMonitoring(state, t, monitoringApiFactory) {
  let monitoringApi = null;
  let refreshTimer = null;
  let activeChart = null;
  let resizeObserver = null;
  let expandedCheckId = null;

  const section = document.getElementById("monitoringSection");
  const summaryContainer = document.getElementById("monSummaryCards");
  const filterBar = document.getElementById("monFilterBar");
  const checkListContainer = document.getElementById("monCheckList");
  const alertListContainer = document.getElementById("monAlertList");
  const alertLogContainer = document.getElementById("monAlertLog");

  function ensureApi() {
    if (!state.session) return false;
    if (!monitoringApi) {
      monitoringApi = monitoringApiFactory(state.session);
    }
    return true;
  }

  function destroyChart() {
    if (activeChart) {
      activeChart.destroy();
      activeChart = null;
    }
    if (resizeObserver) {
      resizeObserver.disconnect();
      resizeObserver = null;
    }
  }

  function startRefresh() {
    stopRefresh();
    refreshTimer = setInterval(() => loadMonitoring(), 30_000);
  }

  function stopRefresh() {
    if (refreshTimer) {
      clearInterval(refreshTimer);
      refreshTimer = null;
    }
  }

  // ── Summary Cards ──────────────────────────────────────────────────
  function renderSummaryCards(checks) {
    summaryContainer.innerHTML = "";
    const summary = computeSummary(checks);
    const cards = [
      { key: "total", label: t("monitoring.total"), value: summary.total, cls: "" },
      { key: "ok", label: t("monitoring.ok"), value: summary.ok, cls: "mon-summary-ok" },
      { key: "warning", label: t("monitoring.warning"), value: summary.warning, cls: "mon-summary-warning" },
      { key: "critical", label: t("monitoring.critical"), value: summary.critical, cls: "mon-summary-critical" }
    ];
    for (const c of cards) {
      const card = document.createElement("div");
      card.className = `mon-summary-card ${c.cls}`;
      const val = document.createElement("div");
      val.className = "mon-summary-value";
      val.textContent = String(c.value);
      const lbl = document.createElement("div");
      lbl.className = "mon-summary-label";
      lbl.textContent = c.label;
      card.append(val, lbl);
      summaryContainer.appendChild(card);
    }
  }

  // ── Helpers ─────────────────────────────────────────────────────────
  function buildServerMap() {
    const map = {};
    for (const s of state.monitorServers || []) {
      map[s.id] = s;
    }
    return map;
  }

  function resolveServerName(serverId) {
    const srv = buildServerMap()[serverId];
    return srv ? (srv.name || srv.hostname || serverId) : serverId;
  }

  // ── Filter Bar ─────────────────────────────────────────────────────
  function renderFilterBar(checks) {
    filterBar.innerHTML = "";

    const serverIds = [...new Set(checks.map((c) => c.serverId).filter(Boolean))].sort();
    const types = [...new Set(checks.map((c) => c.checkType))].sort();

    const serverOptions = serverIds.map((id) => ({ value: id, label: resolveServerName(id) }));
    serverOptions.sort((a, b) => a.label.localeCompare(b.label));
    const serverSelect = buildSelect("monFilterServer", t("monitoring.filter.allServers"), serverOptions);
    serverSelect.value = state.monitorFilters.server || "";
    serverSelect.addEventListener("change", () => { state.monitorFilters.server = serverSelect.value; applyFilters(); });

    const typeSelect = buildSelect("monFilterType", t("monitoring.filter.allTypes"), types.map((tp) => ({ value: tp, label: tp.toUpperCase() })));
    typeSelect.value = state.monitorFilters.type || "";
    typeSelect.addEventListener("change", () => { state.monitorFilters.type = typeSelect.value; applyFilters(); });

    const statusOpts = ["ok", "warning", "critical", "unknown", "pending"].map((s) => ({ value: s, label: s.charAt(0).toUpperCase() + s.slice(1) }));
    const statusSelect = buildSelect("monFilterStatus", t("monitoring.filter.allStatus"), statusOpts);
    statusSelect.value = state.monitorFilters.status || "";
    statusSelect.addEventListener("change", () => { state.monitorFilters.status = statusSelect.value; applyFilters(); });

    const searchInput = document.createElement("input");
    searchInput.type = "search";
    searchInput.placeholder = t("monitoring.filter.search");
    searchInput.className = "mon-filter-search";
    searchInput.value = state.monitorFilters.search || "";
    searchInput.addEventListener("input", () => { state.monitorFilters.search = searchInput.value; applyFilters(); });

    filterBar.append(serverSelect, typeSelect, statusSelect, searchInput);
  }

  function buildSelect(id, allLabel, options) {
    const sel = document.createElement("select");
    sel.id = id;
    sel.className = "mon-filter-select";
    const allOpt = document.createElement("option");
    allOpt.value = "";
    allOpt.textContent = allLabel;
    sel.appendChild(allOpt);
    for (const o of options) {
      const opt = document.createElement("option");
      opt.value = o.value;
      opt.textContent = o.label;
      sel.appendChild(opt);
    }
    return sel;
  }

  function applyFilters() {
    const filtered = filterChecks(state.monitorChecks, state.monitorFilters);
    renderSummaryCards(filtered);
    renderCheckList(filtered);
  }

  // ── Check List ─────────────────────────────────────────────────────
  function renderCheckList(checks) {
    checkListContainer.innerHTML = "";
    if (checks.length === 0) {
      const empty = document.createElement("div");
      empty.className = "mon-empty";
      empty.textContent = t("monitoring.noChecks");
      checkListContainer.appendChild(empty);
      return;
    }
    const groups = groupChecksByServer(checks, state.monitorServers || []);
    for (const group of groups) {
      const groupEl = buildServerGroup(group);
      checkListContainer.appendChild(groupEl);
    }

    // Offenes Detail-Panel nach Re-Rendering wiederherstellen
    if (expandedCheckId) {
      const check = checks.find((c) => c.id === expandedCheckId);
      const row = checkListContainer.querySelector(`.mon-check-row[data-check-id="${expandedCheckId}"]`);
      if (check && row) {
        toggleDetailPanel(check, row);
      } else {
        expandedCheckId = null;
      }
    }
  }

  function buildServerGroup(group) {
    const wrapper = document.createElement("div");
    wrapper.className = "mon-server-group open";
    const worst = worstStatus(group.checks);

    const header = document.createElement("div");
    header.className = "mon-server-header";
    header.addEventListener("click", () => wrapper.classList.toggle("open"));

    const dot = document.createElement("span");
    dot.className = `mon-dot ${statusClass(worst)}`;
    const name = document.createElement("span");
    name.className = "mon-server-name";
    name.textContent = group.serverName || group.serverId || t("monitoring.noServer");
    const count = document.createElement("span");
    count.className = "mon-server-count";
    count.textContent = `${group.checks.length}`;
    const chevron = document.createElement("span");
    chevron.className = "mon-chevron";
    chevron.textContent = "▸";

    header.append(chevron, dot, name, count);

    const body = document.createElement("div");
    body.className = "mon-server-body";
    for (const check of group.checks) {
      body.appendChild(buildCheckRow(check));
    }

    wrapper.append(header, body);
    return wrapper;
  }

  function buildCheckRow(check) {
    const status = check.state?.status || "pending";
    const row = document.createElement("div");
    row.className = "mon-check-row";
    row.dataset.checkId = check.id;

    const dot = document.createElement("span");
    dot.className = `mon-dot ${statusClass(status)}`;

    const typeBadge = document.createElement("span");
    typeBadge.className = `mon-type-badge badge-${check.checkType}`;
    typeBadge.textContent = check.checkType.toUpperCase();

    const nameEl = document.createElement("span");
    nameEl.className = "mon-check-name";
    nameEl.textContent = check.name;

    const msgEl = document.createElement("span");
    msgEl.className = "mon-check-msg";
    msgEl.textContent = check.state?.message || "";

    const timeEl = document.createElement("span");
    timeEl.className = "mon-check-time";
    timeEl.textContent = formatCheckTime(check.state?.lastCheck);

    const actions = document.createElement("div");
    actions.className = "mon-check-actions";

    const toggleBtn = document.createElement("button");
    toggleBtn.className = `btn small ${check.enabled ? "ghost" : "primary"}`;
    toggleBtn.textContent = check.enabled ? t("monitoring.action.disable") : t("monitoring.action.enable");
    toggleBtn.addEventListener("click", async (e) => {
      e.stopPropagation();
      await handleToggleCheck(check.id);
    });

    const runBtn = document.createElement("button");
    runBtn.className = "btn small accent";
    runBtn.textContent = t("monitoring.action.run");
    runBtn.addEventListener("click", async (e) => {
      e.stopPropagation();
      await handleRunCheck(check.id);
    });

    actions.append(toggleBtn, runBtn);
    row.append(dot, typeBadge, nameEl, msgEl, timeEl, actions);

    row.addEventListener("click", () => toggleDetailPanel(check, row));

    return row;
  }

  // ── Detail Panel (Metrics) ─────────────────────────────────────────
  const NO_CHART_TYPES = ["service_process", "docker_health", "proxmox_backup"];

  function toggleDetailPanel(check, rowEl) {
    const existingPanel = rowEl.parentElement.querySelector(`.mon-detail-panel[data-check-id="${check.id}"]`);
    if (existingPanel) {
      destroyChart();
      existingPanel.remove();
      expandedCheckId = null;
      return;
    }

    // Close any other open panel
    const openPanels = checkListContainer.querySelectorAll(".mon-detail-panel");
    openPanels.forEach((p) => p.remove());
    destroyChart();

    expandedCheckId = check.id;
    const panel = document.createElement("div");
    panel.className = "mon-detail-panel";
    panel.dataset.checkId = check.id;

    const info = document.createElement("div");
    info.className = "mon-detail-info";
    info.innerHTML = `<strong>${check.name}</strong> &mdash; ${check.checkType.toUpperCase()}`;
    if (check.description) {
      const desc = document.createElement("div");
      desc.className = "mon-detail-desc";
      desc.textContent = check.description;
      info.appendChild(desc);
    }

    // Config-Zusammenfassung
    const configKV = formatCheckConfig(check);
    if (configKV.length > 0) {
      const configEl = document.createElement("div");
      configEl.className = "mon-detail-config";
      configEl.innerHTML = configKV.map(([k, v]) => `<span class="mon-cfg-key">${k}:</span> <span class="mon-cfg-val">${v}</span>`).join("  &middot;  ");
      info.appendChild(configEl);
    }

    panel.appendChild(info);

    // Typspezifischer Content aus state.details
    const typeContent = document.createElement("div");
    typeContent.className = "mon-type-content";
    renderTypeContent(check, typeContent);
    panel.appendChild(typeContent);

    // Chart nur fuer Typen die Zeitreihen-Daten haben
    // agent_resources: kein Auto-Chart wenn Details vorhanden (Gauges haben eigenen On-Demand-Chart)
    const skipChart = NO_CHART_TYPES.includes(check.checkType)
      || (check.checkType === "agent_resources" && check.state?.details);
    if (!skipChart) {
      const currentValues = document.createElement("div");
      currentValues.className = "mon-detail-current";

      const periodBar = document.createElement("div");
      periodBar.className = "mon-period-selector";
      const periods = ["1h", "6h", "24h", "7d"];
      let activePeriod = "1h";
      for (const p of periods) {
        const chip = document.createElement("button");
        chip.className = `chip ${p === activePeriod ? "active" : ""}`;
        chip.textContent = p;
        chip.addEventListener("click", () => {
          activePeriod = p;
          periodBar.querySelectorAll(".chip").forEach((c) => c.classList.toggle("active", c.textContent === p));
          loadAndRenderChart(check, p, chartContainer, currentValues, timelineContainer);
        });
        periodBar.appendChild(chip);
      }

      const chartContainer = document.createElement("div");
      chartContainer.className = "mon-chart-container";

      const timelineContainer = document.createElement("div");
      timelineContainer.className = "mon-status-timeline";

      panel.append(currentValues, periodBar, chartContainer, timelineContainer);

      loadAndRenderChart(check, activePeriod, chartContainer, currentValues, timelineContainer);
    }

    rowEl.after(panel);
    requestAnimationFrame(() => panel.scrollIntoView({ behavior: "smooth", block: "nearest" }));
  }

  // ── Type-Specific Renderers ────────────────────────────────────────
  function renderTypeContent(check, container) {
    const details = check.state?.details;
    switch (check.checkType) {
      case "agent_resources": return renderResourceGauges(container, details, check.config, check);
      case "service_process": return renderServiceList(container, details);
      case "docker_health": return renderContainerList(container, details);
      case "proxmox_backup": return renderBackupList(container, details);
      case "zfs_health": return renderZfsGauges(container, details);
      case "agent_ping": return renderAgentPingValue(container, check);
      default: break; // ping, tcp, http - nur Chart
    }
  }

  function gaugeClass(pct, warn, crit) {
    if (pct >= crit) return "gauge-crit";
    if (pct >= warn) return "gauge-warn";
    return "gauge-ok";
  }

  function buildGaugeItem(label, pct, detailText, cls, metricName) {
    const item = document.createElement("div");
    item.className = "mon-gauge-item" + (metricName ? " mon-gauge-clickable" : "");
    if (metricName) item.dataset.metric = metricName;
    item.innerHTML = `
      <span class="mon-gauge-label">${label}</span>
      <div class="mon-gauge-bar">
        <div class="mon-gauge-fill ${cls}" style="width:${Math.min(pct, 100)}%"></div>
        <span class="mon-gauge-text">${pct.toFixed(1)}%</span>
      </div>
      ${detailText ? `<span class="mon-gauge-detail">${detailText}</span>` : ""}
    `;
    return item;
  }

  function renderResourceGauges(container, details, config, check) {
    if (!details) return;
    const grid = document.createElement("div");
    grid.className = "mon-gauge-grid";
    const cpuWarn = config?.cpu_warn || 80;
    const cpuCrit = config?.cpu_crit || 95;
    const memWarn = config?.memory_warn || 80;
    const memCrit = config?.memory_crit || 95;
    const diskWarn = config?.disk_warn || 85;
    const diskCrit = config?.disk_crit || 95;

    if (details.cpu != null) {
      grid.appendChild(buildGaugeItem("CPU", details.cpu, null, gaugeClass(details.cpu, cpuWarn, cpuCrit), "monitor_agent_cpu_percent"));
    }
    if (details.memory != null) {
      const memDetail = details.memory_total_mb
        ? `${details.memory_used_mb || 0} / ${details.memory_total_mb} MB`
        : null;
      grid.appendChild(buildGaugeItem("RAM", details.memory, memDetail, gaugeClass(details.memory, memWarn, memCrit), "monitor_agent_memory_percent"));
    }
    for (const disk of details.disks || []) {
      const diskDetail = disk.total_gb != null
        ? `${(disk.used_gb || 0).toFixed(1)} / ${disk.total_gb.toFixed(1)} GB`
        : null;
      grid.appendChild(buildGaugeItem(disk.mount, disk.percent, diskDetail, gaugeClass(disk.percent, diskWarn, diskCrit), "monitor_agent_disk_percent"));
    }
    container.appendChild(grid);

    // Chart-Bereich fuer angeklickte Gauge
    const chartArea = document.createElement("div");
    chartArea.className = "mon-gauge-chart-area hidden";
    container.appendChild(chartArea);

    let activeMetric = null;
    let activePeriod = "1h";

    grid.addEventListener("click", (e) => {
      const gaugeItem = e.target.closest(".mon-gauge-clickable");
      if (!gaugeItem) return;
      const metric = gaugeItem.dataset.metric;
      const diskMount = gaugeItem.querySelector(".mon-gauge-label")?.textContent;

      // Toggle: gleicher Gauge nochmal -> schliessen
      const metricKey = metric + (diskMount || "");
      if (activeMetric === metricKey) {
        chartArea.classList.add("hidden");
        chartArea.innerHTML = "";
        grid.querySelectorAll(".mon-gauge-item").forEach((g) => g.classList.remove("mon-gauge-active"));
        activeMetric = null;
        destroyChart();
        return;
      }

      activeMetric = metricKey;
      activePeriod = "1h";
      grid.querySelectorAll(".mon-gauge-item").forEach((g) => g.classList.remove("mon-gauge-active"));
      gaugeItem.classList.add("mon-gauge-active");

      chartArea.classList.remove("hidden");
      chartArea.innerHTML = "";

      const periodBar = document.createElement("div");
      periodBar.className = "mon-period-selector";
      for (const p of ["1h", "6h", "24h", "7d"]) {
        const chip = document.createElement("button");
        chip.className = `chip ${p === activePeriod ? "active" : ""}`;
        chip.textContent = p;
        chip.addEventListener("click", () => {
          activePeriod = p;
          periodBar.querySelectorAll(".chip").forEach((c) => c.classList.toggle("active", c.textContent === p));
          loadGaugeChart(check, p, chartContainer, metric, diskMount);
        });
        periodBar.appendChild(chip);
      }

      const chartContainer = document.createElement("div");
      chartContainer.className = "mon-chart-container";

      chartArea.append(periodBar, chartContainer);
      loadGaugeChart(check, activePeriod, chartContainer, metric, diskMount);
    });
  }

  async function loadGaugeChart(check, period, container, metricFilter, diskMount) {
    if (!ensureApi()) return;
    container.innerHTML = `<div class="mon-chart-loading">${t("monitoring.chart.loading")}</div>`;
    try {
      const metricsData = await monitoringApi.fetchMetrics(check.id, period);
      const allSeries = metricsData?.data || [];
      // Filter auf die angeklickte Metrik
      // VictoriaMetrics haengt '_value' an InfluxDB-Metriken an
      const filtered = allSeries.filter((s) => {
        const name = s.metric?.__name__ || "";
        if (metricFilter === "monitor_agent_disk_percent") {
          if (!name.startsWith("monitor_agent_disk_percent")) return false;
          if (name.includes("cpu") || name.includes("memory")) return false;
          const mount = s.metric?.mount || "";
          return mount ? mount === diskMount : name.includes(diskMount || "/");
        }
        return name === metricFilter || name === metricFilter + "_value";
      });
      if (filtered.length === 0) {
        container.innerHTML = `<div class="mon-chart-loading">${t("monitoring.chart.noData")}</div>`;
        return;
      }
      renderChart(container, { data: filtered }, check.checkType);
    } catch (err) {
      container.innerHTML = `<div class="mon-chart-loading">${t("monitoring.chart.error")}</div>`;
    }
  }

  function renderServiceList(container, details) {
    if (!details) return;
    if (details.mode === "auto") {
      const failed = details.failed || [];
      const inactive = details.enabled_inactive || [];
      if (failed.length === 0 && inactive.length === 0) {
        container.innerHTML = `<div class="mon-all-ok"><span class="mon-item-dot item-ok"></span> ${t("monitoring.detail.allUnitsOk")}</div>`;
        return;
      }
      const list = document.createElement("div");
      list.className = "mon-item-list";
      if (failed.length > 0) {
        const title = document.createElement("div");
        title.className = "mon-section-title";
        title.textContent = "Failed";
        list.appendChild(title);
        for (const svc of failed) {
          list.appendChild(buildItemRow(svc, "critical", "failed"));
        }
      }
      if (inactive.length > 0) {
        const title = document.createElement("div");
        title.className = "mon-section-title";
        title.textContent = "Inaktiv (Autostart)";
        list.appendChild(title);
        for (const svc of inactive) {
          list.appendChild(buildItemRow(svc, "warn", "inactive"));
        }
      }
      container.appendChild(list);
    } else {
      // list mode
      const watched = details.watched || [];
      if (watched.length === 0) return;
      const allOk = watched.every((s) => s.running);
      if (allOk) {
        container.innerHTML = `<div class="mon-all-ok"><span class="mon-item-dot item-ok"></span> Alle ${watched.length} Services aktiv</div>`;
        return;
      }
      const list = document.createElement("div");
      list.className = "mon-item-list";
      for (const svc of watched) {
        list.appendChild(buildItemRow(svc.name, svc.running ? "ok" : "critical", svc.running ? "running" : "down"));
      }
      container.appendChild(list);
    }
  }

  function renderContainerList(container, details) {
    if (!details?.containers?.length) return;
    const allOk = details.containers.every((c) => c.category === "ok");
    if (allOk) {
      container.innerHTML = `<div class="mon-all-ok"><span class="mon-item-dot item-ok"></span> Alle ${details.containers.length} Container laufen</div>`;
      return;
    }
    const list = document.createElement("div");
    list.className = "mon-item-list";
    // Probleme zuerst
    const sorted = [...details.containers].sort((a, b) => {
      const order = { critical: 0, warning: 1, ok: 2 };
      return (order[a.category] ?? 2) - (order[b.category] ?? 2);
    });
    for (const c of sorted) {
      const catMap = { critical: "critical", warning: "warn", ok: "ok" };
      const row = buildItemRow(c.name, catMap[c.category] || "ok", c.state);
      if (c.image) {
        const badge = document.createElement("span");
        badge.className = "mon-item-badge";
        badge.textContent = c.image.split(":")[0].split("/").pop();
        row.insertBefore(badge, row.querySelector(".mon-item-status"));
      }
      list.appendChild(row);
    }
    container.appendChild(list);
  }

  function renderBackupList(container, details) {
    if (!details?.vms?.length) return;
    const allOk = details.vms.every((v) => v.backupStatus === "ok");
    if (allOk) {
      container.innerHTML = `<div class="mon-all-ok"><span class="mon-item-dot item-ok"></span> Alle ${details.vms.length} VMs/CTs haben aktuelle Backups</div>`;
      return;
    }
    const list = document.createElement("div");
    list.className = "mon-item-list";
    const sorted = [...details.vms].sort((a, b) => {
      const order = { missing: 0, outdated: 1, ok: 2 };
      return (order[a.backupStatus] ?? 2) - (order[b.backupStatus] ?? 2);
    });
    for (const vm of sorted) {
      const catMap = { ok: "ok", outdated: "warn", missing: "critical" };
      let statusText = vm.backupStatus === "ok" ? "OK" : vm.backupStatus === "missing" ? "Kein Backup" : `Veraltet (${vm.ageHours}h)`;
      const row = buildItemRow(`${vm.name} (${vm.vmid})`, catMap[vm.backupStatus] || "ok", statusText);
      const badge = document.createElement("span");
      badge.className = "mon-item-badge";
      badge.textContent = (vm.type || "vm").toUpperCase();
      row.insertBefore(badge, row.querySelector(".mon-item-name"));
      list.appendChild(row);
    }
    container.appendChild(list);
  }

  function renderZfsGauges(container, details) {
    if (!details?.pools?.length) return;
    const grid = document.createElement("div");
    grid.className = "mon-gauge-grid";
    for (const pool of details.pools) {
      const healthCls = pool.health === "ONLINE" ? "health-online" : pool.health === "DEGRADED" ? "health-degraded" : "health-faulted";
      const item = document.createElement("div");
      item.className = "mon-gauge-item";
      item.innerHTML = `
        <span class="mon-gauge-label">${pool.name}</span>
        <div class="mon-gauge-bar">
          <div class="mon-gauge-fill ${gaugeClass(pool.capacityPercent, 80, 90)}" style="width:${Math.min(pool.capacityPercent, 100)}%"></div>
          <span class="mon-gauge-text">${pool.capacityPercent}%</span>
        </div>
        <span class="mon-health-badge ${healthCls}">${pool.health}</span>
      `;
      grid.appendChild(item);
    }
    container.appendChild(grid);
  }

  function renderAgentPingValue(container, check) {
    const msg = check.state?.message || "";
    const match = msg.match(/(\d+)/);
    const seconds = match ? parseInt(match[1], 10) : null;
    if (seconds == null) return;
    const display = seconds < 120 ? `${seconds}s` : `${Math.round(seconds / 60)}m`;
    container.innerHTML = `<div class="mon-last-seen"><span class="mon-last-seen-value">${display}</span><span class="mon-last-seen-unit">${t("monitoring.detail.lastSeen")}</span></div>`;
  }

  function buildItemRow(name, category, statusText) {
    const row = document.createElement("div");
    row.className = "mon-item-row";
    const catCls = category === "critical" ? "item-crit" : category === "warn" ? "item-warn" : "item-ok";
    row.innerHTML = `
      <span class="mon-item-dot ${catCls}"></span>
      <span class="mon-item-name">${name}</span>
      <span class="mon-item-status">${statusText}</span>
    `;
    return row;
  }

  async function loadAndRenderChart(check, period, container, currentValuesEl, timelineEl) {
    if (!ensureApi()) return;
    container.innerHTML = `<div class="mon-chart-loading">${t("monitoring.chart.loading")}</div>`;
    try {
      const metricsData = await monitoringApi.fetchMetrics(check.id, period);
      renderChart(container, metricsData, check.checkType);
      renderCurrentValues(currentValuesEl, metricsData, check.checkType);
      renderStatusTimeline(timelineEl, metricsData?.statusHistory);
    } catch (err) {
      console.error("[monitoring] metrics fetch error:", err);
      container.innerHTML = `<div class="mon-chart-loading">${t("monitoring.chart.error")}</div>`;
    }
  }

  function renderCurrentValues(el, metricsData, checkType) {
    el.innerHTML = "";
    const results = metricsData?.data || [];
    if (results.length === 0) return;

    const unit = checkTypeUnit(checkType);
    const parts = [];
    for (const series of results) {
      const name = series.metric?.__name__ || "";
      if (name.includes("status")) continue;
      const values = series.values || [];
      if (values.length === 0) continue;
      const last = parseFloat(values[values.length - 1][1]);
      if (isNaN(last)) continue;

      const label = name
        .replace("monitor_check_", "")
        .replace("monitor_agent_", "")
        .replace("monitor_", "")
        .replace(/_value$/, "")
        .replace(/_/g, " ");
      const formatted = Number.isInteger(last) ? String(last) : last.toFixed(1);
      parts.push(`<span class="mon-current-item"><strong>${label}</strong> ${formatted}${unit}</span>`);
    }
    if (parts.length > 0) {
      el.innerHTML = parts.join("  ");
    }
  }

  function renderStatusTimeline(el, statusHistory) {
    el.innerHTML = "";
    const results = statusHistory || [];
    if (results.length === 0 || !results[0]?.values?.length) return;

    const values = results[0].values;
    const statusColors = { 0: "var(--mon-ok-bg, #22c55e)", 1: "var(--mon-warn-bg, #f59e0b)", 2: "var(--mon-crit-bg, #ef4444)", 3: "var(--mon-unknown-bg, #94a3b8)" };
    const bar = document.createElement("div");
    bar.className = "mon-timeline-bar";

    let segStart = 0;
    let segStatus = Math.round(parseFloat(values[0][1]));
    for (let i = 1; i <= values.length; i++) {
      const curStatus = i < values.length ? Math.round(parseFloat(values[i][1])) : -1;
      if (curStatus !== segStatus) {
        const pct = ((i - segStart) / values.length) * 100;
        const seg = document.createElement("div");
        seg.className = "mon-timeline-seg";
        seg.style.width = `${pct}%`;
        seg.style.backgroundColor = statusColors[segStatus] || statusColors[3];
        bar.appendChild(seg);
        segStart = i;
        segStatus = curStatus;
      }
    }
    el.appendChild(bar);
  }

  function renderChart(container, metricsData, checkType) {
    destroyChart();
    container.innerHTML = "";

    const results = metricsData?.data || [];
    if (results.length === 0) {
      container.innerHTML = `<div class="mon-chart-loading">${t("monitoring.chart.noData")}</div>`;
      return;
    }

    // Skip the status metric, prefer duration/value metrics
    const filtered = results.filter((r) => {
      const name = r.metric?.__name__ || "";
      return !name.includes("status");
    });
    const series = filtered.length > 0 ? filtered : results;

    // Build uPlot data
    const timestamps = series[0].values.map((v) => Number(v[0]));
    const data = [timestamps];
    const uplotSeries = [{}];
    const colors = ["#38bdf8", "#22c55e", "#f97316", "#a855f7", "#ec4899", "#14b8a6"];

    for (let i = 0; i < series.length; i++) {
      const values = series[i].values.map((v) => {
        const n = parseFloat(v[1]);
        return isNaN(n) ? null : n;
      });
      data.push(values);

      const metricName = series[i].metric.__name__ || series[i].metric.name || `Series ${i + 1}`;
      const label = metricName
        .replace("monitor_check_", "")
        .replace("monitor_agent_", "")
        .replace("monitor_", "")
        .replace(/_value$/, "")
        .replace(/_/g, " ");

      uplotSeries.push({
        label,
        stroke: colors[i % colors.length],
        width: 2,
        fill: ["service_process", "proxmox_backup", "docker_health"].includes(checkType)
          ? colors[i % colors.length] + "30"
          : undefined,
      });
    }

    if (typeof window.uPlot === "undefined") {
      container.innerHTML = `<div class="mon-chart-loading">uPlot not loaded</div>`;
      return;
    }

    const unit = checkTypeUnit(checkType);
    const pctCheck = isPercentCheck(checkType);
    const axisStyle = { stroke: "#94a3b8", grid: { stroke: "rgba(148,163,184,0.12)" }, ticks: { stroke: "rgba(148,163,184,0.12)" } };

    const opts = {
      width: container.offsetWidth || 600,
      height: 250,
      series: uplotSeries,
      axes: [
        axisStyle,
        {
          ...axisStyle,
          label: unit || undefined,
          ...(pctCheck ? { range: [0, 100] } : {}),
        }
      ],
      cursor: { drag: { x: false, y: false } },
      scales: {
        x: { time: true },
        ...(pctCheck ? { y: { min: 0, max: 100 } } : {}),
      }
    };

    function createChart() {
      opts.width = container.offsetWidth || 600;
      activeChart = new window.uPlot(opts, data, container);
    }

    // Sicherstellen, dass der Container im Layout ist, bevor uPlot die Breite misst
    if (container.offsetWidth > 0) {
      createChart();
    } else {
      requestAnimationFrame(createChart);
    }

    resizeObserver = new ResizeObserver(() => {
      if (activeChart && container.offsetWidth > 0) {
        activeChart.setSize({ width: container.offsetWidth, height: 250 });
      }
    });
    resizeObserver.observe(container);
  }

  // ── Alerts Tab ─────────────────────────────────────────────────────
  async function loadAlerts() {
    if (!ensureApi()) return;
    try {
      state.monitorAlertRules = await monitoringApi.fetchAlerts();
    } catch (_) {
      state.monitorAlertRules = [];
    }
    renderAlerts();
  }

  function renderAlerts() {
    alertListContainer.innerHTML = "";
    if (state.monitorAlertRules.length === 0) {
      const empty = document.createElement("div");
      empty.className = "mon-empty";
      empty.textContent = t("monitoring.alerts.noRules");
      alertListContainer.appendChild(empty);
      return;
    }
    for (const rule of state.monitorAlertRules) {
      alertListContainer.appendChild(buildAlertCard(rule));
    }
  }

  function buildAlertCard(rule) {
    const card = document.createElement("div");
    card.className = "mon-alert-card";

    const left = document.createElement("div");
    left.className = "mon-alert-info";

    const name = document.createElement("div");
    name.className = "mon-alert-name";
    name.textContent = rule.name;

    const meta = document.createElement("div");
    meta.className = "mon-alert-meta";
    const parts = [];
    parts.push(`${t("monitoring.alerts.channel")}: ${rule.channel}`);
    if (rule.matchSeverity) parts.push(`${t("monitoring.alerts.severity")}: ${rule.matchSeverity}`);
    parts.push(`${t("monitoring.alerts.cooldown")}: ${rule.cooldownMinutes}m`);
    meta.textContent = parts.join(" · ");

    left.append(name, meta);

    const actions = document.createElement("div");
    actions.className = "mon-alert-actions";
    const toggleBtn = document.createElement("button");
    toggleBtn.className = `btn small ${rule.enabled ? "ghost" : "primary"}`;
    toggleBtn.textContent = rule.enabled ? t("monitoring.action.disable") : t("monitoring.action.enable");
    toggleBtn.addEventListener("click", async () => {
      await handleToggleAlert(rule.id);
    });
    const statusDot = document.createElement("span");
    statusDot.className = `mon-dot ${rule.enabled ? "mon-ok" : "mon-unknown"}`;
    actions.append(statusDot, toggleBtn);

    card.append(left, actions);
    return card;
  }

  // ── Alert Log Tab ──────────────────────────────────────────────────
  async function loadAlertLog() {
    if (!ensureApi()) return;
    try {
      state.monitorAlertLog = await monitoringApi.fetchAlertLog(50);
    } catch (_) {
      state.monitorAlertLog = [];
    }
    renderAlertLog();
  }

  function renderAlertLog() {
    alertLogContainer.innerHTML = "";
    if (state.monitorAlertLog.length === 0) {
      const empty = document.createElement("div");
      empty.className = "mon-empty";
      empty.textContent = t("monitoring.log.noEntries");
      alertLogContainer.appendChild(empty);
      return;
    }
    for (const entry of state.monitorAlertLog) {
      alertLogContainer.appendChild(buildLogEntry(entry));
    }
  }

  function buildLogEntry(entry) {
    const row = document.createElement("div");
    row.className = "mon-log-entry";

    const time = document.createElement("span");
    time.className = "mon-log-time";
    time.textContent = formatCheckTime(entry.sentAt);

    const transition = document.createElement("span");
    transition.className = "mon-log-transition";
    const oldDot = document.createElement("span");
    oldDot.className = `mon-dot-sm ${statusClass(entry.oldStatus)}`;
    const arrow = document.createElement("span");
    arrow.textContent = " → ";
    const newDot = document.createElement("span");
    newDot.className = `mon-dot-sm ${statusClass(entry.newStatus)}`;
    const labels = document.createElement("span");
    labels.textContent = ` ${entry.oldStatus} → ${entry.newStatus}`;
    transition.append(oldDot, arrow, newDot, labels);

    const success = document.createElement("span");
    success.className = `mon-log-result ${entry.success ? "mon-ok" : "mon-critical"}`;
    success.textContent = entry.success ? "✓" : "✗";

    const error = document.createElement("span");
    error.className = "mon-log-error";
    error.textContent = entry.error || "";

    row.append(time, transition, success, error);
    return row;
  }

  // ── Actions ────────────────────────────────────────────────────────
  async function handleToggleCheck(checkId) {
    if (!ensureApi()) return;
    try {
      await monitoringApi.toggleCheck(checkId);
      await loadMonitoring();
    } catch (err) {
      showMonitoringError(err);
    }
  }

  async function handleRunCheck(checkId) {
    if (!ensureApi()) return;
    try {
      await monitoringApi.runCheck(checkId);
      setTimeout(() => loadMonitoring(), 2000);
    } catch (err) {
      showMonitoringError(err);
    }
  }

  async function handleToggleAlert(ruleId) {
    if (!ensureApi()) return;
    try {
      await monitoringApi.toggleAlert(ruleId);
      await loadAlerts();
    } catch (err) {
      showMonitoringError(err);
    }
  }

  function showMonitoringError(err) {
    const target = document.getElementById("globalStatus");
    if (!target) return;
    const msg = err.message === "SESSION_EXPIRED" ? t("monitoring.error.session") : t("monitoring.error.action");
    target.textContent = msg;
    target.classList.add("show");
    target.style.border = "1px solid rgba(248, 113, 113, 0.4)";
    target.style.color = "#fca5a5";
  }

  // ── Tab Switching ──────────────────────────────────────────────────
  function switchMonitorTab(tab) {
    state.monitorTab = tab;
    document.querySelectorAll(".mon-tab").forEach((t) => t.classList.toggle("active", t.dataset.tab === tab));
    document.querySelectorAll(".mon-tab-content").forEach((c) => c.classList.toggle("hidden", c.dataset.tab !== tab));
    destroyChart();
    expandedCheckId = null;

    if (tab === "alerts") loadAlerts();
    else if (tab === "log") loadAlertLog();
  }

  // ── Main Load ─���──────────────────────────────────────────────────���─
  async function loadServers() {
    if (!ensureApi()) return;
    try {
      const servers = await monitoringApi.fetchServers();
      state.monitorServers = Array.isArray(servers) ? servers : [];
    } catch (_) {
      state.monitorServers = [];
    }
  }

  async function loadMonitoring() {
    if (!ensureApi()) return;
    try {
      state.monitorChecks = await monitoringApi.fetchStatus();
    } catch (err) {
      if (err.message === "SESSION_EXPIRED") {
        showMonitoringError(err);
        return;
      }
      state.monitorChecks = [];
    }
    if (state.monitorTab === "overview") {
      const filtered = filterChecks(state.monitorChecks, state.monitorFilters);
      renderSummaryCards(filtered);
      renderFilterBar(state.monitorChecks);
      renderCheckList(filtered);
    }
  }

  function activate() {
    monitoringApi = null; // re-create with fresh session
    ensureApi();
    loadServers().then(() => loadMonitoring());
    startRefresh();
    switchMonitorTab(state.monitorTab || "overview");
  }

  function deactivate() {
    stopRefresh();
    destroyChart();
    expandedCheckId = null;
  }

  // ── Wire up tabs ───────────────────────────────────────────────────
  document.querySelectorAll(".mon-tab").forEach((tab) => {
    tab.addEventListener("click", () => switchMonitorTab(tab.dataset.tab));
  });

  return { loadMonitoring, activate, deactivate };
}
