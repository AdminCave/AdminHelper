<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import { t } from '$lib/i18n';
  import * as api from '$lib/api/monitoring';
  import {
    DEF_CPU_WARN,
    DEF_CPU_CRIT,
    DEF_MEM_WARN,
    DEF_MEM_CRIT,
    DEF_DISK_WARN,
    DEF_DISK_CRIT,
    DEF_TEMP_WARN,
    DEF_TEMP_CRIT,
    NO_CHART_TYPES,
    gaugeClass,
    checkTypeUnit,
    toCsv,
  } from '$lib/utils/monitoring';
  import type {
    MonitorCheck,
    MonitorResourceDetails,
    MonitorServiceDetails,
    MonitorContainerDetails,
    MonitorBackupDetails,
    MonitorZfsDetails,
    MonitorSmartDetails,
    MonitoringMetricsResponse,
  } from '$lib/api/types';
  import GaugeItem from './GaugeItem.svelte';
  import MetricsChart from './MetricsChart.svelte';

  interface Props {
    check: MonitorCheck;
  }

  let { check }: Props = $props();

  const config = $derived(check.config ?? {});

  // ── Config rendering (from _formatCheckConfigWeb) ──────────────────────
  const configKv = $derived.by(() => {
    const c = config;
    const tp = check.checkType;
    const kv: [string, string | number][] = [];
    if (tp === 'ping') {
      kv.push(
        [$t('monitor.cfg.target'), c.target ?? ''],
        [$t('monitor.cfg.timeout'), `${c.timeout ?? 5}s`],
      );
    } else if (tp === 'tcp') {
      kv.push(
        [$t('monitor.cfg.target'), `${c.target ?? ''}:${c.port ?? ''}`],
        [$t('monitor.cfg.timeout'), `${c.timeout ?? 5}s`],
      );
    } else if (tp === 'http') {
      kv.push(
        [$t('monitor.cfg.url'), c.url ?? ''],
        [$t('monitor.cfg.method'), c.method ?? 'GET'],
        [$t('monitor.cfg.expected'), c.expected_status ?? 200],
      );
      if (c.verify_ssl === false) kv.push([$t('monitor.cfg.ssl'), $t('monitor.cfg.sslDisabled')]);
      if (c.search_string) kv.push([$t('monitor.cfg.searchText'), c.search_string]);
    } else if (tp === 'agent_ping') {
      kv.push([
        $t('monitor.cfg.staleThreshold'),
        $t('monitor.cfg.staleMinutes', { min: c.stale_minutes ?? 5 }),
      ]);
    } else if (tp === 'agent_resources') {
      kv.push(
        [
          $t('monitor.cfg.cpu'),
          `Warn ${c.cpu_warn ?? DEF_CPU_WARN}% / Crit ${c.cpu_crit ?? DEF_CPU_CRIT}%`,
        ],
        [
          $t('monitor.cfg.ram'),
          `Warn ${c.memory_warn ?? DEF_MEM_WARN}% / Crit ${c.memory_crit ?? DEF_MEM_CRIT}%`,
        ],
        [
          $t('monitor.cfg.disk'),
          `Warn ${c.disk_warn ?? DEF_DISK_WARN}% / Crit ${c.disk_crit ?? DEF_DISK_CRIT}%`,
        ],
        [
          $t('monitor.cfg.temp'),
          `Warn ${c.temp_warn ?? DEF_TEMP_WARN}\u00b0C / Crit ${c.temp_crit ?? DEF_TEMP_CRIT}\u00b0C`,
        ],
      );
      if (c.temp_overrides) {
        for (const [sensor, ov] of Object.entries(c.temp_overrides)) {
          const parts: string[] = [];
          if (ov.warn != null) parts.push(`Warn ${ov.warn}\u00b0C`);
          if (ov.crit != null) parts.push(`Crit ${ov.crit}\u00b0C`);
          kv.push([sensor, parts.join(' / ')]);
        }
      }
    } else if (tp === 'service_process') {
      kv.push([$t('monitor.cfg.mode'), c.mode ?? 'auto']);
      if (c.services?.length) kv.push([$t('monitor.cfg.services'), toCsv(c.services)]);
      if (c.ignore?.length) kv.push([$t('monitor.cfg.ignored'), toCsv(c.ignore)]);
    } else if (tp === 'proxmox_backup') {
      kv.push([
        $t('monitor.cfg.maxAge'),
        $t('monitor.cfg.maxAgeHours', { hours: c.max_backup_age_hours ?? 26 }),
      ]);
      if (c.exclude_vmids?.length)
        kv.push([$t('monitor.cfg.excludeVmids'), toCsv(c.exclude_vmids)]);
    } else if (tp === 'zfs_health') {
      kv.push([
        $t('monitor.cfg.capacity'),
        `Warn ${c.capacity_warn ?? 80}% / Crit ${c.capacity_crit ?? 90}%`,
      ]);
    } else if (tp === 'docker_health') {
      if (c.ignore_containers?.length)
        kv.push([$t('monitor.cfg.ignored'), toCsv(c.ignore_containers)]);
      kv.push([
        $t('monitor.cfg.restartCheck'),
        c.check_restarts !== false ? $t('monitor.cfg.restartActive') : $t('monitor.cfg.restartOff'),
      ]);
    } else if (tp === 'smart_health') {
      kv.push(
        ['Realloc', `Warn ${c.reallocated_warn ?? 1} / Crit ${c.reallocated_crit ?? 10}`],
        ['Pending', `Warn ${c.pending_warn ?? 1} / Crit ${c.pending_crit ?? 5}`],
        ['NVMe Spare', `Warn <${c.nvme_spare_warn ?? 20}% / Crit <${c.nvme_spare_crit ?? 10}%`],
        ['NVMe Wear', `Warn ${c.nvme_used_warn ?? 90}% / Crit ${c.nvme_used_crit ?? 100}%`],
        ['Temp HDD', `Warn ${c.temp_hdd_warn ?? 55}\u00b0C / Crit ${c.temp_hdd_crit ?? 60}\u00b0C`],
        ['Temp SSD', `Warn ${c.temp_ssd_warn ?? 60}\u00b0C / Crit ${c.temp_ssd_crit ?? 70}\u00b0C`],
        [
          'Temp NVMe',
          `Warn ${c.temp_nvme_warn ?? 65}\u00b0C / Crit ${c.temp_nvme_crit ?? 75}\u00b0C`,
        ],
      );
      if (c.ignore_devices?.length) kv.push([$t('monitor.cfg.ignored'), toCsv(c.ignore_devices)]);
    }
    return kv;
  });

  // ── Type-content data (typed per checkType) ────────────────────────────
  const resourceDetails = $derived.by<MonitorResourceDetails | null>(() =>
    check.checkType === 'agent_resources'
      ? ((check.state?.details as MonitorResourceDetails) ?? null)
      : null,
  );
  const serviceDetails = $derived.by<MonitorServiceDetails | null>(() =>
    check.checkType === 'service_process'
      ? ((check.state?.details as MonitorServiceDetails) ?? null)
      : null,
  );
  const containerDetails = $derived.by<MonitorContainerDetails | null>(() =>
    check.checkType === 'docker_health'
      ? ((check.state?.details as MonitorContainerDetails) ?? null)
      : null,
  );
  const backupDetails = $derived.by<MonitorBackupDetails | null>(() =>
    check.checkType === 'proxmox_backup'
      ? ((check.state?.details as MonitorBackupDetails) ?? null)
      : null,
  );
  const zfsDetails = $derived.by<MonitorZfsDetails | null>(() =>
    check.checkType === 'zfs_health' ? ((check.state?.details as MonitorZfsDetails) ?? null) : null,
  );
  const smartDetails = $derived.by<MonitorSmartDetails | null>(() =>
    check.checkType === 'smart_health'
      ? ((check.state?.details as MonitorSmartDetails) ?? null)
      : null,
  );

  // ── Gauge-Click-On-Demand-Chart ────────────────────────────────────────
  let activeMetric = $state<string | null>(null);
  let activeDiskMount = $state<string | null>(null);
  let gaugePeriod = $state<'1h' | '6h' | '24h' | '7d'>('1h');
  let gaugeData = $state<MonitoringMetricsResponse | null>(null);
  let gaugeLoading = $state(false);
  let gaugeError = $state<string | null>(null);

  function gaugeKey(metric: string, mount?: string | null): string {
    return metric + (mount ?? '');
  }

  async function clickGauge(metric: string, mount?: string | null): Promise<void> {
    const key = gaugeKey(metric, mount);
    const currentKey = activeMetric ? gaugeKey(activeMetric, activeDiskMount) : null;
    if (currentKey === key) {
      activeMetric = null;
      activeDiskMount = null;
      gaugeData = null;
      return;
    }
    activeMetric = metric;
    activeDiskMount = mount ?? null;
    gaugePeriod = '1h';
    await loadGauge(metric, mount ?? null, '1h');
  }

  async function loadGauge(
    metric: string,
    mount: string | null,
    period: '1h' | '6h' | '24h' | '7d',
  ): Promise<void> {
    gaugeLoading = true;
    gaugeError = null;
    try {
      const data = await api.checkMetrics(check.id, period);
      const all = data.data ?? [];
      const filtered = all.filter((s) => {
        const name = s.metric?.__name__ ?? '';
        if (metric === 'monitor_agent_disk_percent') {
          if (!name.startsWith('monitor_agent_disk_percent')) return false;
          if (name.includes('cpu') || name.includes('memory')) return false;
          const m = s.metric?.mount ?? '';
          return m ? m === mount : name.includes(mount ?? '/');
        }
        return name === metric || name === metric + '_value';
      });
      gaugeData = { data: filtered };
    } catch (err) {
      gaugeError = err instanceof Error ? err.message : 'Fehler';
      gaugeData = null;
    } finally {
      gaugeLoading = false;
    }
  }

  async function setGaugePeriod(p: '1h' | '6h' | '24h' | '7d'): Promise<void> {
    gaugePeriod = p;
    if (activeMetric) await loadGauge(activeMetric, activeDiskMount, p);
  }

  // ── Main-Chart (Whole-Check) ───────────────────────────────────────────
  const skipChart = $derived(
    NO_CHART_TYPES.includes(check.checkType) ||
      (check.checkType === 'agent_resources' && !!check.state?.details),
  );

  let mainPeriod = $state<'1h' | '6h' | '24h' | '7d'>('1h');
  let mainData = $state<MonitoringMetricsResponse | null>(null);
  let mainLoading = $state(false);
  let mainError = $state<string | null>(null);

  async function loadMain(period: '1h' | '6h' | '24h' | '7d'): Promise<void> {
    mainLoading = true;
    mainError = null;
    try {
      mainData = await api.checkMetrics(check.id, period);
    } catch (err) {
      mainError = err instanceof Error ? err.message : 'Fehler';
      mainData = null;
    } finally {
      mainLoading = false;
    }
  }

  async function setMainPeriod(p: '1h' | '6h' | '24h' | '7d'): Promise<void> {
    mainPeriod = p;
    await loadMain(p);
  }

  $effect(() => {
    if (!skipChart) {
      void loadMain(mainPeriod);
    }
  });

  // ── Current values (next to period tabs) ───────────────────────────────
  const currentValues = $derived.by(() => {
    if (skipChart || !mainData) return [] as { label: string; text: string }[];
    const series = mainData.data ?? [];
    const out: { label: string; text: string }[] = [];
    for (const s of series) {
      const name = s.metric?.__name__ ?? $t('monitor.value');
      const vals = s.values;
      if (!vals.length) continue;
      const last = parseFloat(vals[vals.length - 1][1]);
      if (isNaN(last)) continue;
      const isTemp = name.includes('agent_temp');
      const unit = isTemp ? ' \u00b0C' : checkTypeUnit(check.checkType);
      const label = name
        .replace(/^monitor_/, '')
        .replace(/_value$/, '')
        .replace(/_/g, ' ');
      out.push({ label, text: `${last.toFixed(1)}${unit}` });
    }
    return out;
  });

  // ── Status-Timeline ────────────────────────────────────────────────────
  const STATUS_MAP: Record<number, 'ok' | 'warning' | 'critical' | 'unknown' | 'pending'> = {
    0: 'ok',
    1: 'warning',
    2: 'critical',
    3: 'unknown',
    4: 'pending',
  };
  const COLOR_MAP: Record<string, string> = {
    ok: 'var(--green)',
    warning: 'var(--yellow)',
    critical: 'var(--red)',
    unknown: 'var(--text-muted)',
    pending: '#666',
  };

  const timelineSegments = $derived.by(() => {
    if (!mainData) return [] as { pct: number; color: string; status: string }[];
    const result = (mainData.statusHistory ?? [])[0];
    if (!result || result.values.length < 2) return [];
    const values = result.values;
    const totalTime = values[values.length - 1][0] - values[0][0];
    if (totalTime <= 0) return [];
    const segs: { pct: number; color: string; status: string }[] = [];
    for (let i = 0; i < values.length - 1; i++) {
      const status = STATUS_MAP[parseInt(values[i][1])] ?? 'unknown';
      const duration = values[i + 1][0] - values[i][0];
      segs.push({
        pct: (duration / totalTime) * 100,
        color: COLOR_MAP[status],
        status,
      });
    }
    return segs;
  });

  // ── Extract agent_ping seconds ─────────────────────────────────────────
  const pingSeconds = $derived.by(() => {
    if (check.checkType !== 'agent_ping') return null;
    const msg = check.state?.message ?? '';
    const m = msg.match(/(\d+)/);
    if (!m) return null;
    return parseInt(m[1], 10);
  });

  function pingDisplay(seconds: number): string {
    return seconds < 120 ? `${seconds}s` : `${Math.round(seconds / 60)}m`;
  }
</script>

<div class="check-detail-panel">
  {#if configKv.length > 0}
    <div class="check-detail-config">
      <strong>{$t('monitor.config')}</strong>
      <div class="check-cfg-grid">
        {#each configKv as [k, v] (k)}
          <span class="check-cfg-key">{k}:</span>
          <span class="check-cfg-val">{v}</span>
        {/each}
      </div>
    </div>
  {/if}

  <!-- Type-Specific Content -->
  {#if check.checkType === 'agent_resources' && resourceDetails}
    {@const cfg = config}
    {@const cpuW = cfg.cpu_warn ?? DEF_CPU_WARN}
    {@const cpuC = cfg.cpu_crit ?? DEF_CPU_CRIT}
    {@const memW = cfg.memory_warn ?? DEF_MEM_WARN}
    {@const memC = cfg.memory_crit ?? DEF_MEM_CRIT}
    {@const diskW = cfg.disk_warn ?? DEF_DISK_WARN}
    {@const diskC = cfg.disk_crit ?? DEF_DISK_CRIT}
    {@const tempW = cfg.temp_warn ?? DEF_TEMP_WARN}
    {@const tempC = cfg.temp_crit ?? DEF_TEMP_CRIT}
    {@const tempOv = cfg.temp_overrides ?? {}}
    <div class="mon-gauge-grid">
      {#if resourceDetails.cpu != null}
        <GaugeItem
          label="CPU"
          value={resourceDetails.cpu}
          cls={gaugeClass(resourceDetails.cpu, cpuW, cpuC)}
          metric="monitor_agent_cpu_percent"
          active={activeMetric === 'monitor_agent_cpu_percent'}
          onClick={() => clickGauge('monitor_agent_cpu_percent')}
        />
      {/if}
      {#if resourceDetails.memory != null}
        {@const memDetail = resourceDetails.memory_total_mb
          ? `${resourceDetails.memory_used_mb ?? 0} / ${resourceDetails.memory_total_mb} MB`
          : null}
        <GaugeItem
          label="RAM"
          value={resourceDetails.memory}
          detail={memDetail}
          cls={gaugeClass(resourceDetails.memory, memW, memC)}
          metric="monitor_agent_memory_percent"
          active={activeMetric === 'monitor_agent_memory_percent'}
          onClick={() => clickGauge('monitor_agent_memory_percent')}
        />
      {/if}
      {#each resourceDetails.disks ?? [] as disk (disk.mount)}
        {@const dDetail =
          disk.total_gb != null
            ? `${(disk.used_gb ?? 0).toFixed(1)} / ${disk.total_gb.toFixed(1)} GB`
            : null}
        <GaugeItem
          label={disk.mount}
          value={disk.percent}
          detail={dDetail}
          cls={gaugeClass(disk.percent, diskW, diskC)}
          metric="monitor_agent_disk_percent"
          active={activeMetric === 'monitor_agent_disk_percent' && activeDiskMount === disk.mount}
          onClick={() => clickGauge('monitor_agent_disk_percent', disk.mount)}
        />
      {/each}
      {#each resourceDetails.temperatures ?? [] as sensor (sensor.sensor)}
        {@const ov = tempOv[sensor.sensor] ?? {}}
        {@const sW = ov.warn ?? tempW}
        {@const sC = ov.crit ?? tempC}
        {@const hwInfo =
          [
            sensor.high > 0 ? `High: ${sensor.high}\u00b0C` : null,
            sensor.critical > 0 ? `Crit: ${sensor.critical}\u00b0C` : null,
          ]
            .filter(Boolean)
            .join(', ') || null}
        <GaugeItem
          label={sensor.sensor}
          value={sensor.temp_c}
          detail={hwInfo}
          unit="&deg;C"
          cls={gaugeClass(sensor.temp_c, sW, sC)}
          metric="monitor_agent_temp"
          active={activeMetric === 'monitor_agent_temp'}
          onClick={() => clickGauge('monitor_agent_temp')}
        />
      {/each}
    </div>
    {#if activeMetric}
      <div class="mon-gauge-chart-area">
        <div class="check-detail-periods">
          {#each ['1h', '6h', '24h', '7d'] as p (p)}
            <button
              class="btn small"
              class:active={gaugePeriod === p}
              onclick={() => setGaugePeriod(p as '1h' | '6h' | '24h' | '7d')}>{p}</button
            >
          {/each}
        </div>
        <div class="check-detail-chart">
          <MetricsChart
            data={gaugeData}
            checkType={check.checkType}
            loading={gaugeLoading}
            error={gaugeError}
          />
        </div>
      </div>
    {/if}
  {:else if check.checkType === 'service_process' && serviceDetails}
    {#if serviceDetails.mode === 'auto'}
      {@const failed = serviceDetails.failed ?? []}
      {@const inactive = serviceDetails.enabled_inactive ?? []}
      {#if failed.length === 0 && inactive.length === 0}
        <div class="mon-all-ok">
          <span class="mon-item-dot item-ok"></span>
          {$t('monitor.allUnitsOk')}
        </div>
      {:else}
        <div class="mon-item-list">
          {#if failed.length > 0}
            <div class="mon-section-title">Failed</div>
            {#each failed as svc (svc)}
              <div class="mon-item-row">
                <span class="mon-item-dot item-crit"></span>
                <span class="mon-item-name">{svc}</span>
                <span class="mon-item-status">failed</span>
              </div>
            {/each}
          {/if}
          {#if inactive.length > 0}
            <div class="mon-section-title">{$t('monitor.sectionInactive')}</div>
            {#each inactive as svc (svc)}
              <div class="mon-item-row">
                <span class="mon-item-dot item-warn"></span>
                <span class="mon-item-name">{svc}</span>
                <span class="mon-item-status">inactive</span>
              </div>
            {/each}
          {/if}
        </div>
      {/if}
    {:else if (serviceDetails.watched ?? []).length > 0}
      <div class="mon-item-list">
        {#each serviceDetails.watched ?? [] as svc (svc.name)}
          <div class="mon-item-row">
            <span class="mon-item-dot {svc.running ? 'item-ok' : 'item-crit'}"></span>
            <span class="mon-item-name">{svc.name}</span>
            <span class="mon-item-status">{svc.running ? 'running' : 'down'}</span>
          </div>
        {/each}
      </div>
    {/if}
  {:else if check.checkType === 'docker_health' && containerDetails?.containers?.length}
    {@const allOk = containerDetails.containers.every((c) => c.category === 'ok')}
    {#if allOk}
      <div class="mon-all-ok">
        <span class="mon-item-dot item-ok"></span>
        {$t('monitor.allContainersRunning', { count: containerDetails.containers.length })}
      </div>
    {:else}
      {@const orderMap = { critical: 0, warning: 1, ok: 2 } as const}
      {@const sorted = [...containerDetails.containers].sort(
        (a, b) => (orderMap[a.category] ?? 2) - (orderMap[b.category] ?? 2),
      )}
      <div class="mon-item-list">
        {#each sorted as c (c.name)}
          {@const dotCls =
            c.category === 'critical'
              ? 'item-crit'
              : c.category === 'warning'
                ? 'item-warn'
                : 'item-ok'}
          {@const imgBadge = c.image ? c.image.split(':')[0].split('/').pop() : null}
          <div class="mon-item-row">
            <span class="mon-item-dot {dotCls}"></span>
            <span class="mon-item-name">{c.name}</span>
            {#if imgBadge}
              <span class="mon-item-badge">{imgBadge}</span>
            {/if}
            <span class="mon-item-status">{c.state}</span>
          </div>
        {/each}
      </div>
    {/if}
  {:else if check.checkType === 'proxmox_backup' && backupDetails?.vms?.length}
    {@const allOk = backupDetails.vms.every((v) => v.backupStatus === 'ok')}
    {#if allOk}
      <div class="mon-all-ok">
        <span class="mon-item-dot item-ok"></span>
        {$t('monitor.allBackupsOk', { count: backupDetails.vms.length })}
      </div>
    {:else}
      {@const orderMap = { missing: 0, outdated: 1, ok: 2 } as const}
      {@const sorted = [...backupDetails.vms].sort(
        (a, b) => (orderMap[a.backupStatus] ?? 2) - (orderMap[b.backupStatus] ?? 2),
      )}
      <div class="mon-item-list">
        {#each sorted as vm (vm.vmid)}
          {@const dotCls =
            vm.backupStatus === 'missing'
              ? 'item-crit'
              : vm.backupStatus === 'outdated'
                ? 'item-warn'
                : 'item-ok'}
          {@const statusText =
            vm.backupStatus === 'ok'
              ? 'OK'
              : vm.backupStatus === 'missing'
                ? $t('monitor.noBackup')
                : $t('monitor.outdated', { hours: vm.ageHours ?? 0 })}
          <div class="mon-item-row">
            <span class="mon-item-dot {dotCls}"></span>
            <span class="mon-item-badge">{(vm.type ?? 'vm').toUpperCase()}</span>
            <span class="mon-item-name">{vm.name} ({vm.vmid})</span>
            <span class="mon-item-status">{statusText}</span>
          </div>
        {/each}
      </div>
    {/if}
  {:else if check.checkType === 'zfs_health' && zfsDetails?.pools?.length}
    <div class="mon-gauge-grid">
      {#each zfsDetails.pools as pool (pool.name)}
        {@const healthCls =
          pool.health === 'ONLINE'
            ? 'health-online'
            : pool.health === 'DEGRADED'
              ? 'health-degraded'
              : 'health-faulted'}
        <div class="mon-gauge-item">
          <span class="mon-gauge-label">{pool.name}</span>
          <div class="mon-gauge-bar">
            <div
              class="mon-gauge-fill {gaugeClass(pool.capacityPercent, 80, 90)}"
              style="width:{Math.min(pool.capacityPercent, 100)}%"
            ></div>
            <span class="mon-gauge-text">{pool.capacityPercent}%</span>
          </div>
          <span class="mon-health-badge {healthCls}">{pool.health}</span>
        </div>
      {/each}
    </div>
  {:else if check.checkType === 'smart_health' && smartDetails?.disks?.length}
    <div class="mon-gauge-grid">
      {#each smartDetails.disks as disk (disk.device)}
        {@const cat = disk.category ?? 'ok'}
        {@const badgeCls =
          cat === 'critical'
            ? 'health-faulted'
            : cat === 'warning'
              ? 'health-degraded'
              : 'health-online'}
        {@const badgeText = cat === 'critical' ? 'CRIT' : cat === 'warning' ? 'WARN' : 'OK'}
        {@const temp = Number(disk.temp_c) || 0}
        {@const tempWarn = Number(disk.temp_warn) || 60}
        {@const tempCrit = Number(disk.temp_crit) || 70}
        {@const tempPct = Math.min((temp / tempCrit) * 100, 100)}
        {@const tempCls = gaugeClass(temp, tempWarn, tempCrit)}
        {@const hours = Number(disk.power_on_hours) || 0}
        {@const hoursStr = hours > 0 ? `${hours.toLocaleString('de-DE')} h` : null}
        {@const secondary = (() => {
          const parts: string[] = [];
          if (disk.kind === 'NVMe') {
            if (disk.available_spare_pct != null) parts.push(`Spare ${disk.available_spare_pct}%`);
            if (disk.percentage_used != null) parts.push(`Wear ${disk.percentage_used}%`);
          } else {
            const realloc = Number(disk.reallocated_sectors) || 0;
            const pending = Number(disk.pending_sectors) || 0;
            if (realloc > 0) parts.push(`Realloc ${realloc}`);
            if (pending > 0) parts.push(`Pending ${pending}`);
          }
          if (hoursStr) parts.push(hoursStr);
          return parts.join(' | ');
        })()}
        <div class="mon-gauge-item">
          <span class="mon-gauge-label">{disk.device} [{disk.kind ?? disk.protocol ?? 'Disk'}]</span
          >
          <div class="mon-gauge-bar">
            <div class="mon-gauge-fill {tempCls}" style="width:{tempPct}%"></div>
            <span class="mon-gauge-text">{temp}&deg;C</span>
          </div>
          <span class="mon-gauge-detail">{disk.model ?? ''}</span>
          {#if secondary}
            <span class="mon-gauge-detail">{secondary}</span>
          {/if}
          {#if disk.critical_warning_bits?.length}
            <span class="mon-gauge-detail" style="color:var(--status-crit)">
              {disk.critical_warning_bits.join(', ')}
            </span>
          {/if}
          <span class="mon-health-badge {badgeCls}">{badgeText}</span>
        </div>
      {/each}
    </div>
  {:else if check.checkType === 'agent_ping' && pingSeconds != null}
    <div class="mon-last-seen">
      <span class="mon-last-seen-value">{pingDisplay(pingSeconds)}</span>
      <span class="mon-last-seen-unit">{$t('monitor.sinceLastReport')}</span>
    </div>
  {/if}

  {#if !skipChart}
    {#if currentValues.length > 0}
      <div class="check-detail-current">
        {#each currentValues as item, i (i)}
          <span class="check-current-item"><strong>{item.label}</strong>: {item.text}</span>
        {/each}
      </div>
    {/if}
    <div class="check-detail-periods">
      {#each ['1h', '6h', '24h', '7d'] as p (p)}
        <button
          class="btn small"
          class:active={mainPeriod === p}
          onclick={() => setMainPeriod(p as '1h' | '6h' | '24h' | '7d')}>{p}</button
        >
      {/each}
    </div>
    <div class="check-detail-chart">
      <MetricsChart
        data={mainData}
        checkType={check.checkType}
        loading={mainLoading}
        error={mainError}
      />
    </div>
    {#if timelineSegments.length > 0}
      <div class="check-detail-timeline-label">{$t('monitor.statusHistory')}</div>
      <div class="check-timeline-bar">
        {#each timelineSegments as seg, i (i)}
          <div
            class="check-timeline-seg"
            style="width:{seg.pct}%;background:{seg.color}"
            title={seg.status}
          ></div>
        {/each}
      </div>
    {/if}
  {/if}
</div>
