<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import { onMount } from 'svelte';
  import { Activity, Cable, History, List, Plus } from '@lucide/svelte';
  import { navigate } from '$lib/router';
  import {
    loadForCurrentMode as loadConnections,
    kindCounts,
    recentConnections,
    loading,
  } from '$lib/stores/connections';
  import { sessionStore } from '$lib/stores/session';
  import {
    loadMonitoring,
    loadServers,
    monitoringChecks,
    monitoringServers,
    monitoringHasLoaded,
    monitoringError,
    setSelectedServer,
    setOverviewView,
  } from '$lib/stores/monitoring';
  import { tunnel, tunnelMappings } from '$lib/stores/tunnel';
  import { computeSummary, groupChecksByServerWithSummary } from '$lib/models/monitoring';
  import ConnectionsLoadError from '../components/ConnectionsLoadError.svelte';
  import MonHeartbeatBar from '../components/monitoring/MonHeartbeatBar.svelte';
  import Panel from '../components/ui/Panel.svelte';
  import Pill from '../components/ui/Pill.svelte';
  import Button from '../components/ui/Button.svelte';
  import Dot from '../components/ui/Dot.svelte';
  import { timeAgo } from '$lib/utils/timeAgo';
  import type { Connection } from '$lib/bridge/types';
  import type { MonitorCheck } from '$lib/api/types';
  import { initiateConnect } from '$lib/stores/connectFlow';
  import { openEditor } from '$lib/stores/editor';
  import { t } from '$lib/i18n';

  // Servers, monitoring and tunnels exist only against a hub; local and sync show connections.
  let serverMode = $derived(
    $sessionStore.settings?.mode === 'server' && Boolean($sessionStore.session),
  );

  onMount(() => {
    void loadConnections();
    if (serverMode) void loadServers().then(() => loadMonitoring());
  });

  let enabledChecks = $derived($monitoringChecks.filter((c) => c.enabled !== false));
  let summary = $derived(computeSummary(enabledChecks));
  let problems = $derived(summary.critical + summary.warning);
  // A failed load leaves no checks behind: zero problems would read as a healthy monitoring.
  let monitoringKnown = $derived($monitoringHasLoaded && !$monitoringError);
  let agentServers = $derived(
    new Set(enabledChecks.filter((c) => c.checkType === 'agent_ping').map((c) => c.serverId)).size,
  );
  let problemServers = $derived(
    groupChecksByServerWithSummary(enabledChecks, $monitoringServers).filter(
      (g) => g.worst === 'critical' || g.worst === 'warning',
    ),
  );
  let activeTunnels = $derived($tunnelMappings.filter((m) => m.enabled));

  function heartbeatOf(checks: MonitorCheck[]): string | null {
    return checks.find((c) => c.checkType === 'agent_ping')?.id ?? null;
  }

  function openServer(key: string): void {
    setSelectedServer(key);
    setOverviewView('list');
    navigate('/monitoring');
  }

  function target(c: Connection): string {
    return (c.kind === 'web' ? c.url : c.host) || '-';
  }
</script>

<ConnectionsLoadError />

<div class="dash">
  <div class="dash-cards">
    <div class="dash-card" data-card="connections">
      <div class="dash-card-label">{$t('dashboard.total')}</div>
      <div class="dash-card-value">{$kindCounts.total}</div>
      <div class="dash-card-hint">
        {$t('dashboard.kindHint', {
          ssh: $kindCounts.ssh,
          rdp: $kindCounts.rdp,
          web: $kindCounts.web,
        })}
      </div>
    </div>
    {#if serverMode}
      <div class="dash-card" data-card="servers">
        <div class="dash-card-label">{$t('dashboard.servers')}</div>
        <div class="dash-card-value">{$monitoringServers.length}</div>
        <div class="dash-card-hint">{$t('dashboard.serversHint', { count: agentServers })}</div>
      </div>
      <div class="dash-card" data-card="problems" class:has-problems={problems > 0}>
        <div class="dash-card-label">{$t('dashboard.problems')}</div>
        <div class="dash-card-value">{monitoringKnown ? problems : '-'}</div>
        <div class="dash-card-hint">{$t('dashboard.problemsHint')}</div>
      </div>
    {/if}
  </div>

  <div class="dash-panels">
    <Panel title={$t('dashboard.recent')} icon={History} pad={8}>
      <div data-panel="recent">
        {#if $recentConnections.length > 0}
          <ul class="dash-rows">
            {#each $recentConnections as conn (conn.id)}
              <li class="dash-row">
                <span class="dash-row-name">{conn.name || target(conn)}</span>
                <span class="dash-row-target">{target(conn)}</span>
                <Pill tone={conn.kind === 'ssh' ? 'accent' : 'muted'}
                  >{conn.kind.toUpperCase()}</Pill
                >
                <span class="dash-row-meta">{timeAgo(conn.lastUsed, $t)}</span>
                <Button variant="secondary" size="sm" onclick={() => void initiateConnect(conn)}>
                  {$t('action.connect')}
                </Button>
              </li>
            {/each}
          </ul>
        {:else if $loading}
          <div class="dash-empty">{$t('loading.generic')}</div>
        {:else}
          <div class="dash-empty">{$t('dashboard.empty')}</div>
        {/if}
      </div>
    </Panel>

    {#if serverMode}
      <Panel title={$t('dashboard.monitoring')} icon={Activity} pad={8}>
        {#snippet action()}
          <Button variant="ghost" size="sm" onclick={() => navigate('/monitoring')}>
            {$t('dashboard.showAll')}
          </Button>
        {/snippet}
        <div data-panel="monitoring">
          {#if $monitoringError}
            <div class="dash-empty dash-error" role="alert">
              {$t('error.monitoring', { message: $monitoringError })}
            </div>
          {:else if $monitoringHasLoaded}
            <div class="dash-pills">
              <Pill tone="crit">{$t('dashboard.pillCrit', { count: summary.critical })}</Pill>
              <Pill tone="warn">{$t('dashboard.pillWarn', { count: summary.warning })}</Pill>
              <Pill tone="ok">{$t('dashboard.pillOk', { count: summary.ok })}</Pill>
            </div>
            {#if problemServers.length > 0}
              <ul class="dash-rows">
                {#each problemServers as g (g.key)}
                  {@const hb = heartbeatOf(g.checks)}
                  <li class="dash-row" data-server={g.key}>
                    <Dot st={g.worst} label={$t(`monitoring.status.${g.worst}`)} />
                    <span class="dash-row-name">{g.serverName}</span>
                    {#if hb}<span class="dash-row-bar"><MonHeartbeatBar checkId={hb} /></span>{/if}
                    <Button variant="ghost" size="sm" onclick={() => openServer(g.key)}>
                      {$t('dashboard.open')}
                    </Button>
                  </li>
                {/each}
              </ul>
            {:else}
              <div class="dash-empty">{$t('dashboard.noProblems')}</div>
            {/if}
          {:else}
            <div class="dash-empty">{$t('loading.generic')}</div>
          {/if}
        </div>
      </Panel>

      <Panel title={$t('dashboard.tunnel')} icon={Cable} pad={8}>
        <div data-panel="tunnel">
          {#if activeTunnels.length > 0}
            <ul class="dash-rows">
              {#each activeTunnels as m (m.id)}
                <li class="dash-row">
                  <Dot st={$tunnel.ui} />
                  <span class="dash-row-name">{m.name}</span>
                  <span class="dash-row-target">
                    {m.visitorPort
                      ? `127.0.0.1:${m.visitorPort} → :${m.localPort}`
                      : `:${m.localPort}`}
                  </span>
                  <Pill>{m.tunnelType.toUpperCase()}</Pill>
                </li>
              {/each}
            </ul>
          {:else}
            <div class="dash-empty">{$t('dashboard.noTunnels')}</div>
          {/if}
        </div>
      </Panel>
    {/if}
  </div>

  <div class="dash-buttons">
    <Button variant="primary" iconLeft={Plus} onclick={() => openEditor(null)}>
      {$t('connections.new')}
    </Button>
    <Button variant="secondary" iconLeft={List} onclick={() => navigate('/connections')}>
      {$t('dashboard.toList')}
    </Button>
  </div>
</div>

<style>
  .dash {
    display: flex;
    flex-direction: column;
    gap: var(--space-5);
  }
  .dash-cards {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
    gap: var(--space-3);
  }
  .dash-card {
    padding: var(--space-4) var(--space-5);
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    background: var(--surface);
  }
  .dash-card-label {
    color: var(--text-muted);
    font-size: var(--text-xs);
    font-weight: 600;
    letter-spacing: 0.06em;
    text-transform: uppercase;
  }
  .dash-card-value {
    margin-top: var(--space-1);
    color: var(--text-strong);
    font-family: var(--font-mono);
    font-size: 30px;
    font-variant-numeric: tabular-nums;
    line-height: 1.1;
  }
  .dash-card.has-problems .dash-card-value {
    color: var(--danger);
  }
  .dash-card-hint {
    margin-top: var(--space-1);
    color: var(--text-subtle);
    font-size: var(--text-sm);
  }
  .dash-panels {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(min(100%, 420px), 1fr));
    gap: var(--space-4);
  }
  .dash-rows {
    display: flex;
    flex-direction: column;
    gap: 2px;
    margin: 0;
    padding: 0;
    list-style: none;
  }
  .dash-row {
    display: flex;
    align-items: center;
    gap: var(--space-3);
    min-width: 0;
    padding: var(--space-2);
    border-radius: var(--radius-sm);
    font-size: var(--text-sm);
  }
  .dash-row:hover {
    background: var(--surface-raised);
  }
  .dash-row-name {
    flex: 1;
    min-width: 0;
    overflow: hidden;
    color: var(--text-strong);
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .dash-row-target {
    overflow: hidden;
    color: var(--text-muted);
    font-family: var(--font-mono);
    font-size: var(--text-xs);
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .dash-row-meta {
    color: var(--text-subtle);
    font-size: var(--text-xs);
    white-space: nowrap;
  }
  .dash-row-bar {
    flex: 1;
    min-width: 80px;
  }
  .dash-pills {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-2);
    padding: var(--space-2);
  }
  .dash-error {
    color: var(--danger);
  }
  .dash-buttons {
    display: flex;
    gap: var(--space-2);
  }
</style>
