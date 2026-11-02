<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import { onDestroy, onMount } from 'svelte';
  import { SvelteSet } from 'svelte/reactivity';
  import { LayoutGrid, Plus, Rows3, SearchX } from '@lucide/svelte';
  import {
    connections,
    connectionsStore,
    favorites,
    loadForCurrentMode as loadConnections,
    loading,
    reachability,
    remove,
    searchTerm,
    startReachability,
    toggleFavorite,
    upsert,
  } from '$lib/stores/connections';
  import { save } from '@tauri-apps/plugin-dialog';
  import { deletePassword, writeExportCsv } from '$lib/bridge';
  import { reportError, showStatus } from '$lib/stores/statusBar';
  import { errMsg } from '$lib/utils/errors';
  import {
    connectionsCsv,
    filterConnections,
    groupConnections,
    kindCounts,
    libraryCounts,
    quickAccess,
    sortConnections,
    tagCounts,
    type Grouping,
    type Library,
    type ListContext,
    type SortDir,
    type SortKey,
  } from '$lib/models/connectionList';
  import type { Connection, ConnectionKind } from '$lib/bridge/types';
  import { tunnelMappings } from '$lib/stores/tunnel';
  import { infraServers } from '$lib/stores/infra';
  import { openEditor } from '$lib/stores/editor';
  import { initiateConnect } from '$lib/stores/connectFlow';
  import { t } from '$lib/i18n';
  import { accelerateScroll, LIST_FACTOR } from '$lib/utils/scrollAcceleration';
  import ConnectionsLoadError from '../components/ConnectionsLoadError.svelte';
  import BulkBar from '../components/connections/BulkBar.svelte';
  import ConnectionInspector from '../components/connections/ConnectionInspector.svelte';
  import ConnectionSidebar from '../components/connections/ConnectionSidebar.svelte';
  import ConnectionTable from '../components/connections/ConnectionTable.svelte';
  import QuickAccess from '../components/connections/QuickAccess.svelte';
  import Button from '../components/ui/Button.svelte';
  import { confirmDialog } from '../components/ui/ConfirmDialog.svelte';
  import EmptyState from '../components/ui/EmptyState.svelte';
  import SearchField from '../components/ui/SearchField.svelte';
  import Segmented from '../components/ui/Segmented.svelte';
  import Select from '../components/ui/Select.svelte';
  import Tag from '../components/ui/Tag.svelte';

  // Literal keys, so the unused-key check in i18n.test.ts sees them.
  const LIBRARY_LABELS: Record<Library, string> = {
    all: 'connections.library.all',
    favorites: 'connections.library.favorites',
    recent: 'connections.library.recent',
    tunnel: 'connections.library.tunnel',
  };
  const KIND_LABELS: Record<ConnectionKind, string> = {
    ssh: 'filters.ssh',
    rdp: 'filters.rdp',
    web: 'filters.web',
  };
  const DEFAULT_DIR: Record<SortKey, SortDir> = { name: 'asc', ping: 'asc', lastUsed: 'desc' };

  let library = $state<Library>('all');
  let kind = $state<ConnectionKind | null>(null);
  let tag = $state<string | null>(null);
  let grouping = $state<Grouping>('host');
  let view = $state<'table' | 'cards'>('table');
  let sortKey = $state<SortKey>('lastUsed');
  let sortDir = $state<SortDir>('desc');
  let selectedId = $state<string | null>(null);
  const checkedIds = new SvelteSet<string>();
  let busy = $state(false);

  let tunnelByConn = $derived(
    new Map(
      $tunnelMappings
        .filter((m) => m.enabled && m.connectionId)
        .map((m) => [m.connectionId as string, m.name]),
    ),
  );
  // Ticks, so "last 24 h" and the counts follow the clock while the page stays open.
  let now = $state(Date.now());
  let ctx = $derived<ListContext>({
    favorites: $favorites,
    tunneled: new Set(tunnelByConn.keys()),
    now,
  });
  let shown = $derived(
    sortConnections(
      filterConnections($connections, { library, kind, tag, search: $searchTerm }, ctx),
      sortKey,
      sortDir,
      $reachability,
    ),
  );
  let groups = $derived(groupConnections(shown, grouping));
  let filtered = $derived(
    library !== 'all' || kind != null || tag != null || $searchTerm.trim() !== '',
  );
  let quick = $derived(filtered ? [] : quickAccess($connections, ctx));
  let selected = $derived($connections.find((c) => c.id === selectedId) ?? null);
  // Derived from the store, so a connection deleted elsewhere drops out of the selection.
  let checkedConns = $derived($connections.filter((c) => checkedIds.has(c.id)));
  let allChecked = $derived(shown.length > 0 && shown.every((c) => checkedIds.has(c.id)));
  // Only a server the inventory already holds gets a name; the page does not load the inventory.
  let selectedServer = $derived(
    selected?.serverId
      ? ($infraServers.find((s) => s.id === selected?.serverId)?.name ?? null)
      : null,
  );

  let stopProbe: (() => void) | null = null;
  let destroyed = false;
  const clock = setInterval(() => (now = Date.now()), 60_000);

  onMount(async () => {
    await loadConnections();
    if (destroyed) return;
    stopProbe = startReachability(() => ({ conns: shown, tunneled: ctx.tunneled }));
  });
  onDestroy(() => {
    destroyed = true;
    clearInterval(clock);
    stopProbe?.();
  });

  function resetFilters(): void {
    library = 'all';
    kind = null;
    tag = null;
    searchTerm.set('');
  }

  function onSort(key: SortKey): void {
    if (key === sortKey) sortDir = sortDir === 'asc' ? 'desc' : 'asc';
    else {
      sortKey = key;
      sortDir = DEFAULT_DIR[key];
    }
  }

  function check(c: Connection, on: boolean): void {
    if (on) checkedIds.add(c.id);
    else checkedIds.delete(c.id);
  }

  // "All" means the visible rows: a filter narrows what the bulk actions touch.
  function checkAll(on: boolean): void {
    for (const c of shown) check(c, on);
  }

  async function bulk(run: () => Promise<void>): Promise<void> {
    busy = true;
    try {
      await run();
    } catch (err) {
      reportError(errMsg(err));
    } finally {
      busy = false;
    }
  }

  function retag(tagName: string, add: boolean): Promise<void> {
    return bulk(async () => {
      const changed = checkedConns.filter((c) => c.tags.includes(tagName) !== add);
      for (const c of changed) {
        const tags = add ? [...c.tags, tagName] : c.tags.filter((x) => x !== tagName);
        await upsert({ ...c, tags });
      }
      showStatus($t('connections.bulk.updated', { count: changed.length }));
    });
  }

  function exportChecked(): Promise<void> {
    return bulk(async () => {
      const dest = await save({
        defaultPath: 'adminhelper-connections.csv',
        filters: [{ name: 'CSV', extensions: ['csv'] }],
      });
      if (!dest) return;
      const path = await writeExportCsv(dest, connectionsCsv(checkedConns));
      showStatus($t('connections.bulk.saved', { path }));
    });
  }

  async function deleteChecked(): Promise<void> {
    const targets = checkedConns;
    const ok = await confirmDialog(
      $t('connections.bulk.deleteConfirm', { count: targets.length }),
      {
        confirmLabel: $t('action.delete'),
      },
    );
    if (!ok) return;
    await bulk(async () => {
      for (const c of targets) {
        await remove(c.id);
        if (c.kind === 'rdp') {
          try {
            await deletePassword(c);
          } catch {
            // non-fatal, as in the editor: a missing keyring entry must not stop the rest
          }
        }
      }
      checkedIds.clear();
      showStatus($t('connections.bulk.deleted', { count: targets.length }));
    });
  }

  function connect(c: Connection): void {
    selectedId = c.id;
    void initiateConnect(c);
  }
</script>

<div class="conn-page">
  <aside class="conn-rail">
    <ConnectionSidebar
      {library}
      {kind}
      {tag}
      libraryCounts={libraryCounts($connections, ctx)}
      kindCounts={kindCounts($connections)}
      tags={tagCounts($connections)}
      onLibrary={(l) => (library = l)}
      onKind={(k) => (kind = k)}
      onTag={(x) => (tag = x)}
    />
  </aside>

  <div class="conn-main">
    <div class="conn-toolbar">
      <div class="search">
        <SearchField
          bind:value={$searchTerm}
          placeholder={$t('connections.search')}
          label={$t('connections.search')}
          size="sm"
          fullWidth
        />
      </div>
      <div class="kind-switch">
        <Segmented
          label={$t('connections.type')}
          value={kind ?? 'all'}
          options={[
            { value: 'all', label: $t('connections.library.all') },
            { value: 'ssh', label: $t('filters.ssh') },
            { value: 'rdp', label: $t('filters.rdp') },
            { value: 'web', label: $t('filters.web') },
          ]}
          onChange={(v) => (kind = v === 'all' ? null : (v as ConnectionKind))}
        />
      </div>
      <div class="grouping" title={$t('connections.group')}>
        <Select
          size="sm"
          value={grouping}
          options={[
            { value: 'host', label: $t('connections.group.host') },
            { value: 'tag', label: $t('connections.group.tag') },
            { value: 'kind', label: $t('connections.group.kind') },
            { value: 'none', label: $t('connections.group.none') },
          ]}
          onChange={(v) => (grouping = v as Grouping)}
        />
      </div>
      <Segmented
        label={$t('connections.view')}
        value={view}
        options={[
          { value: 'table', icon: Rows3, title: $t('connections.view.table') },
          { value: 'cards', icon: LayoutGrid, title: $t('connections.view.cards') },
        ]}
        onChange={(v) => (view = v as 'table' | 'cards')}
      />
      <span class="counter" data-testid="conn-counter"
        >{$t('connections.count', { shown: shown.length, total: $connections.length })}</span
      >
      <Button size="sm" iconLeft={Plus} onclick={() => openEditor(null)}
        >{$t('connections.new')}</Button
      >
    </div>

    {#if filtered}
      <div class="chips">
        {#if library !== 'all'}
          <Tag
            size="sm"
            onRemove={() => (library = 'all')}
            removeLabel={$t('connections.chip.remove')}>{$t(LIBRARY_LABELS[library])}</Tag
          >
        {/if}
        {#if kind}
          <Tag size="sm" onRemove={() => (kind = null)} removeLabel={$t('connections.chip.remove')}
            >{$t('connections.chip.kind', { kind: $t(KIND_LABELS[kind]) })}</Tag
          >
        {/if}
        {#if tag}
          <Tag size="sm" onRemove={() => (tag = null)} removeLabel={$t('connections.chip.remove')}
            >{$t('connections.chip.tag', { tag })}</Tag
          >
        {/if}
        {#if $searchTerm.trim()}
          <Tag
            size="sm"
            onRemove={() => searchTerm.set('')}
            removeLabel={$t('connections.chip.remove')}
            >{$t('connections.chip.search', { q: $searchTerm.trim() })}</Tag
          >
        {/if}
        <button type="button" class="reset" onclick={resetFilters}>{$t('connections.reset')}</button
        >
      </div>
    {/if}

    {#if checkedConns.length > 0}
      <BulkBar
        count={checkedConns.length}
        {busy}
        onAddTag={(x) => void retag(x, true)}
        onRemoveTag={(x) => void retag(x, false)}
        onExport={() => void exportChecked()}
        onDelete={() => void deleteChecked()}
        onClear={() => checkedIds.clear()}
      />
    {/if}

    <ConnectionsLoadError />

    <div class="conn-scroll" use:accelerateScroll={LIST_FACTOR}>
      {#if $connections.length === 0}
        {#if $loading}
          <div class="dash-empty" style="padding: var(--sp-6);">{$t('loading.generic')}</div>
        {:else if !$connectionsStore.error}
          <div class="dash-empty" style="padding: var(--sp-6);">{$t('connections.empty')}</div>
        {/if}
      {:else}
        <QuickAccess
          items={quick}
          favorites={$favorites}
          reach={$reachability}
          onConnect={connect}
        />
        {#if shown.length === 0}
          <div class="no-results">
            <EmptyState icon={SearchX} title={$t('connections.noResults')}>
              {#snippet action()}
                <Button size="sm" variant="secondary" onclick={resetFilters}
                  >{$t('connections.resetFilters')}</Button
                >
              {/snippet}
            </EmptyState>
          </div>
        {:else}
          <ConnectionTable
            {groups}
            {grouping}
            {view}
            favorites={$favorites}
            reach={$reachability}
            tunnelName={(c) => tunnelByConn.get(c.id) ?? null}
            {selectedId}
            {sortKey}
            {sortDir}
            {onSort}
            onSelect={(c) => (selectedId = c.id)}
            onClear={() => (selectedId = null)}
            checked={checkedIds}
            {allChecked}
            onCheck={check}
            onCheckAll={checkAll}
            onConnect={connect}
            onEdit={(c) => openEditor(c)}
            onFavorite={(c) => void toggleFavorite(c.id)}
          />
        {/if}
      {/if}
    </div>
  </div>

  <div class="conn-insp">
    <ConnectionInspector
      conn={selected}
      favorite={selected ? $favorites.has(selected.id) : false}
      reach={selected ? $reachability[selected.id] : undefined}
      tunnel={selected ? (tunnelByConn.get(selected.id) ?? null) : null}
      server={selectedServer}
      onConnect={connect}
      onEdit={(c) => openEditor(c)}
      onFavorite={(c) => void toggleFavorite(c.id)}
    />
  </div>
</div>

<style>
  .conn-page {
    container-type: inline-size;
    display: flex;
    height: 100%;
    min-height: 0;
  }
  .conn-rail {
    display: none;
    flex: 0 0 220px;
    min-height: 0;
  }
  .conn-main {
    flex: 1;
    display: flex;
    flex-direction: column;
    min-width: 0;
    min-height: 0;
  }
  .conn-insp {
    display: none;
    flex: 0 0 340px;
    min-height: 0;
    overflow-y: auto;
    border-left: 1px solid var(--border);
  }
  .conn-toolbar {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 10px;
    padding: var(--sp-3) var(--sp-4);
    border-bottom: 1px solid var(--border);
  }
  .search {
    flex: 1 1 220px;
    min-width: 180px;
    max-width: 420px;
  }
  .counter {
    margin-left: auto;
    font-family: var(--font-mono);
    font-size: 12px;
    color: var(--text-subtle);
    white-space: nowrap;
  }
  .chips {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 6px;
    padding: var(--sp-3) var(--sp-4) 0;
  }
  .reset {
    border: none;
    background: transparent;
    color: var(--link);
    font: inherit;
    font-size: 12px;
    cursor: pointer;
  }
  .conn-scroll {
    flex: 1;
    min-height: 0;
    overflow-y: auto;
    padding-bottom: var(--sp-4);
  }
  .no-results {
    padding: var(--sp-5);
  }

  /* A container query only reaches descendants, hence nothing on .conn-page itself here. */
  @container (min-width: 900px) {
    .conn-insp {
      display: block;
    }
  }
  @container (min-width: 1380px) {
    .conn-insp {
      flex-basis: 380px;
    }
  }
  /* From 1180 px the filters live in the rail, and the kind switch in the toolbar goes. */
  @container (min-width: 1180px) {
    .conn-rail {
      display: block;
    }
    .kind-switch {
      display: none;
    }
  }
</style>
