<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import {
    monitoringChecks,
    monitoringServers,
    selectedServerId,
    checkEditor,
    openCheckEditor,
    closeCheckEditor,
    loadMonitoring,
    loadMaintenanceWindows,
    monitoringCatalog,
    monitoringDiscovery,
    monitoringFindings,
    monitoringFindingsError,
    requestScan,
    adoptFinding,
    adoptAllFindings,
    dismissFinding,
  } from '$lib/stores/monitoring';
  import { STATUS_PRIORITY, computeSummary, worstStatus } from '$lib/models/monitoring';
  import { adoptNoteLines, ageText, cardNote, cardSummary } from '$lib/models/monitoringText';
  import type { MonitorCheck, MonitorCheckType, MonitorFinding } from '$lib/api/types';
  import { Plus, RefreshCw, TriangleAlert, Wrench, X } from '@lucide/svelte';
  import Button from '../ui/Button.svelte';
  import Callout from '../ui/Callout.svelte';
  import Dot from '../ui/Dot.svelte';
  import EmptyState from '../ui/EmptyState.svelte';
  import IconButton from '../ui/IconButton.svelte';
  import Pill from '../ui/Pill.svelte';
  import MaintenanceModal from './MaintenanceModal.svelte';
  import MonitorCheckModal from './MonitorCheckModal.svelte';
  import MonHeartbeatBar from './MonHeartbeatBar.svelte';
  import FindingsInbox from './card/FindingsInbox.svelte';
  import ModuleCard from './card/ModuleCard.svelte';
  import MonCard, { opensByDefault } from './card/MonCard.svelte';
  import MonCosts from './card/MonCosts.svelte';
  import SecLive from './section/SecLive.svelte';
  import SecNetwork from './section/SecNetwork.svelte';
  import SecHeartbeat from './section/SecHeartbeat.svelte';
  import SecServices from './section/SecServices.svelte';
  import SecSystem from './section/SecSystem.svelte';
  import SecDocker from './section/SecDocker.svelte';
  import SecBackups from './section/SecBackups.svelte';
  import SecZfs from './section/SecZfs.svelte';
  import SecSmart from './section/SecSmart.svelte';
  import SecForecast from './section/SecForecast.svelte';
  import HistoryPanel from './HistoryPanel.svelte';
  import { t } from '$lib/i18n';

  type CardKind = 'system' | 'services' | 'docker' | 'backups' | 'module';
  interface Card {
    key: string;
    kind: CardKind;
    checks: MonitorCheck[];
    moduleId: string;
    instance: string;
  }

  let selected = $derived($selectedServerId);
  let realServer = $derived(!!selected && selected !== '__none');

  let serverName = $derived.by(() => {
    if (!selected) return '';
    if (selected === '__none') return $t('monitoring.server.noServer');
    const srv = $monitoringServers.find((s) => s.id === selected);
    if (srv) return srv.name || srv.hostname || selected;
    return selected;
  });

  let serverHost = $derived.by(() => {
    if (!selected || selected === '__none') return '';
    const srv = $monitoringServers.find((s) => s.id === selected);
    return srv ? srv.hostname || '' : '';
  });

  let serverChecks = $derived.by(() => {
    if (!selected) return [] as MonitorCheck[];
    return $monitoringChecks.filter((c) => (c.serverId || '__none') === selected);
  });

  let summary = $derived(computeSummary(serverChecks));
  let worst = $derived(worstStatus(serverChecks));
  let worstLabel = $derived(
    {
      ok: $t('monitoring.status.ok'),
      warning: $t('monitoring.status.warning'),
      critical: $t('monitoring.status.critical'),
      unknown: $t('monitoring.status.unknown'),
      pending: $t('monitoring.status.pending'),
    }[worst],
  );
  let problems = $derived(summary.critical + summary.warning + summary.unknown);
  let problemText = $derived(
    problems === 0
      ? $t('monitoring.server.problems.none')
      : problems === 1
        ? $t('monitoring.server.problems.one')
        : $t('monitoring.server.problems.many', { count: problems }),
  );

  let maintOpen = $state(false);

  // Module checks belong to their instance's card whatever their type; the rest go by
  // type into the fixed cards. A probe without a module (made by hand) gets a card of
  // its own rather than none.
  let moduleChecks = $derived(serverChecks.filter((c) => c.moduleId || c.checkType === 'probe'));
  let plainChecks = $derived(serverChecks.filter((c) => !c.moduleId && c.checkType !== 'probe'));

  function pick(type: MonitorCheckType | MonitorCheckType[]): MonitorCheck[] {
    const types = Array.isArray(type) ? type : [type];
    return plainChecks.filter((c) => types.includes(c.checkType));
  }

  let liveChecks = $derived(pick('agent_resources'));
  let networkChecks = $derived(pick(['ping', 'tcp', 'http']));
  let heartbeatChecks = $derived(pick('agent_ping'));
  let serviceChecks = $derived(pick('service_process'));
  let systemChecks = $derived(pick('system_state'));
  let dockerChecks = $derived(pick('docker_health'));
  let backupChecks = $derived(pick('proxmox_backup'));
  let zfsChecks = $derived(pick('zfs_health'));
  let smartChecks = $derived(pick('smart_health'));
  let forecastChecks = $derived(pick('disk_forecast'));
  let systemCardChecks = $derived([
    ...heartbeatChecks,
    ...liveChecks,
    ...networkChecks,
    ...systemChecks,
    ...zfsChecks,
    ...smartChecks,
    ...forecastChecks,
  ]);

  function moduleOf(id: string) {
    return $monitoringCatalog?.modules.find((m) => m.id === id) ?? null;
  }

  let moduleCards = $derived.by(() => {
    const groups: Record<string, Card> = {};
    for (const c of moduleChecks) {
      const moduleId = c.moduleId || c.checkType;
      const instance = c.moduleInstance ?? '';
      const key = `module:${moduleId}/${instance}`;
      const card = groups[key];
      if (card) card.checks.push(c);
      else groups[key] = { key, kind: 'module', checks: [c], moduleId, instance };
    }
    const name = (card: Card) => moduleOf(card.moduleId)?.name ?? card.moduleId;
    return Object.values(groups).sort(
      (a, b) =>
        name(a).localeCompare(name(b)) ||
        a.instance.localeCompare(b.instance, undefined, { numeric: true }),
    );
  });

  // Concept §3.14: problems first (worst first, else in the fixed order), then what was
  // newly found, then the quiet cards in the fixed order.
  let cards = $derived.by(() => {
    const fixed: Card[] = [
      { kind: 'system' as const, checks: systemCardChecks },
      { kind: 'services' as const, checks: serviceChecks },
      { kind: 'docker' as const, checks: dockerChecks },
      { kind: 'backups' as const, checks: backupChecks },
    ]
      .filter((c) => c.checks.length > 0)
      .map((c) => ({ ...c, key: c.kind, moduleId: '', instance: '' }));
    const all = [...fixed, ...moduleCards];
    const rank = (card: Card) => {
      const status = worstStatus(card.checks);
      return opensByDefault(status) ? STATUS_PRIORITY[status] : 0;
    };
    return {
      problems: all.filter((c) => rank(c) > 0).sort((a, b) => rank(b) - rank(a)),
      rest: all.filter((c) => rank(c) === 0),
    };
  });

  // A failed load keeps the old list (the store), so the card stays and says the list
  // is not current; without any list it says the findings cannot be loaded.
  let findings = $derived(
    realServer ? $monitoringFindings.filter((f) => f.serverId === selected) : [],
  );
  let findingsError = $derived(realServer ? $monitoringFindingsError : null);
  let showFindings = $derived(findings.length > 0 || !!findingsError);

  let discovery = $derived(realServer && selected ? $monitoringDiscovery[selected] : undefined);
  let scanInfo = $derived(
    discovery
      ? discovery.scannedAt
        ? $t('monitoring.scan.last', { age: ageText($t, discovery.scannedAt) })
        : $t('monitoring.scan.never')
      : null,
  );
  // Requested and not yet run: the agent picks it up with its next report.
  let scanRequested = $derived(!!discovery?.scanRequestedAt);
  let scanning = $state(false);

  async function scanNow(): Promise<void> {
    if (!selected || !realServer || scanning) return;
    scanning = true;
    try {
      await requestScan(selected);
    } finally {
      scanning = false;
    }
  }

  // What adopting left out (a check the instance cannot carry, a finding that failed)
  // stays visible until closed or the next adopt: the finding itself is gone from the
  // list, so the module card would show fewer checks than the catalog plans, unexplained.
  let adoptNote = $state<{ serverId: string; lines: string[] } | null>(null);
  let adoptLines = $derived(adoptNote?.serverId === selected ? adoptNote.lines : []);

  function showAdoptNote(serverId: string, lines: string[]): void {
    adoptNote = lines.length > 0 ? { serverId, lines } : null;
  }

  async function adopt(f: MonitorFinding): Promise<void> {
    adoptNote = null;
    const result = await adoptFinding(f.id);
    if (result) showAdoptNote(f.serverId, adoptNoteLines($t, [result], [], $monitoringCatalog));
  }
  async function dismiss(f: MonitorFinding): Promise<void> {
    await dismissFinding(f.id);
  }
  async function adoptAll(): Promise<void> {
    if (!selected) return;
    adoptNote = null;
    const serverId = selected;
    const before = findings;
    const result = await adoptAllFindings(serverId);
    if (!result) return;
    showAdoptNote(
      serverId,
      adoptNoteLines($t, result.adopted, result.failed, $monitoringCatalog, before),
    );
  }

  function cardTitle(kind: Exclude<CardKind, 'module'>): string {
    return {
      system: $t('monitoring.card.system'),
      services: $t('monitoring.section.services'),
      docker: $t('monitoring.section.docker'),
      backups: $t('monitoring.section.backups'),
    }[kind];
  }
</script>

{#snippet cardView(card: Card)}
  {#if card.kind === 'module'}
    <ModuleCard
      module={moduleOf(card.moduleId)}
      moduleId={card.moduleId}
      instance={card.instance}
      checks={card.checks}
    />
  {:else}
    <MonCard
      title={cardTitle(card.kind)}
      status={worstStatus(card.checks)}
      summary={cardSummary($t, card.checks)}
      note={cardNote($t, card.checks)}
    >
      <div class="card-sections" class:single={card.kind !== 'system'}>
        {#if card.kind === 'system'}
          {#if liveChecks.length > 0 && selected && selected !== '__none'}
            <HistoryPanel serverId={selected} {serverName} latencyChecks={networkChecks} />
          {/if}
          {#if heartbeatChecks.length > 0}
            <SecHeartbeat checks={heartbeatChecks} />
          {/if}
          {#if liveChecks.length > 0}
            <SecLive checks={liveChecks} />
          {/if}
          {#if networkChecks.length > 0}
            <SecNetwork checks={networkChecks} />
          {/if}
          {#if systemChecks.length > 0}
            <SecSystem checks={systemChecks} />
          {/if}
          {#if zfsChecks.length > 0}
            <SecZfs checks={zfsChecks} />
          {/if}
          {#if smartChecks.length > 0}
            <SecSmart checks={smartChecks} />
          {/if}
          {#if forecastChecks.length > 0}
            <SecForecast checks={forecastChecks} />
          {/if}
        {:else if card.kind === 'services'}
          <SecServices checks={card.checks} serverId={realServer ? selected : null} />
        {:else if card.kind === 'docker'}
          <SecDocker checks={card.checks} />
        {:else}
          <SecBackups checks={card.checks} />
        {/if}
      </div>
    </MonCard>
  {/if}
{/snippet}

<div class="mon-dashboard">
  {#if !selected}
    <div class="mon-panel-empty">
      <span class="mon-panel-empty-icon" aria-hidden="true">⇦</span>
      <span>{$t('monitoring.panel.selectServer')}</span>
    </div>
  {:else}
    <header class="mon-dashboard-head">
      <div class="mon-dashboard-title">
        <Dot st={worst} size={11} ring label={worstLabel} />
        <div class="mon-dashboard-titles">
          <h2 class="mon-dashboard-name">{serverName}</h2>
          {#if serverHost && serverHost !== serverName}
            <span class="mon-dashboard-host">{serverHost}</span>
          {/if}
        </div>
        <div class="mon-dashboard-stats">
          {#if summary.critical > 0}
            <Pill tone="crit">{summary.critical} {$t('monitoring.status.critical')}</Pill>
          {/if}
          {#if summary.warning > 0}
            <Pill tone="warn">{summary.warning} {$t('monitoring.status.warning')}</Pill>
          {/if}
          <Pill tone="ok">{summary.ok} {$t('monitoring.status.ok')}</Pill>
          {#if summary.unknown > 0}
            <Pill>{summary.unknown} {$t('monitoring.status.unknown')}</Pill>
          {/if}
          {#if summary.pending > 0}
            <Pill>{summary.pending} {$t('monitoring.status.pending')}</Pill>
          {/if}
        </div>
        {#if realServer}
          <div class="mon-dashboard-actions">
            <Button
              variant="ghost"
              size="sm"
              iconLeft={RefreshCw}
              data-action="scan-now"
              loading={scanning}
              disabled={scanning || scanRequested}
              onclick={scanNow}
              >{scanRequested ? $t('monitoring.scan.requested') : $t('monitoring.scan.now')}</Button
            >
            <Button
              variant="ghost"
              size="sm"
              iconLeft={Wrench}
              data-action="maintenance-new"
              onclick={() => (maintOpen = true)}>{$t('monitoring.maint.title')}</Button
            >
            <Button
              size="sm"
              iconLeft={Plus}
              data-action="check-new"
              onclick={() => openCheckEditor(null, selected ?? '')}
              >{$t('monitoring.checkEdit.add')}</Button
            >
          </div>
        {/if}
      </div>
      <p class="mon-dashboard-line">
        <span class="mon-dashboard-problems" class:has-problems={problems > 0}>{problemText}</span>
        {#if scanInfo}
          <span class="mon-dashboard-scan">{scanInfo}</span>
        {/if}
      </p>
      {#if heartbeatChecks.length > 0}
        <MonHeartbeatBar checkId={heartbeatChecks[0].id} />
      {/if}
    </header>

    {#if adoptLines.length > 0}
      <div class="adopt-note" role="status">
        <Callout tone="warning" icon={TriangleAlert} title={$t('monitoring.findings.partial')}>
          <ul class="adopt-note-list">
            {#each adoptLines as line, i (i)}
              <li>{line}</li>
            {/each}
          </ul>
          {#snippet action()}
            <IconButton
              icon={X}
              size="sm"
              label={$t('action.close')}
              onclick={() => (adoptNote = null)}
            />
          {/snippet}
        </Callout>
      </div>
    {/if}

    {#if serverChecks.length === 0 && !showFindings}
      <div class="mon-panel-empty-inline">{$t('monitoring.panel.noChecks')}</div>
    {:else}
      {#each cards.problems as card (card.key)}
        {@render cardView(card)}
      {/each}
      {#if showFindings}
        <MonCard
          title={$t('monitoring.card.findings', { count: findings.length })}
          status={null}
          defaultOpen={findings.length > 0}
          note={findingsError ? $t('monitoring.findings.stale', { error: findingsError }) : null}
        >
          {#if findings.length > 0}
            <div class="findings-body">
              <FindingsInbox {findings} onAdopt={adopt} onDismiss={dismiss} onAdoptAll={adoptAll} />
            </div>
          {:else}
            <EmptyState framed={false} message={$t('monitoring.findings.unavailable')} />
          {/if}
        </MonCard>
      {/if}
      {#each cards.rest as card (card.key)}
        {@render cardView(card)}
      {/each}
      {#if realServer && selected}
        <MonCosts serverId={selected} />
      {/if}
    {/if}
  {/if}
</div>

<MonitorCheckModal
  open={$checkEditor.open}
  target={$checkEditor.target}
  serverId={$checkEditor.serverId}
  onClose={closeCheckEditor}
  onSaved={() => void loadMonitoring()}
/>

{#if selected && selected !== '__none'}
  <MaintenanceModal
    open={maintOpen}
    editing={null}
    serverId={selected}
    onClose={() => (maintOpen = false)}
    onSaved={() => void loadMaintenanceWindows()}
  />
{/if}

<style>
  .mon-dashboard {
    display: flex;
    flex-direction: column;
    gap: var(--space-3);
  }
  .mon-dashboard-head {
    display: flex;
    flex-direction: column;
    gap: var(--space-3);
    padding: var(--space-4);
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    background: var(--surface);
  }
  .mon-dashboard-title {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-3);
    min-width: 0;
  }
  .mon-dashboard-titles {
    display: flex;
    flex: 1 1 10rem;
    flex-direction: column;
    gap: var(--space-1);
    min-width: 0;
  }
  .mon-dashboard-name {
    overflow: hidden;
    margin: 0;
    color: var(--text-strong);
    font-size: var(--text-lg);
    font-weight: 600;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .mon-dashboard-host {
    overflow: hidden;
    color: var(--text-subtle);
    font-family: var(--font-mono);
    font-size: var(--text-xs);
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .mon-dashboard-stats,
  .mon-dashboard-actions {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-2);
  }
  .mon-dashboard-line {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-1) var(--space-4);
    margin: 0;
    font-size: var(--text-sm);
  }
  .mon-dashboard-problems {
    color: var(--text-muted);
  }
  .mon-dashboard-problems.has-problems {
    color: var(--text-strong);
    font-weight: 600;
  }
  .mon-dashboard-scan {
    color: var(--text-subtle);
  }
  /* The sections keep their frame elsewhere; inside a card the card is the frame. */
  .card-sections :global(.mon-section) {
    border: 0;
    border-radius: 0;
    background: transparent;
  }
  .card-sections :global(.mon-section + .mon-section) {
    border-top: 1px solid var(--border-faint);
  }
  /* A card of one section already shows its title, dot and count. */
  .card-sections.single :global(.mon-section-head) {
    display: none;
  }
  .card-sections.single :global(.mon-section-body) {
    padding-top: var(--space-2);
  }
  .findings-body {
    padding: var(--space-2) var(--space-4) var(--space-4);
  }
  .adopt-note-list {
    margin: 0;
    padding-left: var(--space-4);
  }
  .mon-panel-empty,
  .mon-panel-empty-inline {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: var(--space-2);
    padding: var(--space-6) var(--space-4);
    border: 1px dashed var(--border);
    border-radius: var(--radius-lg);
    color: var(--text-muted);
    font-size: var(--text-sm);
    text-align: center;
  }
  .mon-panel-empty-icon {
    font-size: var(--text-2xl);
    opacity: 0.5;
  }
</style>
