<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import { onMount } from 'svelte';
  import 'uplot/dist/uPlot.min.css';
  import { t, language } from '$lib/i18n';
  import { monitorChecks, alertRules, alertLog, monitoringTemplates } from '$lib/stores/monitoring';
  import { servers as serversStore } from '$lib/stores/servers';
  import { showToast } from '$lib/stores/notifications';
  import { worstStatusOf, formatTime } from '$lib/utils/monitoring';
  import Button from '$lib/components/ui/Button.svelte';
  import EmptyState from '$lib/components/ui/EmptyState.svelte';
  import { confirmDialog } from '$lib/components/ui/ConfirmDialog.svelte';
  import CheckDetail from '$lib/components/monitoring/CheckDetail.svelte';
  import MonitorCheckModal from '$modals/MonitorCheckModal.svelte';
  import AlertRuleModal from '$modals/AlertRuleModal.svelte';
  import MonitoringTemplateModal from '$modals/MonitoringTemplateModal.svelte';
  import type { AlertRule, MonitorCheck, MonStatus, MonitoringTemplateFull } from '$lib/api/types';

  type Tab = 'overview' | 'alerts' | 'log' | 'templates';

  let activeTab = $state<Tab>('overview');

  // ── Filter-State ───────────────────────────────────────────────────────
  let serverFilter = $state('');
  let typeFilter = $state('');
  let statusFilter = $state('');
  let tagFilter = $state('');
  let searchQuery = $state('');

  // ── Modals ────────────────────────────────────────────────────────────
  let checkModalOpen = $state(false);
  let editingCheck = $state<MonitorCheck | null>(null);
  let alertModalOpen = $state(false);
  let editingAlert = $state<AlertRule | null>(null);
  let templateModalOpen = $state(false);
  let editingTemplate = $state<MonitoringTemplateFull | null>(null);

  // ── Expandable Check-Rows ─────────────────────────────────────────────
  let expandedCheckId = $state<string | null>(null);
  let expandedServers = $state<Record<string, boolean>>({});

  let logLoaded = $state(false);

  onMount(async () => {
    try {
      await Promise.all([
        monitorChecks.refresh(),
        alertRules.refresh(),
        monitoringTemplates.refresh(),
        $serversStore.length === 0 ? serversStore.refresh() : Promise.resolve(),
      ]);
    } catch (err) {
      showToast(err instanceof Error ? err.message : $t('error.generic'), 'error');
    }
  });

  const serverMap = $derived.by(() => {
    // eslint-disable-next-line svelte/prefer-svelte-reactivity -- transient builder inside $derived.by, not reactive state
    const m = new Map<string, string>();
    for (const s of $serversStore) m.set(s.id, s.name);
    return m;
  });

  // ── Filtered checks ────────────────────────────────────────────────────
  const filteredChecks = $derived.by(() => {
    let list = $monitorChecks;
    if (serverFilter) list = list.filter((c) => c.serverId === serverFilter);
    if (typeFilter) list = list.filter((c) => c.checkType === typeFilter);
    if (statusFilter) {
      list = list.filter((c) => (c.state?.status ?? 'pending') === statusFilter);
    }
    if (tagFilter) {
      const tag = tagFilter;
      const byId = new Map($serversStore.map((s) => [s.id, s]));
      list = list.filter((c) => {
        const srv = c.serverId ? byId.get(c.serverId) : null;
        return srv && (srv.tags ?? []).includes(tag);
      });
    }
    if (searchQuery) {
      const q = searchQuery.toLowerCase();
      list = list.filter((c) => {
        const sn = c.serverId ? (serverMap.get(c.serverId) ?? '') : '';
        return (
          c.name.toLowerCase().includes(q) ||
          (c.state?.message ?? '').toLowerCase().includes(q) ||
          sn.toLowerCase().includes(q)
        );
      });
    }
    return list;
  });

  const summaryCounts = $derived.by(() => {
    const counts = { total: filteredChecks.length, ok: 0, warning: 0, critical: 0 };
    for (const c of filteredChecks) {
      const s = c.state?.status ?? 'pending';
      if (s === 'ok') counts.ok++;
      else if (s === 'warning') counts.warning++;
      else if (s === 'critical') counts.critical++;
    }
    return counts;
  });

  const serverIdsInUse = $derived(
    Array.from(new Set($monitorChecks.map((c) => c.serverId).filter((x): x is string => !!x))),
  );
  const typesInUse = $derived(Array.from(new Set($monitorChecks.map((c) => c.checkType))).sort());
  const tagsInUse = $derived.by(() => {
    // eslint-disable-next-line svelte/prefer-svelte-reactivity -- transient builder inside $derived.by, not reactive state
    const set = new Set<string>();
    for (const id of serverIdsInUse) {
      const s = $serversStore.find((srv) => srv.id === id);
      for (const tg of s?.tags ?? []) set.add(tg);
    }
    return Array.from(set).sort();
  });

  // ── Checks grouped by server ───────────────────────────────────────────
  interface CheckGroup {
    key: string;
    title: string;
    checks: MonitorCheck[];
    worst: MonStatus;
  }

  const checkGroups = $derived.by<CheckGroup[]>(() => {
    // eslint-disable-next-line svelte/prefer-svelte-reactivity -- transient builder inside $derived.by, not reactive state
    const byServer = new Map<string, MonitorCheck[]>();
    const noServer: MonitorCheck[] = [];
    for (const c of filteredChecks) {
      if (c.serverId) {
        const bucket = byServer.get(c.serverId) ?? [];
        bucket.push(c);
        byServer.set(c.serverId, bucket);
      } else {
        noServer.push(c);
      }
    }
    const groups: CheckGroup[] = [];
    for (const [sid, checks] of byServer.entries()) {
      groups.push({
        key: sid,
        title: serverMap.get(sid) ?? sid,
        checks,
        worst: worstStatusOf(checks),
      });
    }
    if (noServer.length > 0) {
      groups.push({
        key: '__nosrv__',
        title: $t('monitor.noServer'),
        checks: noServer,
        worst: worstStatusOf(noServer),
      });
    }
    return groups;
  });

  // ── Check-Actions ─────────────────────────────────────────────────────
  function openCreateCheck() {
    editingCheck = null;
    checkModalOpen = true;
  }

  function editCheck(c: MonitorCheck) {
    editingCheck = c;
    checkModalOpen = true;
  }

  async function runCheckNow(c: MonitorCheck) {
    try {
      await monitorChecks.run(c.id);
      showToast($t('toast.check.executed'));
    } catch (err) {
      showToast(err instanceof Error ? err.message : $t('error.generic'), 'error');
    }
  }

  async function toggleCheck(c: MonitorCheck) {
    try {
      await monitorChecks.toggle(c.id);
    } catch (err) {
      showToast(err instanceof Error ? err.message : $t('error.generic'), 'error');
    }
  }

  async function removeCheck(c: MonitorCheck) {
    if (!(await confirmDialog($t('confirm.check.delete'), { confirmLabel: $t('action.delete') })))
      return;
    try {
      await monitorChecks.remove(c.id);
      showToast($t('toast.check.deleted'));
    } catch (err) {
      showToast(err instanceof Error ? err.message : $t('error.generic'), 'error');
    }
  }

  function closeCheckModal() {
    checkModalOpen = false;
    editingCheck = null;
    void monitorChecks.refresh();
  }

  // ── Alert-Actions ─────────────────────────────────────────────────────
  function openCreateAlert() {
    editingAlert = null;
    alertModalOpen = true;
  }

  function editAlert(r: AlertRule) {
    editingAlert = r;
    alertModalOpen = true;
  }

  async function toggleAlert(r: AlertRule) {
    try {
      await alertRules.toggle(r.id);
      showToast($t('toast.alert.updated'));
    } catch (err) {
      showToast(err instanceof Error ? err.message : $t('error.generic'), 'error');
    }
  }

  async function removeAlert(r: AlertRule) {
    if (!(await confirmDialog($t('confirm.alert.delete'), { confirmLabel: $t('action.delete') })))
      return;
    try {
      await alertRules.remove(r.id);
      showToast($t('toast.alert.deleted'));
    } catch (err) {
      showToast(err instanceof Error ? err.message : $t('error.generic'), 'error');
    }
  }

  function closeAlertModal() {
    alertModalOpen = false;
    editingAlert = null;
    void alertRules.refresh();
  }

  // ── Template-Actions ──────────────────────────────────────────────────
  function openCreateTemplate() {
    editingTemplate = null;
    templateModalOpen = true;
  }

  function editTemplate(tpl: MonitoringTemplateFull) {
    editingTemplate = tpl;
    templateModalOpen = true;
  }

  async function removeTemplate(tpl: MonitoringTemplateFull) {
    if (
      !(await confirmDialog($t('confirm.template.delete'), { confirmLabel: $t('action.delete') }))
    )
      return;
    try {
      await monitoringTemplates.remove(tpl.id);
      showToast($t('toast.template.deleted'));
    } catch (err) {
      showToast(err instanceof Error ? err.message : $t('error.generic'), 'error');
    }
  }

  function closeTemplateModal() {
    templateModalOpen = false;
    editingTemplate = null;
    void monitoringTemplates.refresh();
  }

  // ── Tab change ─────────────────────────────────────────────────────────
  async function switchTab(tab: Tab) {
    activeTab = tab;
    if (tab === 'log' && !logLoaded) {
      try {
        await alertLog.refresh();
        logLoaded = true;
      } catch (err) {
        showToast(err instanceof Error ? err.message : $t('error.generic'), 'error');
      }
    }
  }

  async function refreshLog() {
    try {
      await alertLog.refresh();
      logLoaded = true;
    } catch (err) {
      showToast(err instanceof Error ? err.message : $t('error.generic'), 'error');
    }
  }

  function toggleServer(key: string) {
    expandedServers = { ...expandedServers, [key]: !expandedServers[key] };
  }

  function toggleCheckRow(id: string) {
    expandedCheckId = expandedCheckId === id ? null : id;
  }

  function alertFilterLabel(r: AlertRule): string {
    const parts: string[] = [];
    if (r.matchSeverity) parts.push(`Severity: ${r.matchSeverity}`);
    if (r.matchServerId) {
      const name = serverMap.get(r.matchServerId) ?? r.matchServerId.substring(0, 8);
      parts.push(`Server: ${name}`);
    }
    return parts.length > 0 ? parts.join(', ') : $t('label.all');
  }
</script>

<div class="page active">
  <div class="page-header">
    <div>
      <div class="page-title">{$t('page.monitoring.title')}</div>
      <div class="page-subtitle">{$t('page.monitoring.subtitle')}</div>
    </div>
  </div>

  <div class="monitor-tabs">
    <button
      class="monitor-tab"
      class:active={activeTab === 'overview'}
      onclick={() => switchTab('overview')}>{$t('page.monitoring.tabOverview')}</button
    >
    <button
      class="monitor-tab"
      class:active={activeTab === 'alerts'}
      onclick={() => switchTab('alerts')}>{$t('page.monitoring.tabAlerts')}</button
    >
    <button class="monitor-tab" class:active={activeTab === 'log'} onclick={() => switchTab('log')}
      >{$t('page.monitoring.tabLog')}</button
    >
    <button
      class="monitor-tab"
      class:active={activeTab === 'templates'}
      onclick={() => switchTab('templates')}>{$t('page.monitoring.tabTemplates')}</button
    >
  </div>

  <!-- Tab: Overview -->
  {#if activeTab === 'overview'}
    <div class="monitor-tab-content active">
      <div class="monitor-filters">
        <select class="filter-select" bind:value={serverFilter}>
          <option value="">{$t('label.allServers')}</option>
          {#each serverIdsInUse as id (id)}
            <option value={id}>{serverMap.get(id) ?? id.substring(0, 8)}</option>
          {/each}
        </select>
        <select class="filter-select" bind:value={typeFilter}>
          <option value="">{$t('label.allTypes')}</option>
          {#each typesInUse as tp (tp)}
            <option value={tp}>{tp}</option>
          {/each}
        </select>
        <select class="filter-select" bind:value={statusFilter}>
          <option value="">{$t('label.allStatus')}</option>
          <option value="ok">{$t('monitor.ok')}</option>
          <option value="warning">{$t('monitor.warning')}</option>
          <option value="critical">{$t('monitor.critical')}</option>
          <option value="unknown">{$t('monitor.unknown')}</option>
        </select>
        <select class="filter-select" bind:value={tagFilter}>
          <option value="">{$t('label.allTags')}</option>
          {#each tagsInUse as tg (tg)}
            <option value={tg}>{tg}</option>
          {/each}
        </select>
        <input
          type="search"
          class="search-input"
          placeholder={$t('action.searchShort')}
          bind:value={searchQuery}
        />
        <Button variant="primary" onclick={openCreateCheck}>
          {$t('page.monitoring.addCheck')}
        </Button>
      </div>

      <div id="monitorOverview" style="display:grid;grid-template-columns:repeat(4,1fr);gap:12px">
        <div class="monitor-summary-card">
          <div class="monitor-summary-value">{summaryCounts.total}</div>
          <div class="monitor-summary-label">{$t('monitor.total')}</div>
        </div>
        <div class="monitor-summary-card monitor-summary-ok">
          <div class="monitor-summary-value">{summaryCounts.ok}</div>
          <div class="monitor-summary-label">{$t('monitor.ok')}</div>
        </div>
        <div class="monitor-summary-card monitor-summary-warning">
          <div class="monitor-summary-value">{summaryCounts.warning}</div>
          <div class="monitor-summary-label">{$t('monitor.warning')}</div>
        </div>
        <div class="monitor-summary-card monitor-summary-critical">
          <div class="monitor-summary-value">{summaryCounts.critical}</div>
          <div class="monitor-summary-label">{$t('monitor.critical')}</div>
        </div>
      </div>

      {#if filteredChecks.length === 0}
        <EmptyState message={$t('page.monitoring.empty')} />
      {:else}
        <div style="display:flex;flex-direction:column;gap:12px">
          {#each checkGroups as group (group.key)}
            {@const open = expandedServers[group.key] ?? false}
            <div class="server-card">
              <div
                class="server-card-header"
                role="button"
                tabindex="0"
                onclick={() => toggleServer(group.key)}
                onkeydown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') toggleServer(group.key);
                }}
              >
                <div style="display:flex;align-items:center;gap:10px;flex:1;min-width:0">
                  <span class="server-chevron" class:rotated={open}>&#x25B6;</span>
                  <span class="monitor-dot monitor-{group.worst}"></span>
                  <strong>{group.title}</strong>
                  <span style="color:var(--text-muted);font-size:12px">
                    {group.checks.length !== 1
                      ? $t('monitor.checkCountPlural', { count: group.checks.length })
                      : $t('monitor.checkCount', { count: group.checks.length })}
                  </span>
                </div>
              </div>
              {#if open}
                <div class="server-card-body">
                  <table class="data-table" style="margin:0">
                    <thead>
                      <tr>
                        <th></th>
                        <th>{$t('label.type')}</th>
                        <th>{$t('label.name')}</th>
                        <th>{$t('label.status')}</th>
                        <th>{$t('monitor.lastCheck')}</th>
                        <th>{$t('label.actions')}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {#each group.checks as c (c.id)}
                        {@const st = c.state?.status ?? 'pending'}
                        {@const msg = c.state?.message ?? '\u2013'}
                        {@const last = c.state?.lastCheck
                          ? formatTime(c.state.lastCheck, $language)
                          : $t('monitor.neverChecked')}
                        <tr
                          class="check-row"
                          style="cursor:pointer"
                          onclick={() => toggleCheckRow(c.id)}
                        >
                          <td><span class="monitor-dot monitor-{st}"></span></td>
                          <td>
                            <span class="badge badge-{c.checkType}">
                              {c.checkType.toUpperCase()}
                            </span>
                          </td>
                          <td>
                            <strong>{c.name}</strong>
                            {#if c.templateId}
                              <span class="badge badge-tpl" title="Von Template verwaltet">TPL</span
                              >
                            {/if}
                          </td>
                          <td
                            style="max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--text-muted)"
                          >
                            {msg}
                          </td>
                          <td style="color:var(--text-muted);font-size:12px">{last}</td>
                          <td style="white-space:nowrap" onclick={(e) => e.stopPropagation()}>
                            <button
                              class="btn small"
                              title={$t('monitor.runNow')}
                              onclick={() => runCheckNow(c)}>&#x25B6;</button
                            >
                            <button class="btn small" onclick={() => editCheck(c)}>
                              {$t('action.edit')}
                            </button>
                            <button class="btn small ghost" onclick={() => toggleCheck(c)}>
                              {c.enabled ? $t('action.disable') : $t('action.enable')}
                            </button>
                            <button class="btn small ghost" onclick={() => removeCheck(c)}>
                              {$t('action.delete')}
                            </button>
                          </td>
                        </tr>
                        {#if expandedCheckId === c.id}
                          <tr class="check-detail-row">
                            <td colspan="6">
                              <CheckDetail check={c} />
                            </td>
                          </tr>
                        {/if}
                      {/each}
                    </tbody>
                  </table>
                </div>
              {/if}
            </div>
          {/each}
        </div>
      {/if}
    </div>
  {/if}

  <!-- Tab: Alert-Rules -->
  {#if activeTab === 'alerts'}
    <div class="monitor-tab-content active">
      <div style="display:flex;justify-content:flex-end;margin-bottom:12px">
        <Button variant="primary" onclick={openCreateAlert}>{$t('page.alerts.add')}</Button>
      </div>
      {#if $alertRules.length === 0}
        <EmptyState message={$t('page.alerts.empty')} />
      {:else}
        <table class="data-table" style="margin:0">
          <thead>
            <tr>
              <th>{$t('label.name')}</th>
              <th>{$t('modal.alert.channel')}</th>
              <th>Filter</th>
              <th>Cooldown</th>
              <th>{$t('label.actions')}</th>
            </tr>
          </thead>
          <tbody>
            {#each $alertRules as r (r.id)}
              <tr class:disabled-row={!r.enabled}>
                <td><strong>{r.name}</strong></td>
                <td>
                  <span class="badge badge-{r.channel}">
                    {r.channel === 'webhook'
                      ? $t('alerts.channel.webhook')
                      : $t('alerts.channel.email')}
                  </span>
                </td>
                <td style="color:var(--text-muted)">{alertFilterLabel(r)}</td>
                <td style="color:var(--text-muted)">
                  {$t('alerts.cooldown', { min: r.cooldownMinutes })}
                </td>
                <td style="white-space:nowrap">
                  <button class="btn small" onclick={() => editAlert(r)}>
                    {$t('action.edit')}
                  </button>
                  <button class="btn small ghost" onclick={() => toggleAlert(r)}>
                    {r.enabled ? $t('action.disable') : $t('action.enable')}
                  </button>
                  <button class="btn small ghost" onclick={() => removeAlert(r)}>
                    {$t('action.delete')}
                  </button>
                </td>
              </tr>
            {/each}
          </tbody>
        </table>
      {/if}
    </div>
  {/if}

  <!-- Tab: Alert-Log -->
  {#if activeTab === 'log'}
    <div class="monitor-tab-content active">
      <div style="display:flex;justify-content:flex-end;margin-bottom:12px">
        <button class="btn small" onclick={refreshLog}>{$t('action.refresh')}</button>
      </div>
      <table class="data-table">
        <thead>
          <tr>
            <th>{$t('alertLog.time')}</th>
            <th>{$t('alertLog.check')}</th>
            <th>{$t('alertLog.from')}</th>
            <th>{$t('alertLog.to')}</th>
            <th>{$t('alertLog.status')}</th>
            <th>{$t('alertLog.error')}</th>
          </tr>
        </thead>
        <tbody>
          {#if $alertLog.length === 0}
            <tr>
              <td colspan="6" style="text-align:center;color:var(--text-muted)">
                {logLoaded ? $t('alerts.noAlerts') : $t('alerts.loadOnTab')}
              </td>
            </tr>
          {:else}
            {#each $alertLog as l (l.id)}
              {@const check = $monitorChecks.find((c) => c.id === l.checkId)}
              {@const checkName = check ? check.name : l.checkId.substring(0, 8)}
              <tr>
                <td style="font-size:12px;color:var(--text-muted)">
                  {formatTime(l.sentAt, $language)}
                </td>
                <td>{checkName}</td>
                <td>
                  <span class="monitor-dot monitor-{l.oldStatus}"></span>
                  {l.oldStatus}
                </td>
                <td>
                  <span class="monitor-dot monitor-{l.newStatus}"></span>
                  {l.newStatus}
                </td>
                <td>
                  {#if l.success}
                    <span style="color:var(--green)">{$t('alerts.sent')}</span>
                  {:else}
                    <span style="color:var(--red)">{$t('alerts.error')}</span>
                  {/if}
                </td>
                <td style="font-size:12px;color:var(--text-muted)">{l.error ?? '\u2013'}</td>
              </tr>
            {/each}
          {/if}
        </tbody>
      </table>
    </div>
  {/if}

  <!-- Tab: Templates -->
  {#if activeTab === 'templates'}
    <div class="monitor-tab-content active">
      <div style="display:flex;justify-content:flex-end;margin-bottom:12px">
        <Button variant="primary" onclick={openCreateTemplate}>
          {$t('page.templates.add')}
        </Button>
      </div>
      {#if $monitoringTemplates.length === 0}
        <EmptyState message={$t('page.templates.empty')} />
      {:else}
        <table class="data-table" style="margin:0">
          <thead>
            <tr>
              <th>{$t('label.name')}</th>
              <th>{$t('label.description')}</th>
              <th>{$t('label.details')}</th>
              <th>Server</th>
              <th>{$t('label.actions')}</th>
            </tr>
          </thead>
          <tbody>
            {#each $monitoringTemplates as tpl (tpl.id)}
              {@const checkCount = (tpl.checkDefinitions ?? []).length}
              {@const alertCount = (tpl.alertDefinitions ?? []).length}
              {@const serverCount = (tpl.assignments ?? []).length}
              {@const serverNames =
                (tpl.assignments ?? []).map((a) => a.serverName ?? a.serverId).join(', ') ||
                '\u2013'}
              <tr>
                <td><strong>{tpl.name}</strong></td>
                <td style="color:var(--text-muted)">{tpl.description ?? ''}</td>
                <td>
                  {$t('template.checks', { count: checkCount, alerts: alertCount })}
                </td>
                <td style="color:var(--text-muted);font-size:12px" title={serverNames}>
                  {$t('template.servers', { count: serverCount })}
                </td>
                <td style="white-space:nowrap">
                  <button class="btn small" onclick={() => editTemplate(tpl)}>
                    {$t('action.edit')}
                  </button>
                  <button class="btn small ghost" onclick={() => removeTemplate(tpl)}>
                    {$t('action.delete')}
                  </button>
                </td>
              </tr>
            {/each}
          </tbody>
        </table>
      {/if}
    </div>
  {/if}
</div>

<MonitorCheckModal open={checkModalOpen} editing={editingCheck} onClose={closeCheckModal} />
<AlertRuleModal open={alertModalOpen} editing={editingAlert} onClose={closeAlertModal} />
<MonitoringTemplateModal
  open={templateModalOpen}
  editing={editingTemplate}
  onClose={closeTemplateModal}
/>

<style>
  .server-chevron {
    display: inline-block;
    transition: transform 0.15s ease;
  }
  .server-chevron.rotated {
    transform: rotate(90deg);
  }
</style>
