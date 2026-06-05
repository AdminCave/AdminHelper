<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import Modal from '$lib/components/ui/Modal.svelte';
  import Button from '$lib/components/ui/Button.svelte';
  import { t } from '$lib/i18n';
  import { monitorChecks } from '$lib/stores/monitoring';
  import { servers as serversStore } from '$lib/stores/servers';
  import { showToast } from '$lib/stores/notifications';
  import {
    DEF_CPU_WARN,
    DEF_CPU_CRIT,
    DEF_MEM_WARN,
    DEF_MEM_CRIT,
    DEF_DISK_WARN,
    DEF_DISK_CRIT,
    DEF_TEMP_WARN,
    DEF_TEMP_CRIT,
    TEMP_GAUGE_MAX,
    parseCsv,
    parseIntCsv,
    toCsv,
  } from '$lib/utils/monitoring';
  import type {
    MonitorCheck,
    MonitorCheckConfig,
    MonitorCheckInput,
    MonitorCheckType,
    MonitorInterval,
    MonitorResourceDetails,
    MonitorSeverity,
  } from '$lib/api/types';

  interface Props {
    open: boolean;
    editing: MonitorCheck | null;
    onClose: () => void;
  }

  let { open, editing, onClose }: Props = $props();

  let name = $state('');
  let serverId = $state('');
  let checkType = $state<MonitorCheckType>('ping');
  let interval = $state<MonitorInterval>('5m');
  let severity = $state<MonitorSeverity>('critical');
  let consecutiveFails = $state(3);
  let description = $state('');

  // Individual config fields per type
  let pingTarget = $state('');
  let pingTimeout = $state(5);

  let tcpTarget = $state('');
  let tcpPort = $state<number | ''>('');
  let tcpTimeout = $state(5);

  let httpUrl = $state('');
  let httpMethod = $state('GET');
  let httpStatus = $state(200);
  let httpTimeout = $state(10);
  let httpVerifySsl = $state(true);
  let httpSearch = $state('');

  let agentPingStale = $state(5);

  let cpuWarn = $state(DEF_CPU_WARN);
  let cpuCrit = $state(DEF_CPU_CRIT);
  let memWarn = $state(DEF_MEM_WARN);
  let memCrit = $state(DEF_MEM_CRIT);
  let diskWarn = $state(DEF_DISK_WARN);
  let diskCrit = $state(DEF_DISK_CRIT);
  let tempWarn = $state(DEF_TEMP_WARN);
  let tempCrit = $state(DEF_TEMP_CRIT);
  let tempOverrides = $state<Record<string, { warn?: number | ''; crit?: number | '' }>>({});

  let svcMode = $state<'auto' | 'list'>('list');
  let svcNames = $state('');
  let svcIgnore = $state('');

  let pveMaxAge = $state(26);
  let pveExclude = $state('');
  let pveExcludeStopped = $state(true);

  let zfsCapWarn = $state(80);
  let zfsCapCrit = $state(90);

  let dockerIgnore = $state('');

  let smartReallocWarn = $state(1);
  let smartReallocCrit = $state(10);
  let smartPendingWarn = $state(1);
  let smartPendingCrit = $state(5);
  let smartNvmeSpareWarn = $state(20);
  let smartNvmeSpareCrit = $state(10);
  let smartNvmeUsedWarn = $state(90);
  let smartNvmeUsedCrit = $state(100);
  let smartTempHddWarn = $state(55);
  let smartTempHddCrit = $state(60);
  let smartTempSsdWarn = $state(60);
  let smartTempSsdCrit = $state(70);
  let smartTempNvmeWarn = $state(65);
  let smartTempNvmeCrit = $state(75);
  let smartIgnore = $state('');

  let sensorList = $state<{ sensor: string; temp_c: number }[]>([]);
  let submitting = $state(false);

  $effect(() => {
    if (!open) return;
    name = editing?.name ?? '';
    serverId = editing?.serverId ?? '';
    checkType = editing?.checkType ?? 'ping';
    interval = editing?.interval ?? '5m';
    severity = editing?.severity ?? 'critical';
    consecutiveFails = editing?.consecutiveFails ?? 3;
    description = editing?.description ?? '';

    const cfg: MonitorCheckConfig = editing?.config ?? {};
    pingTarget = (cfg.target as string) ?? '';
    pingTimeout = (cfg.timeout as number) ?? 5;
    tcpTarget = (cfg.target as string) ?? '';
    tcpPort = (cfg.port as number) ?? '';
    tcpTimeout = (cfg.timeout as number) ?? 5;
    httpUrl = cfg.url ?? '';
    httpMethod = cfg.method ?? 'GET';
    httpStatus = cfg.expected_status ?? 200;
    httpTimeout = cfg.timeout ?? 10;
    httpVerifySsl = cfg.verify_ssl !== false;
    httpSearch = cfg.search_string ?? '';
    agentPingStale = cfg.stale_minutes ?? 5;
    cpuWarn = cfg.cpu_warn ?? DEF_CPU_WARN;
    cpuCrit = cfg.cpu_crit ?? DEF_CPU_CRIT;
    memWarn = cfg.memory_warn ?? DEF_MEM_WARN;
    memCrit = cfg.memory_crit ?? DEF_MEM_CRIT;
    diskWarn = cfg.disk_warn ?? DEF_DISK_WARN;
    diskCrit = cfg.disk_crit ?? DEF_DISK_CRIT;
    tempWarn = cfg.temp_warn ?? DEF_TEMP_WARN;
    tempCrit = cfg.temp_crit ?? DEF_TEMP_CRIT;
    const ov = cfg.temp_overrides ?? {};
    tempOverrides = Object.fromEntries(
      Object.entries(ov).map(([k, v]) => [k, { warn: v.warn ?? '', crit: v.crit ?? '' }]),
    );

    const details = editing?.state?.details as MonitorResourceDetails | undefined;
    sensorList = (details?.temperatures ?? []).map((s) => ({ sensor: s.sensor, temp_c: s.temp_c }));

    svcMode = (cfg.mode as 'auto' | 'list') ?? 'list';
    svcNames = toCsv(cfg.services);
    svcIgnore = toCsv(cfg.ignore);

    pveMaxAge = cfg.max_backup_age_hours ?? 26;
    pveExclude = toCsv(cfg.exclude_vmids);
    pveExcludeStopped = cfg.exclude_stopped !== false;

    zfsCapWarn = cfg.capacity_warn ?? 80;
    zfsCapCrit = cfg.capacity_crit ?? 90;

    dockerIgnore = toCsv(cfg.ignore_containers);

    smartReallocWarn = cfg.reallocated_warn ?? 1;
    smartReallocCrit = cfg.reallocated_crit ?? 10;
    smartPendingWarn = cfg.pending_warn ?? 1;
    smartPendingCrit = cfg.pending_crit ?? 5;
    smartNvmeSpareWarn = cfg.nvme_spare_warn ?? 20;
    smartNvmeSpareCrit = cfg.nvme_spare_crit ?? 10;
    smartNvmeUsedWarn = cfg.nvme_used_warn ?? 90;
    smartNvmeUsedCrit = cfg.nvme_used_crit ?? 100;
    smartTempHddWarn = cfg.temp_hdd_warn ?? 55;
    smartTempHddCrit = cfg.temp_hdd_crit ?? 60;
    smartTempSsdWarn = cfg.temp_ssd_warn ?? 60;
    smartTempSsdCrit = cfg.temp_ssd_crit ?? 70;
    smartTempNvmeWarn = cfg.temp_nvme_warn ?? 65;
    smartTempNvmeCrit = cfg.temp_nvme_crit ?? 75;
    smartIgnore = Array.isArray(cfg.ignore_devices) ? cfg.ignore_devices.join('\n') : '';
  });

  function buildConfig(): MonitorCheckConfig {
    switch (checkType) {
      case 'ping':
        return { target: pingTarget.trim(), timeout: pingTimeout || 5 };
      case 'tcp':
        return {
          target: tcpTarget.trim(),
          port: Number(tcpPort) || 0,
          timeout: tcpTimeout || 5,
        };
      case 'http': {
        const cfg: MonitorCheckConfig = {
          url: httpUrl.trim(),
          method: httpMethod,
          expected_status: httpStatus || 200,
          timeout: httpTimeout || 10,
          verify_ssl: httpVerifySsl,
        };
        const s = httpSearch.trim();
        if (s) cfg.search_string = s;
        return cfg;
      }
      case 'agent_ping':
        return { stale_minutes: agentPingStale || 5 };
      case 'agent_resources': {
        const cfg: MonitorCheckConfig = {
          cpu_warn: cpuWarn || DEF_CPU_WARN,
          cpu_crit: cpuCrit || DEF_CPU_CRIT,
          memory_warn: memWarn || DEF_MEM_WARN,
          memory_crit: memCrit || DEF_MEM_CRIT,
          disk_warn: diskWarn || DEF_DISK_WARN,
          disk_crit: diskCrit || DEF_DISK_CRIT,
          temp_warn: tempWarn || DEF_TEMP_WARN,
          temp_crit: tempCrit || DEF_TEMP_CRIT,
        };
        const outOv: Record<string, { warn?: number; crit?: number }> = {};
        for (const [sensor, v] of Object.entries(tempOverrides)) {
          const entry: { warn?: number; crit?: number } = {};
          if (v.warn !== '' && v.warn != null) entry.warn = Number(v.warn);
          if (v.crit !== '' && v.crit != null) entry.crit = Number(v.crit);
          if (entry.warn != null || entry.crit != null) outOv[sensor] = entry;
        }
        if (Object.keys(outOv).length > 0) cfg.temp_overrides = outOv;
        return cfg;
      }
      case 'service_process':
        return svcMode === 'auto'
          ? { mode: 'auto', ignore: parseCsv(svcIgnore) }
          : { mode: 'list', services: parseCsv(svcNames) };
      case 'proxmox_backup':
        return {
          max_backup_age_hours: pveMaxAge || 26,
          exclude_vmids: parseIntCsv(pveExclude),
          exclude_stopped: pveExcludeStopped,
        };
      case 'zfs_health':
        return { capacity_warn: zfsCapWarn || 80, capacity_crit: zfsCapCrit || 90 };
      case 'docker_health':
        return { ignore_containers: parseCsv(dockerIgnore) };
      case 'smart_health':
        return {
          reallocated_warn: smartReallocWarn || 1,
          reallocated_crit: smartReallocCrit || 10,
          pending_warn: smartPendingWarn || 1,
          pending_crit: smartPendingCrit || 5,
          nvme_spare_warn: smartNvmeSpareWarn || 20,
          nvme_spare_crit: smartNvmeSpareCrit || 10,
          nvme_used_warn: smartNvmeUsedWarn || 90,
          nvme_used_crit: smartNvmeUsedCrit || 100,
          temp_hdd_warn: smartTempHddWarn || 55,
          temp_hdd_crit: smartTempHddCrit || 60,
          temp_ssd_warn: smartTempSsdWarn || 60,
          temp_ssd_crit: smartTempSsdCrit || 70,
          temp_nvme_warn: smartTempNvmeWarn || 65,
          temp_nvme_crit: smartTempNvmeCrit || 75,
          ignore_devices: smartIgnore
            .split('\n')
            .map((s) => s.trim())
            .filter(Boolean),
        };
    }
  }

  async function onSubmit(e: SubmitEvent) {
    e.preventDefault();
    submitting = true;
    try {
      const data: MonitorCheckInput = {
        name: name.trim(),
        server_id: serverId || null,
        check_type: checkType,
        interval,
        severity,
        consecutive_fails: consecutiveFails || 3,
        description: description.trim() || null,
        config: buildConfig(),
      };
      if (editing) {
        await monitorChecks.update(editing.id, data);
        showToast($t('toast.check.saved'));
      } else {
        await monitorChecks.create(data);
        showToast($t('toast.check.created'));
      }
      onClose();
    } catch (err) {
      showToast(err instanceof Error ? err.message : 'Fehler', 'error');
    } finally {
      submitting = false;
    }
  }
</script>

<Modal
  {open}
  title={editing ? $t('modal.check.title') : $t('modal.check.titleNew')}
  width="780px"
  {onClose}
>
  <form class="modal-form" onsubmit={onSubmit} id="monitor-check-form">
    <div class="field full">
      <label for="mcName">{$t('label.name')} *</label>
      <input id="mcName" required bind:value={name} />
    </div>
    <div class="field">
      <label for="mcServer">Server</label>
      <select id="mcServer" bind:value={serverId}>
        <option value="">{$t('modal.check.noServer')}</option>
        {#each $serversStore as s (s.id)}
          <option value={s.id}>{s.name}</option>
        {/each}
      </select>
    </div>
    <div class="field">
      <label for="mcType">{$t('label.type')} *</label>
      <select id="mcType" bind:value={checkType}>
        <option value="ping">ping</option>
        <option value="tcp">tcp</option>
        <option value="http">http</option>
        <option value="agent_ping">agent_ping</option>
        <option value="agent_resources">agent_resources</option>
        <option value="service_process">service_process</option>
        <option value="proxmox_backup">proxmox_backup</option>
        <option value="zfs_health">zfs_health</option>
        <option value="docker_health">docker_health</option>
        <option value="smart_health">smart_health</option>
      </select>
    </div>
    <div class="field">
      <label for="mcInterval">{$t('modal.check.interval')}</label>
      <select id="mcInterval" bind:value={interval}>
        {#each ['1m', '5m', '15m', '30m', '1h', '6h', '12h', '24h'] as v (v)}
          <option value={v}>{v}</option>
        {/each}
      </select>
    </div>
    <div class="field">
      <label for="mcSeverity">Severity</label>
      <select id="mcSeverity" bind:value={severity}>
        <option value="critical">critical</option>
        <option value="warning">warning</option>
        <option value="info">info</option>
      </select>
    </div>
    <div class="field">
      <label for="mcFails">{$t('modal.check.consecutiveFails')}</label>
      <input id="mcFails" type="number" min="1" bind:value={consecutiveFails} />
    </div>
    <div class="field full">
      <label for="mcDesc">{$t('label.description')}</label>
      <input id="mcDesc" bind:value={description} />
    </div>

    {#if checkType === 'ping'}
      <div class="field">
        <label for="mcPingTarget">{$t('monitor.cfg.target')} *</label>
        <input id="mcPingTarget" required bind:value={pingTarget} />
      </div>
      <div class="field">
        <label for="mcPingTimeout">Timeout (s)</label>
        <input id="mcPingTimeout" type="number" bind:value={pingTimeout} />
      </div>
    {:else if checkType === 'tcp'}
      <div class="field">
        <label for="mcTcpTarget">{$t('monitor.cfg.target')} *</label>
        <input id="mcTcpTarget" required bind:value={tcpTarget} />
      </div>
      <div class="field">
        <label for="mcTcpPort">Port *</label>
        <input id="mcTcpPort" type="number" required bind:value={tcpPort} />
      </div>
      <div class="field">
        <label for="mcTcpTimeout">Timeout (s)</label>
        <input id="mcTcpTimeout" type="number" bind:value={tcpTimeout} />
      </div>
    {:else if checkType === 'http'}
      <div class="field full">
        <label for="mcHttpUrl">URL *</label>
        <input id="mcHttpUrl" required bind:value={httpUrl} />
      </div>
      <div class="field">
        <label for="mcHttpMethod">{$t('monitor.cfg.method')}</label>
        <select id="mcHttpMethod" bind:value={httpMethod}>
          <option value="GET">GET</option>
          <option value="POST">POST</option>
          <option value="PUT">PUT</option>
          <option value="HEAD">HEAD</option>
        </select>
      </div>
      <div class="field">
        <label for="mcHttpStatus">{$t('monitor.cfg.expected')}</label>
        <input id="mcHttpStatus" type="number" bind:value={httpStatus} />
      </div>
      <div class="field">
        <label for="mcHttpTimeout">Timeout (s)</label>
        <input id="mcHttpTimeout" type="number" bind:value={httpTimeout} />
      </div>
      <div class="field">
        <label for="mcHttpSsl">{$t('monitor.cfg.ssl')}</label>
        <select id="mcHttpSsl" bind:value={httpVerifySsl}>
          <option value={true}>{$t('action.yes')}</option>
          <option value={false}>{$t('action.no')}</option>
        </select>
      </div>
      <div class="field full">
        <label for="mcHttpSearch">{$t('monitor.cfg.searchText')}</label>
        <input id="mcHttpSearch" bind:value={httpSearch} />
      </div>
    {:else if checkType === 'agent_ping'}
      <div class="field">
        <label for="mcAgentStale">{$t('monitor.cfg.staleThreshold')} (min)</label>
        <input id="mcAgentStale" type="number" bind:value={agentPingStale} />
      </div>
    {:else if checkType === 'agent_resources'}
      <div class="field">
        <label for="mcCpuWarn">CPU Warn %</label>
        <input id="mcCpuWarn" type="number" bind:value={cpuWarn} />
      </div>
      <div class="field">
        <label for="mcCpuCrit">CPU Crit %</label>
        <input id="mcCpuCrit" type="number" bind:value={cpuCrit} />
      </div>
      <div class="field">
        <label for="mcMemWarn">RAM Warn %</label>
        <input id="mcMemWarn" type="number" bind:value={memWarn} />
      </div>
      <div class="field">
        <label for="mcMemCrit">RAM Crit %</label>
        <input id="mcMemCrit" type="number" bind:value={memCrit} />
      </div>
      <div class="field">
        <label for="mcDiskWarn">Disk Warn %</label>
        <input id="mcDiskWarn" type="number" bind:value={diskWarn} />
      </div>
      <div class="field">
        <label for="mcDiskCrit">Disk Crit %</label>
        <input id="mcDiskCrit" type="number" bind:value={diskCrit} />
      </div>
      <div class="field">
        <label for="mcTempWarn">Temp Warn &deg;C</label>
        <input id="mcTempWarn" type="number" bind:value={tempWarn} />
      </div>
      <div class="field">
        <label for="mcTempCrit">Temp Crit &deg;C</label>
        <input id="mcTempCrit" type="number" bind:value={tempCrit} />
      </div>
      {#if sensorList.length > 0}
        <div class="field full">
          <label>{$t('modal.check.tempOverrides')}</label>
          <div style="display:flex;flex-direction:column;gap:4px">
            {#each sensorList as s (s.sensor)}
              {@const ov = tempOverrides[s.sensor] ?? { warn: '', crit: '' }}
              <div style="display:flex;gap:8px;align-items:center">
                <span
                  style="min-width:180px;font-size:12px;color:var(--text-muted)"
                  title={s.sensor}>{s.sensor}</span
                >
                <span style="font-size:11px;color:var(--text-muted);min-width:45px"
                  >{s.temp_c}&deg;C</span
                >
                <input
                  type="number"
                  min="0"
                  max={TEMP_GAUGE_MAX}
                  placeholder={String(tempWarn)}
                  style="width:60px;font-size:12px"
                  title="Warn &deg;C"
                  value={ov.warn}
                  oninput={(e) => {
                    const v = (e.currentTarget as HTMLInputElement).value;
                    tempOverrides = {
                      ...tempOverrides,
                      [s.sensor]: { ...ov, warn: v === '' ? '' : Number(v) },
                    };
                  }}
                />
                <input
                  type="number"
                  min="0"
                  max={TEMP_GAUGE_MAX}
                  placeholder={String(tempCrit)}
                  style="width:60px;font-size:12px"
                  title="Crit &deg;C"
                  value={ov.crit}
                  oninput={(e) => {
                    const v = (e.currentTarget as HTMLInputElement).value;
                    tempOverrides = {
                      ...tempOverrides,
                      [s.sensor]: { ...ov, crit: v === '' ? '' : Number(v) },
                    };
                  }}
                />
              </div>
            {/each}
          </div>
        </div>
      {/if}
    {:else if checkType === 'service_process'}
      <div class="field">
        <label for="mcSvcMode">{$t('monitor.cfg.mode')}</label>
        <select id="mcSvcMode" bind:value={svcMode}>
          <option value="auto">auto</option>
          <option value="list">list</option>
        </select>
      </div>
      {#if svcMode === 'list'}
        <div class="field full">
          <label for="mcSvcNames">{$t('monitor.cfg.services')}</label>
          <input id="mcSvcNames" placeholder="sshd, nginx" bind:value={svcNames} />
        </div>
      {:else}
        <div class="field full">
          <label for="mcSvcIgnore">{$t('monitor.cfg.ignored')}</label>
          <input id="mcSvcIgnore" bind:value={svcIgnore} />
        </div>
      {/if}
    {:else if checkType === 'proxmox_backup'}
      <div class="field">
        <label for="mcPveAge">{$t('monitor.cfg.maxAge')} (h)</label>
        <input id="mcPveAge" type="number" bind:value={pveMaxAge} />
      </div>
      <div class="field">
        <label for="mcPveExclude">{$t('monitor.cfg.excludeVmids')}</label>
        <input id="mcPveExclude" bind:value={pveExclude} />
      </div>
      <div class="field">
        <label for="mcPveStopped">Gestoppte VMs</label>
        <select id="mcPveStopped" bind:value={pveExcludeStopped}>
          <option value={true}>{$t('modal.check.pveExcludeStopped')}</option>
          <option value={false}>{$t('modal.check.pveIncludeStopped')}</option>
        </select>
      </div>
    {:else if checkType === 'zfs_health'}
      <div class="field">
        <label for="mcZfsWarn">Kap. Warn %</label>
        <input id="mcZfsWarn" type="number" bind:value={zfsCapWarn} />
      </div>
      <div class="field">
        <label for="mcZfsCrit">Kap. Crit %</label>
        <input id="mcZfsCrit" type="number" bind:value={zfsCapCrit} />
      </div>
    {:else if checkType === 'docker_health'}
      <div class="field full">
        <label for="mcDockerIgnore">{$t('monitor.cfg.ignored')}</label>
        <input id="mcDockerIgnore" placeholder="container1, container2" bind:value={dockerIgnore} />
      </div>
    {:else if checkType === 'smart_health'}
      <div class="field">
        <label>Realloc Warn</label><input type="number" bind:value={smartReallocWarn} />
      </div>
      <div class="field">
        <label>Realloc Crit</label><input type="number" bind:value={smartReallocCrit} />
      </div>
      <div class="field">
        <label>Pending Warn</label><input type="number" bind:value={smartPendingWarn} />
      </div>
      <div class="field">
        <label>Pending Crit</label><input type="number" bind:value={smartPendingCrit} />
      </div>
      <div class="field">
        <label>NVMe Spare Warn %</label><input type="number" bind:value={smartNvmeSpareWarn} />
      </div>
      <div class="field">
        <label>NVMe Spare Crit %</label><input type="number" bind:value={smartNvmeSpareCrit} />
      </div>
      <div class="field">
        <label>NVMe Wear Warn %</label><input type="number" bind:value={smartNvmeUsedWarn} />
      </div>
      <div class="field">
        <label>NVMe Wear Crit %</label><input type="number" bind:value={smartNvmeUsedCrit} />
      </div>
      <div class="field">
        <label>HDD Temp Warn</label><input type="number" bind:value={smartTempHddWarn} />
      </div>
      <div class="field">
        <label>HDD Temp Crit</label><input type="number" bind:value={smartTempHddCrit} />
      </div>
      <div class="field">
        <label>SSD Temp Warn</label><input type="number" bind:value={smartTempSsdWarn} />
      </div>
      <div class="field">
        <label>SSD Temp Crit</label><input type="number" bind:value={smartTempSsdCrit} />
      </div>
      <div class="field">
        <label>NVMe Temp Warn</label><input type="number" bind:value={smartTempNvmeWarn} />
      </div>
      <div class="field">
        <label>NVMe Temp Crit</label><input type="number" bind:value={smartTempNvmeCrit} />
      </div>
      <div class="field full">
        <label for="mcSmartIgnore">{$t('monitor.cfg.ignored')}</label>
        <textarea id="mcSmartIgnore" rows="3" bind:value={smartIgnore}></textarea>
      </div>
    {/if}
  </form>
  {#snippet footer()}
    <Button variant="ghost" onclick={onClose}>{$t('action.cancel')}</Button>
    <Button
      variant="primary"
      type="submit"
      disabled={submitting}
      onclick={() =>
        (document.getElementById('monitor-check-form') as HTMLFormElement)?.requestSubmit()}
    >
      {$t('action.save')}
    </Button>
  {/snippet}
</Modal>
