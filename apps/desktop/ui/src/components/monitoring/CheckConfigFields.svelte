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
  type NumField = { key: Extract<keyof MonitorCheckConfig, string>; labelKey: string };

  const RESOURCE_NUM_FIELDS: NumField[] = [
    { key: 'cpu_warn', labelKey: 'monitoring.checkCfg.cpuWarn' },
    { key: 'cpu_crit', labelKey: 'monitoring.checkCfg.cpuCrit' },
    { key: 'memory_warn', labelKey: 'monitoring.checkCfg.memoryWarn' },
    { key: 'memory_crit', labelKey: 'monitoring.checkCfg.memoryCrit' },
    { key: 'disk_warn', labelKey: 'monitoring.checkCfg.diskWarn' },
    { key: 'disk_crit', labelKey: 'monitoring.checkCfg.diskCrit' },
    { key: 'temp_warn', labelKey: 'monitoring.checkCfg.tempWarn' },
    { key: 'temp_crit', labelKey: 'monitoring.checkCfg.tempCrit' },
  ];

  const SMART_NUM_FIELDS: NumField[] = [
    { key: 'reallocated_warn', labelKey: 'monitoring.checkCfg.reallocatedWarn' },
    { key: 'reallocated_crit', labelKey: 'monitoring.checkCfg.reallocatedCrit' },
    { key: 'pending_warn', labelKey: 'monitoring.checkCfg.pendingWarn' },
    { key: 'pending_crit', labelKey: 'monitoring.checkCfg.pendingCrit' },
    { key: 'nvme_spare_warn', labelKey: 'monitoring.checkCfg.nvmeSpareWarn' },
    { key: 'nvme_spare_crit', labelKey: 'monitoring.checkCfg.nvmeSpareCrit' },
    { key: 'nvme_used_warn', labelKey: 'monitoring.checkCfg.nvmeUsedWarn' },
    { key: 'nvme_used_crit', labelKey: 'monitoring.checkCfg.nvmeUsedCrit' },
    { key: 'temp_hdd_warn', labelKey: 'monitoring.checkCfg.tempHddWarn' },
    { key: 'temp_hdd_crit', labelKey: 'monitoring.checkCfg.tempHddCrit' },
    { key: 'temp_ssd_warn', labelKey: 'monitoring.checkCfg.tempSsdWarn' },
    { key: 'temp_ssd_crit', labelKey: 'monitoring.checkCfg.tempSsdCrit' },
    { key: 'temp_nvme_warn', labelKey: 'monitoring.checkCfg.tempNvmeWarn' },
    { key: 'temp_nvme_crit', labelKey: 'monitoring.checkCfg.tempNvmeCrit' },
  ];
</script>

{#snippet numField(key: Extract<keyof MonitorCheckConfig, string>, labelKey: string)}
  <label class="field">
    <span class="field-label">{$t(labelKey)}</span>
    <input type="number" value={numVal(key)} oninput={(e) => setNum(key, e.currentTarget.value)} />
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
      value={numVal('port')}
      oninput={(e) => setNum('port', e.currentTarget.value)}
    />
  </label>
  <label class="field">
    <span class="field-label">{$t('monitoring.checkCfg.timeout')}</span>
    <input
      type="number"
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
      value={numVal('expected_status')}
      oninput={(e) => setNum('expected_status', e.currentTarget.value)}
    />
  </label>
  <label class="field">
    <span class="field-label">{$t('monitoring.checkCfg.timeout')}</span>
    <input
      type="number"
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
      value={numVal('stale_minutes')}
      oninput={(e) => setNum('stale_minutes', e.currentTarget.value)}
    />
  </label>
{:else if checkType === 'agent_resources'}
  {#each RESOURCE_NUM_FIELDS as f (f.key)}{@render numField(f.key, f.labelKey)}{/each}
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
      value={numVal('capacity_warn')}
      oninput={(e) => setNum('capacity_warn', e.currentTarget.value)}
    />
  </label>
  <label class="field">
    <span class="field-label">{$t('monitoring.checkCfg.capacityCrit')}</span>
    <input
      type="number"
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
  <label class="field checkbox">
    <input
      type="checkbox"
      checked={boolVal('check_restarts', false)}
      onchange={(e) => setBool('check_restarts', e.currentTarget.checked)}
    />
    <span>{$t('monitoring.checkCfg.checkRestarts')}</span>
  </label>
{:else if checkType === 'smart_health'}
  {#each SMART_NUM_FIELDS as f (f.key)}{@render numField(f.key, f.labelKey)}{/each}
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
