<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import Modal from '$lib/components/ui/Modal.svelte';
  import Button from '$lib/components/ui/Button.svelte';
  import { t } from '$lib/i18n';
  import { monitoringTemplates } from '$lib/stores/monitoring';
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
    parseCsv,
    toCsv,
  } from '$lib/utils/monitoring';
  import type {
    MonitorCheckConfig,
    MonitorCheckType,
    MonitoringTemplateFull,
    MonitoringTemplateInput,
    TemplateAlertDef,
    TemplateCheckDef,
  } from '$lib/api/types';

  interface Props {
    open: boolean;
    editing: MonitoringTemplateFull | null;
    onClose: () => void;
  }

  let { open, editing, onClose }: Props = $props();

  let name = $state('');
  let description = $state('');
  let checkDefs = $state<TemplateCheckDef[]>([]);
  let alertDefs = $state<TemplateAlertDef[]>([]);
  let submitting = $state(false);

  $effect(() => {
    if (!open) return;
    name = editing?.name ?? '';
    description = editing?.description ?? '';
    checkDefs = (editing?.checkDefinitions ?? []).map((d) => ({ ...d, config: { ...d.config } }));
    alertDefs = (editing?.alertDefinitions ?? []).map((d) => ({
      ...d,
      channel_config: { ...d.channel_config },
    }));
  });

  function defaultConfig(type: MonitorCheckType): MonitorCheckConfig {
    const h = '{{hostname}}';
    switch (type) {
      case 'ping':
        return { target: h, timeout: 5 };
      case 'tcp':
        return { target: h, port: 22, timeout: 5 };
      case 'http':
        return {
          url: 'http://{{hostname}}',
          method: 'GET',
          expected_status: 200,
          timeout: 10,
          verify_ssl: true,
        };
      case 'agent_ping':
        return { server_id: '{{server_id}}', stale_minutes: 5 };
      case 'agent_resources':
        return {
          cpu_warn: DEF_CPU_WARN,
          cpu_crit: DEF_CPU_CRIT,
          memory_warn: DEF_MEM_WARN,
          memory_crit: DEF_MEM_CRIT,
          disk_warn: DEF_DISK_WARN,
          disk_crit: DEF_DISK_CRIT,
          temp_warn: DEF_TEMP_WARN,
          temp_crit: DEF_TEMP_CRIT,
        };
      case 'service_process':
        return { mode: 'auto', ignore: [] };
      case 'proxmox_backup':
        return { max_backup_age_hours: 26, exclude_vmids: [], exclude_stopped: true };
      case 'zfs_health':
        return { capacity_warn: 80, capacity_crit: 90 };
      case 'docker_health':
        return { ignore_containers: [] };
      case 'smart_health':
        return {
          reallocated_warn: 1,
          reallocated_crit: 10,
          pending_warn: 1,
          pending_crit: 5,
          nvme_spare_warn: 20,
          nvme_spare_crit: 10,
          nvme_used_warn: 90,
          nvme_used_crit: 100,
          temp_hdd_warn: 55,
          temp_hdd_crit: 60,
          temp_ssd_warn: 60,
          temp_ssd_crit: 70,
          temp_nvme_warn: 65,
          temp_nvme_crit: 75,
          ignore_devices: [],
        };
    }
  }

  function addCheckDef() {
    checkDefs = [
      ...checkDefs,
      {
        def_id: crypto.randomUUID(),
        name: 'Ping {{server_name}}',
        check_type: 'ping',
        config: { target: '{{hostname}}', timeout: 5 },
        interval: '5m',
        severity: 'critical',
        consecutive_fails: 3,
      },
    ];
  }

  function removeCheckDef(i: number) {
    checkDefs = checkDefs.filter((_, idx) => idx !== i);
  }

  function changeCheckType(i: number, type: MonitorCheckType) {
    checkDefs = checkDefs.map((d, idx) =>
      idx === i ? { ...d, check_type: type, config: defaultConfig(type) } : d,
    );
  }

  function updateCheckConfig(i: number, key: string, value: unknown) {
    checkDefs = checkDefs.map((d, idx) =>
      idx === i ? { ...d, config: { ...d.config, [key]: value } } : d,
    );
  }

  function updateCheckField<K extends keyof TemplateCheckDef>(
    i: number,
    key: K,
    value: TemplateCheckDef[K],
  ) {
    checkDefs = checkDefs.map((d, idx) => (idx === i ? { ...d, [key]: value } : d));
  }

  function addAlertDef() {
    alertDefs = [
      ...alertDefs,
      {
        def_id: crypto.randomUUID(),
        name: 'Alert {{server_name}}',
        channel: 'webhook',
        channel_config: { url: '' },
        match_severity: 'critical',
        cooldown_minutes: 30,
        enabled: true,
      },
    ];
  }

  function removeAlertDef(i: number) {
    alertDefs = alertDefs.filter((_, idx) => idx !== i);
  }

  function changeAlertChannel(i: number, ch: 'webhook' | 'email') {
    alertDefs = alertDefs.map((d, idx) =>
      idx === i ? { ...d, channel: ch, channel_config: {} } : d,
    );
  }

  function updateAlertField<K extends keyof TemplateAlertDef>(
    i: number,
    key: K,
    value: TemplateAlertDef[K],
  ) {
    alertDefs = alertDefs.map((d, idx) => (idx === i ? { ...d, [key]: value } : d));
  }

  function updateAlertChannelConfig(i: number, key: string, value: unknown) {
    alertDefs = alertDefs.map((d, idx) =>
      idx === i ? { ...d, channel_config: { ...d.channel_config, [key]: value } } : d,
    );
  }

  async function onSubmit(e: SubmitEvent) {
    e.preventDefault();
    submitting = true;
    try {
      const data: MonitoringTemplateInput = {
        name: name.trim(),
        description: description.trim() || null,
        check_definitions: checkDefs,
        alert_definitions: alertDefs,
      };
      if (editing) {
        await monitoringTemplates.update(editing.id, data);
        showToast($t('toast.template.saved'));
      } else {
        await monitoringTemplates.create(data);
        showToast($t('toast.template.created'));
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
  title={editing ? $t('modal.template.title') : $t('modal.template.titleNew')}
  width="900px"
  {onClose}
>
  <form class="modal-form" onsubmit={onSubmit} id="template-form">
    <div class="field">
      <label for="tplName">{$t('label.name')} *</label>
      <input id="tplName" required bind:value={name} />
    </div>
    <div class="field full">
      <label for="tplDesc">{$t('label.description')}</label>
      <input id="tplDesc" bind:value={description} />
    </div>

    <div class="field full">
      <label>{$t('modal.template.checks')} ({checkDefs.length})</label>
      {#if checkDefs.length === 0}
        <div style="color:var(--text-muted);font-size:13px;padding:8px 0">
          {$t('modal.template.noChecks')}
        </div>
      {:else}
        {#each checkDefs as def, i (def.def_id ?? i)}
          {@const cfg = def.config ?? {}}
          <div
            class="tpl-def-row"
            style="margin-bottom:8px;padding:8px 10px;background:var(--bg-card);border:1px solid var(--border);border-radius:8px"
          >
            <div style="display:flex;gap:6px;align-items:center;margin-bottom:6px;flex-wrap:wrap">
              <span class="badge badge-{def.check_type}" style="flex-shrink:0;font-size:10px">
                {def.check_type.toUpperCase()}
              </span>
              <input
                value={def.name}
                style="flex:1;min-width:120px"
                placeholder={'Name ({{server_name}})'}
                oninput={(e) =>
                  updateCheckField(i, 'name', (e.currentTarget as HTMLInputElement).value)}
              />
              <select
                style="width:140px"
                value={def.check_type}
                onchange={(e) =>
                  changeCheckType(
                    i,
                    (e.currentTarget as HTMLSelectElement).value as MonitorCheckType,
                  )}
              >
                {#each ['ping', 'tcp', 'http', 'agent_ping', 'agent_resources', 'service_process', 'proxmox_backup', 'zfs_health', 'docker_health', 'smart_health'] as tp (tp)}
                  <option value={tp}>{tp}</option>
                {/each}
              </select>
              <select
                style="width:70px"
                value={def.interval}
                onchange={(e) =>
                  updateCheckField(
                    i,
                    'interval',
                    (e.currentTarget as HTMLSelectElement).value as TemplateCheckDef['interval'],
                  )}
              >
                {#each ['1m', '5m', '15m', '30m', '1h', '6h', '12h', '24h'] as v (v)}
                  <option value={v}>{v}</option>
                {/each}
              </select>
              <select
                style="width:90px"
                value={def.severity}
                onchange={(e) =>
                  updateCheckField(
                    i,
                    'severity',
                    (e.currentTarget as HTMLSelectElement).value as TemplateCheckDef['severity'],
                  )}
              >
                <option value="critical">critical</option>
                <option value="warning">warning</option>
                <option value="info">info</option>
              </select>
              <button type="button" class="btn small ghost" onclick={() => removeCheckDef(i)}
                >&#x2715;</button
              >
            </div>
            <div style="display:flex;gap:6px;flex-wrap:wrap;font-size:13px">
              {#if def.check_type === 'ping'}
                <input
                  value={cfg.target ?? ''}
                  placeholder="Ziel"
                  style="width:160px;font-size:12px"
                  oninput={(e) =>
                    updateCheckConfig(i, 'target', (e.currentTarget as HTMLInputElement).value)}
                />
                <input
                  type="number"
                  value={cfg.timeout ?? 5}
                  placeholder="Timeout (s)"
                  style="width:70px;font-size:12px"
                  oninput={(e) =>
                    updateCheckConfig(
                      i,
                      'timeout',
                      Number((e.currentTarget as HTMLInputElement).value) || 0,
                    )}
                />
              {:else if def.check_type === 'tcp'}
                <input
                  value={cfg.target ?? ''}
                  placeholder="Ziel"
                  style="width:160px;font-size:12px"
                  oninput={(e) =>
                    updateCheckConfig(i, 'target', (e.currentTarget as HTMLInputElement).value)}
                />
                <input
                  type="number"
                  value={cfg.port ?? ''}
                  placeholder="Port"
                  style="width:70px;font-size:12px"
                  oninput={(e) =>
                    updateCheckConfig(
                      i,
                      'port',
                      Number((e.currentTarget as HTMLInputElement).value) || 0,
                    )}
                />
                <input
                  type="number"
                  value={cfg.timeout ?? 5}
                  placeholder="Timeout (s)"
                  style="width:70px;font-size:12px"
                  oninput={(e) =>
                    updateCheckConfig(
                      i,
                      'timeout',
                      Number((e.currentTarget as HTMLInputElement).value) || 0,
                    )}
                />
              {:else if def.check_type === 'http'}
                <input
                  value={cfg.url ?? ''}
                  placeholder="URL"
                  style="width:220px;font-size:12px"
                  oninput={(e) =>
                    updateCheckConfig(i, 'url', (e.currentTarget as HTMLInputElement).value)}
                />
                <select
                  value={cfg.method ?? 'GET'}
                  style="font-size:12px"
                  onchange={(e) =>
                    updateCheckConfig(i, 'method', (e.currentTarget as HTMLSelectElement).value)}
                >
                  {#each ['GET', 'POST', 'PUT', 'HEAD'] as m (m)}<option value={m}>{m}</option
                    >{/each}
                </select>
                <input
                  type="number"
                  value={cfg.expected_status ?? 200}
                  placeholder="Status"
                  style="width:60px;font-size:12px"
                  oninput={(e) =>
                    updateCheckConfig(
                      i,
                      'expected_status',
                      Number((e.currentTarget as HTMLInputElement).value) || 200,
                    )}
                />
                <input
                  type="number"
                  value={cfg.timeout ?? 10}
                  placeholder="Timeout (s)"
                  style="width:70px;font-size:12px"
                  oninput={(e) =>
                    updateCheckConfig(
                      i,
                      'timeout',
                      Number((e.currentTarget as HTMLInputElement).value) || 0,
                    )}
                />
                <select
                  style="font-size:12px"
                  value={String(cfg.verify_ssl ?? true)}
                  onchange={(e) =>
                    updateCheckConfig(
                      i,
                      'verify_ssl',
                      (e.currentTarget as HTMLSelectElement).value === 'true',
                    )}
                >
                  <option value="true">SSL Ja</option>
                  <option value="false">SSL Nein</option>
                </select>
                <input
                  value={cfg.search_string ?? ''}
                  placeholder="Suchtext"
                  style="width:120px;font-size:12px"
                  oninput={(e) =>
                    updateCheckConfig(
                      i,
                      'search_string',
                      (e.currentTarget as HTMLInputElement).value,
                    )}
                />
              {:else if def.check_type === 'agent_ping'}
                <input
                  value={cfg.server_id ?? ''}
                  placeholder="Server-ID"
                  style="width:220px;font-size:12px"
                  oninput={(e) =>
                    updateCheckConfig(i, 'server_id', (e.currentTarget as HTMLInputElement).value)}
                />
                <input
                  type="number"
                  value={cfg.stale_minutes ?? 5}
                  placeholder="Timeout (min)"
                  style="width:80px;font-size:12px"
                  oninput={(e) =>
                    updateCheckConfig(
                      i,
                      'stale_minutes',
                      Number((e.currentTarget as HTMLInputElement).value) || 5,
                    )}
                />
              {:else if def.check_type === 'agent_resources'}
                {#each ['cpu_warn', 'cpu_crit', 'memory_warn', 'memory_crit', 'disk_warn', 'disk_crit', 'temp_warn', 'temp_crit'] as k (k)}
                  <input
                    type="number"
                    value={(cfg as Record<string, number>)[k] ?? 0}
                    placeholder={k}
                    style="width:80px;font-size:12px"
                    oninput={(e) =>
                      updateCheckConfig(
                        i,
                        k,
                        Number((e.currentTarget as HTMLInputElement).value) || 0,
                      )}
                  />
                {/each}
              {:else if def.check_type === 'service_process'}
                <select
                  value={cfg.mode ?? 'auto'}
                  style="font-size:12px"
                  onchange={(e) =>
                    updateCheckConfig(i, 'mode', (e.currentTarget as HTMLSelectElement).value)}
                >
                  <option value="auto">auto</option>
                  <option value="list">list</option>
                </select>
                {#if cfg.mode === 'list'}
                  <input
                    value={toCsv(cfg.services)}
                    placeholder="Services"
                    style="width:200px;font-size:12px"
                    oninput={(e) =>
                      updateCheckConfig(
                        i,
                        'services',
                        parseCsv((e.currentTarget as HTMLInputElement).value),
                      )}
                  />
                {:else}
                  <input
                    value={toCsv(cfg.ignore)}
                    placeholder="Ignorieren"
                    style="width:200px;font-size:12px"
                    oninput={(e) =>
                      updateCheckConfig(
                        i,
                        'ignore',
                        parseCsv((e.currentTarget as HTMLInputElement).value),
                      )}
                  />
                {/if}
              {:else if def.check_type === 'proxmox_backup'}
                <input
                  type="number"
                  value={cfg.max_backup_age_hours ?? 26}
                  placeholder="max Alter (h)"
                  style="width:90px;font-size:12px"
                  oninput={(e) =>
                    updateCheckConfig(
                      i,
                      'max_backup_age_hours',
                      Number((e.currentTarget as HTMLInputElement).value) || 26,
                    )}
                />
              {:else if def.check_type === 'zfs_health'}
                <input
                  type="number"
                  value={cfg.capacity_warn ?? 80}
                  placeholder="Warn %"
                  style="width:80px;font-size:12px"
                  oninput={(e) =>
                    updateCheckConfig(
                      i,
                      'capacity_warn',
                      Number((e.currentTarget as HTMLInputElement).value) || 80,
                    )}
                />
                <input
                  type="number"
                  value={cfg.capacity_crit ?? 90}
                  placeholder="Crit %"
                  style="width:80px;font-size:12px"
                  oninput={(e) =>
                    updateCheckConfig(
                      i,
                      'capacity_crit',
                      Number((e.currentTarget as HTMLInputElement).value) || 90,
                    )}
                />
              {:else if def.check_type === 'docker_health'}
                <input
                  value={toCsv(cfg.ignore_containers)}
                  placeholder="Ignorieren"
                  style="width:200px;font-size:12px"
                  oninput={(e) =>
                    updateCheckConfig(
                      i,
                      'ignore_containers',
                      parseCsv((e.currentTarget as HTMLInputElement).value),
                    )}
                />
              {/if}
            </div>
          </div>
        {/each}
      {/if}
      <button type="button" class="btn small" onclick={addCheckDef}>+ Check</button>
    </div>

    <div class="field full">
      <label>{$t('modal.template.alerts')} ({alertDefs.length})</label>
      {#if alertDefs.length === 0}
        <div style="color:var(--text-muted);font-size:13px;padding:8px 0">
          {$t('modal.template.noAlerts')}
        </div>
      {:else}
        {#each alertDefs as def, i (def.def_id ?? i)}
          {@const cc = def.channel_config ?? {}}
          <div
            class="tpl-def-row"
            style="margin-bottom:8px;padding:8px 10px;background:var(--bg-card);border:1px solid var(--border);border-radius:8px"
          >
            <div style="display:flex;gap:6px;align-items:center;margin-bottom:6px;flex-wrap:wrap">
              <span class="badge badge-{def.channel}" style="flex-shrink:0;font-size:10px">
                {def.channel === 'email' ? 'E-Mail' : 'Webhook'}
              </span>
              <input
                value={def.name}
                style="flex:1;min-width:120px"
                placeholder="Name"
                oninput={(e) =>
                  updateAlertField(i, 'name', (e.currentTarget as HTMLInputElement).value)}
              />
              <select
                value={def.channel}
                style="width:90px"
                onchange={(e) =>
                  changeAlertChannel(
                    i,
                    (e.currentTarget as HTMLSelectElement).value as 'webhook' | 'email',
                  )}
              >
                <option value="webhook">Webhook</option>
                <option value="email">E-Mail</option>
              </select>
              <select
                value={def.match_severity ?? ''}
                style="width:100px"
                onchange={(e) => {
                  const v = (e.currentTarget as HTMLSelectElement).value;
                  updateAlertField(
                    i,
                    'match_severity',
                    (v || null) as TemplateAlertDef['match_severity'],
                  );
                }}
              >
                <option value="">Alle</option>
                <option value="critical">critical</option>
                <option value="warning">warning</option>
              </select>
              <input
                type="number"
                value={def.cooldown_minutes ?? 30}
                placeholder="Cooldown (min)"
                style="width:80px"
                oninput={(e) =>
                  updateAlertField(
                    i,
                    'cooldown_minutes',
                    Number((e.currentTarget as HTMLInputElement).value) || 30,
                  )}
              />
              <button type="button" class="btn small ghost" onclick={() => removeAlertDef(i)}
                >&#x2715;</button
              >
            </div>
            <div style="display:flex;gap:6px;flex-wrap:wrap;font-size:13px">
              {#if def.channel === 'webhook'}
                <input
                  value={cc.url ?? ''}
                  placeholder="Webhook URL"
                  style="flex:1;min-width:200px;font-size:12px"
                  oninput={(e) =>
                    updateAlertChannelConfig(i, 'url', (e.currentTarget as HTMLInputElement).value)}
                />
              {:else}
                <input
                  value={cc.to ?? ''}
                  placeholder="Empfaenger"
                  style="flex:1;min-width:160px;font-size:12px"
                  oninput={(e) =>
                    updateAlertChannelConfig(i, 'to', (e.currentTarget as HTMLInputElement).value)}
                />
                <input
                  value={cc.smtp_host ?? ''}
                  placeholder="SMTP Host"
                  style="width:160px;font-size:12px"
                  oninput={(e) =>
                    updateAlertChannelConfig(
                      i,
                      'smtp_host',
                      (e.currentTarget as HTMLInputElement).value,
                    )}
                />
                <input
                  type="number"
                  value={cc.smtp_port ?? 587}
                  placeholder="Port"
                  style="width:70px;font-size:12px"
                  oninput={(e) =>
                    updateAlertChannelConfig(
                      i,
                      'smtp_port',
                      Number((e.currentTarget as HTMLInputElement).value) || 587,
                    )}
                />
              {/if}
            </div>
          </div>
        {/each}
      {/if}
      <button type="button" class="btn small" onclick={addAlertDef}>+ Alert</button>
    </div>
  </form>
  {#snippet footer()}
    <Button variant="ghost" onclick={onClose}>{$t('action.cancel')}</Button>
    <Button
      variant="primary"
      type="submit"
      disabled={submitting}
      onclick={() => (document.getElementById('template-form') as HTMLFormElement)?.requestSubmit()}
    >
      {$t('action.save')}
    </Button>
  {/snippet}
</Modal>
