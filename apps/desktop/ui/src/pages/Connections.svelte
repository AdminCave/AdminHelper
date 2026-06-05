<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import { onMount } from 'svelte';
  import {
    filteredConnections,
    groupedConnections,
    kindFilter,
    groupFilter,
    viewMode,
    load as loadConnections,
    connections,
  } from '$lib/stores/connections';
  import { tunnelMappings } from '$lib/stores/tunnel';
  import { toCardMeta, groupedTagKeys, type ConnectionGroup } from '$lib/models/connection';
  import type { Connection, ConnectionKind } from '$lib/bridge/types';
  import { openEditor } from '$lib/stores/editor';
  import { initiateConnect } from '$lib/stores/connectFlow';
  import { t } from '$lib/i18n';
  import { accelerateScroll, LIST_FACTOR } from '$lib/utils/scrollAcceleration';

  onMount(async () => {
    await loadConnections();
  });

  type Chip = 'single' | 'grouped' | 'ssh' | 'rdp' | 'web';

  let activeChip = $derived<Chip>($kindFilter !== 'all' ? ($kindFilter as Chip) : $groupFilter);

  function setChip(chip: Chip): void {
    if (chip === 'single' || chip === 'grouped') {
      groupFilter.set(chip);
      kindFilter.set('all');
    } else {
      groupFilter.set('single');
      kindFilter.set(chip);
    }
  }

  function onCardClick(conn: Connection, ev: MouseEvent | KeyboardEvent): void {
    const target = ev.target as HTMLElement;
    if (target.closest('button')) return;
    void initiateConnect(conn);
  }

  function onGroupClick(group: ConnectionGroup, ev: MouseEvent | KeyboardEvent): void {
    const target = ev.target as HTMLElement;
    if (target.closest('button')) return;
    const preferred =
      group.byKind.ssh ?? group.byKind.rdp ?? group.byKind.web ?? group.connections[0];
    if (preferred) void initiateConnect(preferred);
  }

  function onConnect(conn: Connection, event: MouseEvent | KeyboardEvent): void {
    event.stopPropagation();
    event.preventDefault();
    void initiateConnect(conn);
  }

  function onEdit(conn: Connection, event: MouseEvent | KeyboardEvent): void {
    event.stopPropagation();
    event.preventDefault();
    openEditor(conn);
  }

  function tunnelFor(conn: Connection): string | null {
    const match = $tunnelMappings.find((m) => m.enabled && m.connectionId === conn.id);
    return match ? match.name : null;
  }

  let counter = $derived(
    $groupFilter === 'grouped' ? $groupedConnections.length : $filteredConnections.length,
  );

  interface TreeNode {
    tag: string;
    items: Connection[];
    groups: ConnectionGroup[];
  }

  let treeNodes = $derived.by<TreeNode[]>(() => {
    const untagged = $t('tree.untagged');
    const m = new Map<string, TreeNode>();
    if ($groupFilter === 'grouped') {
      for (const grp of $groupedConnections) {
        const tags = groupedTagKeys(grp, untagged);
        for (const tag of tags) {
          const key = tag.trim() || untagged;
          if (!m.has(key)) m.set(key, { tag: key, items: [], groups: [] });
          m.get(key)!.groups.push(grp);
        }
      }
    } else {
      for (const conn of $filteredConnections) {
        const tags = conn.tags && conn.tags.length > 0 ? conn.tags : [untagged];
        for (const tag of tags) {
          const key = tag.trim() || untagged;
          if (!m.has(key)) m.set(key, { tag: key, items: [], groups: [] });
          m.get(key)!.items.push(conn);
        }
      }
    }
    return Array.from(m.values()).sort((a, b) => a.tag.localeCompare(b.tag));
  });

  let openTags = $state<Record<string, boolean>>({});
  function toggleTag(tag: string): void {
    openTags = { ...openTags, [tag]: !(openTags[tag] ?? true) };
  }
  function isOpen(tag: string): boolean {
    return openTags[tag] ?? true;
  }

  const PENCIL_PATH =
    'M3 17.25V21h3.75L17.81 9.94l-3.75-3.75L3 17.25zM20.71 7.04c.39-.39.39-1.02 0-1.41l-2.34-2.34a.996.996 0 0 0-1.41 0l-1.83 1.83 3.75 3.75 1.83-1.83z';
</script>

<div class="section-toolbar">
  <div class="toolbar-left">
    <div class="filters">
      <button class="chip" class:active={activeChip === 'single'} onclick={() => setChip('single')}
        >{$t('filters.single')}</button
      >
      <button
        class="chip"
        class:active={activeChip === 'grouped'}
        onclick={() => setChip('grouped')}>{$t('filters.grouped')}</button
      >
      <button class="chip" class:active={activeChip === 'ssh'} onclick={() => setChip('ssh')}
        >{$t('filters.ssh')}</button
      >
      <button class="chip" class:active={activeChip === 'rdp'} onclick={() => setChip('rdp')}
        >{$t('filters.rdp')}</button
      >
      <button class="chip" class:active={activeChip === 'web'} onclick={() => setChip('web')}
        >{$t('filters.web')}</button
      >
    </div>
    <div class="view-toggle">
      <button class="chip" class:active={$viewMode === 'list'} onclick={() => viewMode.set('list')}
        >{$t('view.list')}</button
      >
      <button class="chip" class:active={$viewMode === 'tree'} onclick={() => viewMode.set('tree')}
        >{$t('view.tree')}</button
      >
    </div>
  </div>
  <div class="toolbar-right">
    <div class="counter">{counter}</div>
    <button class="btn primary" onclick={() => openEditor(null)}>{$t('connections.new')}</button>
  </div>
</div>

{#if $connections.length === 0}
  <div class="list" use:accelerateScroll={LIST_FACTOR}>
    <div class="dash-empty" style="padding: var(--sp-6);">{$t('connections.empty')}</div>
  </div>
{:else if $viewMode === 'list' && $groupFilter === 'single'}
  <div class="list" use:accelerateScroll={LIST_FACTOR}>
    {#if $filteredConnections.length === 0}
      <div class="dash-empty" style="padding: var(--sp-6);">{$t('connections.noResults')}</div>
    {:else}
      {#each $filteredConnections as conn (conn.id)}
        {@const tunnelName = tunnelFor(conn)}
        <div
          class="card"
          role="button"
          tabindex="0"
          onclick={(e) => onCardClick(conn, e)}
          onkeydown={(e) => e.key === 'Enter' && onCardClick(conn, e)}
        >
          <div class="card-main">
            <div class="card-title">{conn.name || $t('list.noName')}</div>
            <div class="card-meta">{toCardMeta(conn)}</div>
            <div class="card-tag">{conn.kind.toUpperCase()}</div>
            {#if tunnelName}
              <div class="card-tag tunnel-badge" title={tunnelName}>{$t('tunnel.badge')}</div>
            {/if}
            {#if conn.tags && conn.tags.length > 0}
              <div class="card-tags">
                {#each conn.tags as tag}
                  <span class="tag">{tag}</span>
                {/each}
              </div>
            {/if}
          </div>
          <div class="card-actions">
            <button
              class="btn icon large"
              title={$t('action.edit')}
              aria-label={$t('action.edit')}
              onclick={(e) => onEdit(conn, e)}
            >
              <svg viewBox="0 0 24 24"><path d={PENCIL_PATH} /></svg>
            </button>
          </div>
        </div>
      {/each}
    {/if}
  </div>
{:else if $viewMode === 'list' && $groupFilter === 'grouped'}
  <div class="list" use:accelerateScroll={LIST_FACTOR}>
    {#if $groupedConnections.length === 0}
      <div class="dash-empty" style="padding: var(--sp-6);">{$t('connections.noResults')}</div>
    {:else}
      {#each $groupedConnections as group (group.key)}
        {@const preferred =
          group.byKind.ssh ?? group.byKind.rdp ?? group.byKind.web ?? group.connections[0]}
        <div
          class="card"
          role="button"
          tabindex="0"
          onclick={(e) => onGroupClick(group, e)}
          onkeydown={(e) => e.key === 'Enter' && onGroupClick(group, e)}
        >
          <div class="card-main">
            <div class="card-title">{group.displayName || $t('list.noName')}</div>
            <div class="card-meta">
              {group.host} · {$t('grouped.connections', { count: group.connections.length })}
            </div>
            <div class="card-tag">
              {['ssh', 'rdp', 'web']
                .filter((k) => group.byKind[k as ConnectionKind])
                .map((k) => k.toUpperCase())
                .join(' · ')}
            </div>
          </div>
          <div class="card-actions">
            {#each ['ssh', 'rdp', 'web'] as kind}
              {#if group.byKind[kind as ConnectionKind]}
                <button
                  class="btn small accent"
                  onclick={(e) => onConnect(group.byKind[kind as ConnectionKind]!, e)}
                  >{kind.toUpperCase()}</button
                >
              {/if}
            {/each}
            {#if preferred}
              <button
                class="btn icon large"
                title={$t('action.edit')}
                aria-label={$t('action.edit')}
                onclick={(e) => onEdit(preferred, e)}
              >
                <svg viewBox="0 0 24 24"><path d={PENCIL_PATH} /></svg>
              </button>
            {/if}
          </div>
        </div>
      {/each}
    {/if}
  </div>
{:else}
  <div class="tree" use:accelerateScroll={LIST_FACTOR}>
    {#if treeNodes.length === 0}
      <div class="dash-empty" style="padding: var(--sp-6);">{$t('connections.noResults')}</div>
    {:else}
      {#each treeNodes as node (node.tag)}
        <div class="tree-group" class:open={isOpen(node.tag)}>
          <div
            class="tree-header"
            role="button"
            tabindex="0"
            onclick={() => toggleTag(node.tag)}
            onkeydown={(e) => e.key === 'Enter' && toggleTag(node.tag)}
          >
            <div class="tree-tag">{node.tag}</div>
            <div class="tree-toggle">
              <span class="tree-count">
                {$t('tree.connections', {
                  count: $groupFilter === 'grouped' ? node.groups.length : node.items.length,
                })}
              </span>
            </div>
          </div>
          <div class="tree-list">
            {#if $groupFilter === 'grouped'}
              {#each node.groups as group (group.key)}
                {@const preferred =
                  group.byKind.ssh ?? group.byKind.rdp ?? group.byKind.web ?? group.connections[0]}
                <div class="tree-node">
                  <div
                    class="card"
                    role="button"
                    tabindex="0"
                    onclick={(e) => onGroupClick(group, e)}
                    onkeydown={(e) => e.key === 'Enter' && onGroupClick(group, e)}
                  >
                    <div class="card-main">
                      <div class="card-title">{group.displayName || $t('list.noName')}</div>
                      <div class="card-meta">
                        {group.host} · {$t('grouped.connections', {
                          count: group.connections.length,
                        })}
                      </div>
                      <div class="card-tag">
                        {['ssh', 'rdp', 'web']
                          .filter((k) => group.byKind[k as ConnectionKind])
                          .map((k) => k.toUpperCase())
                          .join(' · ')}
                      </div>
                    </div>
                    <div class="card-actions">
                      {#each ['ssh', 'rdp', 'web'] as kind}
                        {#if group.byKind[kind as ConnectionKind]}
                          <button
                            class="btn small accent"
                            onclick={(e) => onConnect(group.byKind[kind as ConnectionKind]!, e)}
                            >{kind.toUpperCase()}</button
                          >
                        {/if}
                      {/each}
                      {#if preferred}
                        <button
                          class="btn icon large"
                          title={$t('action.edit')}
                          aria-label={$t('action.edit')}
                          onclick={(e) => onEdit(preferred, e)}
                        >
                          <svg viewBox="0 0 24 24"><path d={PENCIL_PATH} /></svg>
                        </button>
                      {/if}
                    </div>
                  </div>
                </div>
              {/each}
            {:else}
              {#each node.items as conn (conn.id)}
                {@const tunnelName = tunnelFor(conn)}
                <div class="tree-node">
                  <div
                    class="card"
                    role="button"
                    tabindex="0"
                    onclick={(e) => onCardClick(conn, e)}
                    onkeydown={(e) => e.key === 'Enter' && onCardClick(conn, e)}
                  >
                    <div class="card-main">
                      <div class="card-title">{conn.name || $t('list.noName')}</div>
                      <div class="card-meta">{toCardMeta(conn)}</div>
                      <div class="card-tag">{conn.kind.toUpperCase()}</div>
                      {#if tunnelName}
                        <div class="card-tag tunnel-badge" title={tunnelName}>
                          {$t('tunnel.badge')}
                        </div>
                      {/if}
                    </div>
                    <div class="card-actions">
                      <button
                        class="btn icon large"
                        title={$t('action.edit')}
                        aria-label={$t('action.edit')}
                        onclick={(e) => onEdit(conn, e)}
                      >
                        <svg viewBox="0 0 24 24"><path d={PENCIL_PATH} /></svg>
                      </button>
                    </div>
                  </div>
                </div>
              {/each}
            {/if}
          </div>
        </div>
      {/each}
    {/if}
  </div>
{/if}
