<script lang="ts">
  import { onMount } from 'svelte';
  import {
    filteredConnections,
    kindFilter,
    groupFilter,
    load as loadConnections,
    connections,
  } from '$lib/stores/connections';
  import { timeAgo } from '$lib/utils/timeAgo';
  import type { Connection, ConnectionKind } from '$lib/bridge/types';
  import { openEditor } from '$lib/stores/editor';
  import { initiateConnect } from '$lib/stores/connectFlow';

  onMount(async () => {
    await loadConnections();
  });

  function setKind(k: 'all' | ConnectionKind): void {
    kindFilter.set(k);
  }

  function onConnect(conn: Connection, event: MouseEvent | KeyboardEvent): void {
    event.stopPropagation();
    void initiateConnect(conn);
  }

  function kindBadgeColor(kind: ConnectionKind): string {
    if (kind === 'ssh') return 'var(--accent)';
    if (kind === 'rdp') return 'var(--warning)';
    return 'var(--success)';
  }
</script>

<div class="section-toolbar">
  <div class="toolbar-left">
    <div class="filters">
      <button
        class="chip"
        class:active={$kindFilter === 'all'}
        onclick={() => setKind('all')}>Alle</button>
      <button
        class="chip"
        class:active={$kindFilter === 'ssh'}
        onclick={() => setKind('ssh')}>SSH</button>
      <button
        class="chip"
        class:active={$kindFilter === 'rdp'}
        onclick={() => setKind('rdp')}>RDP</button>
      <button
        class="chip"
        class:active={$kindFilter === 'web'}
        onclick={() => setKind('web')}>Web</button>
    </div>
    <div class="view-toggle">
      <button
        class="chip"
        class:active={$groupFilter === 'single'}
        onclick={() => groupFilter.set('single')}>Einzeln</button>
      <button
        class="chip"
        class:active={$groupFilter === 'grouped'}
        onclick={() => groupFilter.set('grouped')}>Zusammengefasst</button>
    </div>
  </div>
  <div class="toolbar-right">
    <div class="counter">{$filteredConnections.length}</div>
    <button class="btn primary" onclick={() => openEditor(null)}>Neue Verbindung</button>
  </div>
</div>

<div class="list">
  {#if $connections.length === 0}
    <div class="dash-empty" style="padding: var(--sp-6);">
      Noch keine Verbindungen angelegt
    </div>
  {:else if $filteredConnections.length === 0}
    <div class="dash-empty" style="padding: var(--sp-6);">
      Keine Treffer fuer deine Filter
    </div>
  {:else}
    {#each $filteredConnections as conn (conn.id)}
      <div
        class="list-item"
        role="button"
        tabindex="0"
        onclick={() => openEditor(conn)}
        onkeydown={(e) => e.key === 'Enter' && openEditor(conn)}
      >
        <div class="list-item-dot" style="background: {kindBadgeColor(conn.kind)}"></div>
        <div class="list-item-body">
          <div class="list-item-name">{conn.name || conn.host || '-'}</div>
          <div class="list-item-meta">
            {conn.kind.toUpperCase()}
            {#if conn.host}· {conn.host}{/if}
            {#if conn.username}· {conn.username}{/if}
            {#if conn.lastUsed}· {timeAgo(conn.lastUsed)}{/if}
          </div>
          {#if conn.tags && conn.tags.length > 0}
            <div class="list-item-tags">
              {#each conn.tags as tag}
                <span class="tag">{tag}</span>
              {/each}
            </div>
          {/if}
        </div>
        <button
          class="btn primary small"
          onclick={(e) => onConnect(conn, e)}
          onkeydown={(e) => e.key === 'Enter' && onConnect(conn, e)}
        >
          Verbinden
        </button>
      </div>
    {/each}
  {/if}
</div>
