<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import { onMount } from 'svelte';
  import { navigate } from '$lib/router';
  import {
    connections,
    load as loadConnections,
    countByKind,
    recentConnections,
  } from '$lib/stores/connections';
  import { timeAgo } from '$lib/utils/timeAgo';
  import type { Connection } from '$lib/bridge/types';
  import { initiateConnect } from '$lib/stores/connectFlow';
  import { openEditor } from '$lib/stores/editor';
  import { t } from '$lib/i18n';

  let stats = $state({ total: 0, ssh: 0, rdp: 0, web: 0 });
  let recent = $state<Connection[]>([]);

  function refresh(): void {
    stats = countByKind();
    recent = recentConnections(5);
  }

  onMount(async () => {
    await loadConnections();
    refresh();
  });

  connections.subscribe(refresh);

  function kindColor(kind: Connection['kind']): string {
    if (kind === 'ssh') return 'var(--accent)';
    if (kind === 'rdp') return 'var(--warning)';
    return 'var(--success)';
  }

  function onConnect(c: Connection): void {
    void initiateConnect(c);
  }
</script>

<div class="dash-stats">
  <div class="stat-card --accent">
    <div class="stat-value">{stats.total}</div>
    <div class="stat-label">{$t('dashboard.total')}</div>
  </div>
  <div class="stat-card">
    <div class="stat-value">{stats.ssh}</div>
    <div class="stat-label">{$t('dashboard.ssh')}</div>
  </div>
  <div class="stat-card">
    <div class="stat-value">{stats.rdp}</div>
    <div class="stat-label">{$t('dashboard.rdp')}</div>
  </div>
  <div class="stat-card">
    <div class="stat-value">{stats.web}</div>
    <div class="stat-label">{$t('dashboard.web')}</div>
  </div>
</div>

<div class="dash-grid">
  <div class="dash-panel">
    <div class="dash-panel-title">{$t('dashboard.recent')}</div>
    {#if recent.length > 0}
      <div class="dash-list">
        {#each recent as conn (conn.id)}
          <div
            class="dash-list-item"
            role="button"
            tabindex="0"
            onclick={() => onConnect(conn)}
            onkeydown={(e) => e.key === 'Enter' && onConnect(conn)}
          >
            <div class="dash-list-item-dot" style="background: {kindColor(conn.kind)}"></div>
            <div class="dash-list-item-name">{conn.name || conn.host || '-'}</div>
            <span class="mon-type-badge" style="font-size: 10px">
              {conn.kind.toUpperCase()}
            </span>
            <div class="dash-list-item-meta">{timeAgo(conn.lastUsed)}</div>
          </div>
        {/each}
      </div>
    {:else}
      <div class="dash-empty">{$t('dashboard.empty')}</div>
    {/if}
  </div>
</div>

<div class="dash-actions">
  <button class="btn primary" onclick={() => openEditor(null)}>
    {$t('connections.new')}
  </button>
  <button class="btn" onclick={() => navigate('/connections')}>
    {$t('dashboard.toList')}
  </button>
</div>
