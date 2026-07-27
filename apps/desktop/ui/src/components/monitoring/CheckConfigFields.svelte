<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import type { MonitorCheckConfig, MonitorCheckType } from '$lib/api/types';
  import { t } from '$lib/i18n';

  interface Props {
    checkType: MonitorCheckType;
    // The parent's reactive $state config object — we mutate config.<field> in
    // place so Svelte 5 fine-grained reactivity keeps the form value in sync.
    config: MonitorCheckConfig;
  }
  let { checkType, config }: Props = $props();

  // ── Field helpers ──────────────────────────────────────────────────────────
  // Empty number ⇒ drop the key (server fills defaults). Empty csv ⇒ drop the key.

  function numVal(key: keyof MonitorCheckConfig): string {
    const v = config[key];
    return typeof v === 'number' ? String(v) : '';
  }
  function setNum(key: string, raw: string): void {
    if (raw.trim() === '') delete config[key];
    else config[key] = Number(raw);
  }

  function strVal(key: keyof MonitorCheckConfig): string {
    const v = config[key];
    return typeof v === 'string' ? v : '';
  }
  function setStr(key: string, raw: string): void {
    config[key] = raw;
  }

  function boolVal(key: keyof MonitorCheckConfig, fallback: boolean): boolean {
    const v = config[key];
    return typeof v === 'boolean' ? v : fallback;
  }
  function setBool(key: string, checked: boolean): void {
    config[key] = checked;
  }

  function csvStrVal(key: keyof MonitorCheckConfig): string {
    const v = config[key];
    return Array.isArray(v) ? v.join(', ') : '';
  }
  function setCsvStr(key: string, raw: string): void {
    const arr = raw
      .split(',')
      .map((s) => s.trim())
      .filter(Boolean);
    if (arr.length === 0) delete config[key];
    else config[key] = arr;
  }
  function setCsvNum(key: string, raw: string): void {
    const arr = raw
      .split(',')
      .map((s) => parseInt(s.trim(), 10))
      .filter((n) => !Number.isNaN(n));
    if (arr.length === 0) delete config[key];
    else config[key] = arr;
  }

  const modeVal = $derived(config.mode === 'auto' ? 'auto' : 'list');

  // Numeric threshold fields rendered data-driven via the numField snippet, so a
  // new threshold is one array entry instead of an 8-line copy-paste block.
  // min/max mirror the T4 backend boundary (app/check_configs.py) — the hard
  // rejection lives server-side; these keep the spinners/form validation sane.
  type NumField = {
    key: Extract<keyof MonitorCheckConfig, string>;
    labelKey: string;
    min?: number;
    max?: number;
  };

  const RESOURCE_NUM_FIELDS: NumField[] = [
    { key: 'cpu_warn', labelKey: 'monitoring.checkCfg.cpuWarn', min: 0, max: 100 },
    { key: 'cpu_crit', labelKey: 'monitoring.checkCfg.cpuCrit', min: 0, max: 100 },
    { key: 'memory_warn', labelKey: 'monitoring.checkCfg.memoryWarn', min: 0, max: 100 },
    { key: 'memory_crit', labelKey: 'monitoring.checkCfg.memoryCrit', min: 0, max: 100 },
    { key: 'disk_warn', labelKey: 'monitoring.checkCfg.diskWarn', min: 0, max: 100 },
    { key: 'disk_crit', labelKey: 'monitoring.checkCfg.diskCrit', min: 0, max: 100 },
    { key: 'temp_warn', labelKey: 'monitoring.checkCfg.tempWarn', min: 0, max: 200 },
    { key: 'temp_crit', labelKey: 'monitoring.checkCfg.tempCrit', min: 0, max: 200 },
    { key: 'hysteresis_pp', labelKey: 'monitoring.checkCfg.hysteresisPp', min: 0, max: 50 },
  ];

  const SMART_NUM_FIELDS: NumField[] = [
    { key: 'reallocated_warn', labelKey: 'monitoring.checkCfg.reallocatedWarn', min: 0 },
    { key: 'reallocated_crit', labelKey: 'monitoring.checkCfg.reallocatedCrit', min: 0 },
    { key: 'pending_warn', labelKey: 'monitoring.checkCfg.pendingWarn', min: 0 },
    { key: 'pending_crit', labelKey: 'monitoring.checkCfg.pendingCrit', min: 0 },
    { key: 'nvme_spare_warn', labelKey: 'monitoring.checkCfg.nvmeSpareWarn', min: 0, max: 100 },
    { key: 'nvme_spare_crit', labelKey: 'monitoring.checkCfg.nvmeSpareCrit', min: 0, max: 100 },
    { key: 'nvme_used_warn', labelKey: 'monitoring.checkCfg.nvmeUsedWarn', min: 0 },
    { key: 'nvme_used_crit', labelKey: 'monitoring.checkCfg.nvmeUsedCrit', min: 0 },
    { key: 'temp_hdd_warn', labelKey: 'monitoring.checkCfg.tempHddWarn', min: 0, max: 200 },
    { key: 'temp_hdd_crit', labelKey: 'monitoring.checkCfg.tempHddCrit', min: 0, max: 200 },
    { key: 'temp_ssd_warn', labelKey: 'monitoring.checkCfg.tempSsdWarn', min: 0, max: 200 },
    { key: 'temp_ssd_crit', labelKey: 'monitoring.checkCfg.tempSsdCrit', min: 0, max: 200 },
    { key: 'temp_nvme_warn', labelKey: 'monitoring.checkCfg.tempNvmeWarn', min: 0, max: 200 },
    { key: 'temp_nvme_crit', labelKey: 'monitoring.checkCfg.tempNvmeCrit', min: 0, max: 200 },
  ];

  const FORECAST_NUM_FIELDS: NumField[] = [
    { key: 'warn_hours', labelKey: 'monitoring.checkCfg.warnHours', min: 1, max: 8760 },
    { key: 'crit_hours', labelKey: 'monitoring.checkCfg.critHours', min: 1, max: 8760 },
    { key: 'window_hours', labelKey: 'monitoring.checkCfg.windowHours', min: 1, max: 168 },
    { key: 'min_history_hours', labelKey: 'monitoring.checkCfg.minHistoryHours', min: 1, max: 48 },
  ];

  // warn >= crit sanity hint. nvme_spare is excluded on purpose: lower is
  // worse there, warn > crit is the CORRECT configuration.
  const WARN_CRIT_PAIRS: { warn: string; crit: string; label: string }[] = [
    { warn: 'cpu_warn', crit: 'cpu_crit', label: 'CPU' },
    { warn: 'memory_warn', crit: 'memory_crit', label: 'RAM' },
    { warn: 'disk_warn', crit: 'disk_crit', label: 'Disk' },
    { warn: 'temp_warn', crit: 'temp_crit', label: 'Temp' },
    { warn: 'capacity_warn', crit: 'capacity_crit', label: 'Capacity' },
    { warn: 'reallocated_warn', crit: 'reallocated_crit', label: 'Reallocated' },
    { warn: 'pending_warn', crit: 'pending_crit', label: 'Pending' },
    { warn: 'nvme_used_warn', crit: 'nvme_used_crit', label: 'NVMe used' },
    { warn: 'temp_hdd_warn', crit: 'temp_hdd_crit', label: 'Temp HDD' },
    { warn: 'temp_ssd_warn', crit: 'temp_ssd_crit', label: 'Temp SSD' },
    { warn: 'temp_nvme_warn', crit: 'temp_nvme_crit', label: 'Temp NVMe' },
  ];

  let thresholdWarnings = $derived(
    WARN_CRIT_PAIRS.filter((pair) => {
      const w = config[pair.warn];
      const c = config[pair.crit];
      return typeof w === 'number' && typeof c === 'number' && w >= c;
    }).map((pair) => pair.label),
  );
</script>

{#snippet numField(f: NumField)}
  <label class="field">
    <span class="field-label">{$t(f.labelKey)}</span>
    <input
      type="number"
      min={f.min}
      max={f.max}
      value={numVal(f.key)}
      oninput={(e) => setNum(f.key, e.currentTarget.value)}
    />
  </label>
{/snippet}

{#if checkType === 'ping'}
  <label class="field">
    <span class="field-label">{$t('monitoring.checkCfg.target')}</span>
    <input
      type="text"
      value={strVal('target')}
      oninput={(e) => setStr('target', e.currentTarget.value)}
    />
  </label>
  <label class="field">
    <span class="field-label">{$t('monitoring.checkCfg.timeout')}</span>
    <input
      type="number"
      min="1"
      max="300"
      value={numVal('timeout')}
      oninput={(e) => setNum('timeout', e.currentTarget.value)}
    />
  </label>
{:else if checkType === 'tcp'}
  <label class="field">
    <span class="field-label">{$t('monitoring.checkCfg.target')}</span>
    <input
      type="text"
      value={strVal('target')}
      oninput={(e) => setStr('target', e.currentTarget.value)}
    />
  </label>
  <label class="field">
    <span class="field-label">{$t('monitoring.checkCfg.port')}</span>
    <input
      type="number"
      min="1"
      max="65535"
      value={numVal('port')}
      oninput={(e) => setNum('port', e.currentTarget.value)}
    />
  </label>
  <label class="field">
    <span class="field-label">{$t('monitoring.checkCfg.timeout')}</span>
    <input
      type="number"
      min="1"
      max="300"
      value={numVal('timeout')}
      oninput={(e) => setNum('timeout', e.currentTarget.value)}
    />
  </label>
{:else if checkType === 'http'}
  <label class="field" style="grid-column: span 2;">
    <span class="field-label">{$t('monitoring.checkCfg.url')}</span>
    <input
      type="url"
      placeholder="https://"
      value={strVal('url')}
      oninput={(e) => setStr('url', e.currentTarget.value)}
    />
  </label>
  <label class="field">
    <span class="field-label">{$t('monitoring.checkCfg.method')}</span>
    <select
      value={strVal('method') || 'GET'}
      onchange={(e) => setStr('method', e.currentTarget.value)}
    >
      <option value="GET">GET</option>
      <option value="POST">POST</option>
      <option value="PUT">PUT</option>
      <option value="HEAD">HEAD</option>
    </select>
  </label>
  <label class="field">
    <span class="field-label">{$t('monitoring.checkCfg.expectedStatus')}</span>
    <input
      type="number"
      min="100"
      max="599"
      value={numVal('expected_status')}
      oninput={(e) => setNum('expected_status', e.currentTarget.value)}
    />
  </label>
  <label class="field">
    <span class="field-label">{$t('monitoring.checkCfg.timeout')}</span>
    <input
      type="number"
      min="1"
      max="300"
      value={numVal('timeout')}
      oninput={(e) => setNum('timeout', e.currentTarget.value)}
    />
  </label>
  <label class="field checkbox">
    <input
      type="checkbox"
      checked={boolVal('verify_ssl', true)}
      onchange={(e) => setBool('verify_ssl', e.currentTarget.checked)}
    />
    <span>{$t('monitoring.checkCfg.verifySsl')}</span>
  </label>
  <label class="field" style="grid-column: span 2;">
    <span class="field-label">{$t('monitoring.checkCfg.searchString')}</span>
    <input
      type="text"
      value={strVal('search_string')}
      oninput={(e) => setStr('search_string', e.currentTarget.value)}
    />
  </label>
{:else if checkType === 'agent_ping'}
  <label class="field">
    <span class="field-label">{$t('monitoring.checkCfg.staleMinutes')}</span>
    <input
      type="number"
      min="1"
      max="1440"
      value={numVal('stale_minutes')}
      oninput={(e) => setNum('stale_minutes', e.currentTarget.value)}
    />
  </label>
{:else if checkType === 'agent_resources'}
  {#each RESOURCE_NUM_FIELDS as f (f.key)}{@render numField(f)}{/each}
{:else if checkType === 'service_process'}
  <label class="field">
    <span class="field-label">{$t('monitoring.checkCfg.mode')}</span>
    <select value={modeVal} onchange={(e) => setStr('mode', e.currentTarget.value)}>
      <option value="auto">{$t('monitoring.checkCfg.modeAuto')}</option>
      <option value="list">{$t('monitoring.checkCfg.modeList')}</option>
    </select>
  </label>
  {#if modeVal === 'list'}
    <label class="field" style="grid-column: span 2;">
      <span class="field-label">{$t('monitoring.checkCfg.services')}</span>
      <input
        type="text"
        placeholder="sshd, nginx"
        value={csvStrVal('services')}
        oninput={(e) => setCsvStr('services', e.currentTarget.value)}
      />
    </label>
  {:else}
    <label class="field" style="grid-column: span 2;">
      <span class="field-label">{$t('monitoring.checkCfg.ignore')}</span>
      <input
        type="text"
        value={csvStrVal('ignore')}
        oninput={(e) => setCsvStr('ignore', e.currentTarget.value)}
      />
    </label>
  {/if}
{:else if checkType === 'proxmox_backup'}
  <label class="field">
    <span class="field-label">{$t('monitoring.checkCfg.maxBackupAgeHours')}</span>
    <input
      type="number"
      min="1"
      max="8760"
      value={numVal('max_backup_age_hours')}
      oninput={(e) => setNum('max_backup_age_hours', e.currentTarget.value)}
    />
  </label>
  <label class="field">
    <span class="field-label">{$t('monitoring.checkCfg.excludeVmids')}</span>
    <input
      type="text"
      placeholder="100, 101"
      value={csvStrVal('exclude_vmids')}
      oninput={(e) => setCsvNum('exclude_vmids', e.currentTarget.value)}
    />
  </label>
  <label class="field checkbox">
    <input
      type="checkbox"
      checked={boolVal('exclude_stopped', true)}
      onchange={(e) => setBool('exclude_stopped', e.currentTarget.checked)}
    />
    <span>{$t('monitoring.checkCfg.excludeStopped')}</span>
  </label>
{:else if checkType === 'zfs_health'}
  <label class="field">
    <span class="field-label">{$t('monitoring.checkCfg.capacityWarn')}</span>
    <input
      type="number"
      min="0"
      max="100"
      value={numVal('capacity_warn')}
      oninput={(e) => setNum('capacity_warn', e.currentTarget.value)}
    />
  </label>
  <label class="field">
    <span class="field-label">{$t('monitoring.checkCfg.capacityCrit')}</span>
    <input
      type="number"
      min="0"
      max="100"
      value={numVal('capacity_crit')}
      oninput={(e) => setNum('capacity_crit', e.currentTarget.value)}
    />
  </label>
{:else if checkType === 'docker_health'}
  <label class="field" style="grid-column: span 2;">
    <span class="field-label">{$t('monitoring.checkCfg.ignoreContainers')}</span>
    <input
      type="text"
      placeholder="container1, container2"
      value={csvStrVal('ignore_containers')}
      oninput={(e) => setCsvStr('ignore_containers', e.currentTarget.value)}
    />
  </label>
{:else if checkType === 'disk_forecast'}
  {#each FORECAST_NUM_FIELDS as f (f.key)}{@render numField(f)}{/each}
{:else if checkType === 'smart_health'}
  {#each SMART_NUM_FIELDS as f (f.key)}{@render numField(f)}{/each}
  <label class="field" style="grid-column: span 2;">
    <span class="field-label">{$t('monitoring.checkCfg.ignoreDevices')}</span>
    <input
      type="text"
      placeholder="/dev/sda, /dev/sdb"
      value={csvStrVal('ignore_devices')}
      oninput={(e) => setCsvStr('ignore_devices', e.currentTarget.value)}
    />
  </label>
{/if}

{#if thresholdWarnings.length > 0}
  <div class="cfg-hint" role="note">
    {$t('monitoring.checkCfg.warnGeCrit', { fields: thresholdWarnings.join(', ') })}
  </div>
{/if}

<style>
  .field {
    display: flex;
    flex-direction: column;
    gap: var(--sp-2);
  }
  .field.checkbox {
    flex-direction: row;
    align-items: center;
    gap: var(--sp-2);
  }
  .field-label {
    font-size: 12px;
    color: var(--text-muted);
  }
  .cfg-hint {
    grid-column: span 2;
    font-size: 12px;
    color: var(--warning, #ffc859);
  }
  .field input,
  .field select {
    background: var(--bg-input, var(--bg-panel));
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    color: var(--text);
    padding: var(--sp-2) var(--sp-3);
    font-size: 13px;
    font-family: inherit;
  }
  .field input:focus,
  .field select:focus {
    outline: 1px solid var(--accent);
  }
</style>
