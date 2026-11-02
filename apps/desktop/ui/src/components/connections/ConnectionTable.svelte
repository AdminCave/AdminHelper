<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script module lang="ts">
  import type { Reach } from '$lib/models/connectionList';

  /** Dot status and i18n key (or literal) of a reachability value. */
  export function reachView(r: Reach): { st: string; key: string | null; ms: number | null } {
    if (typeof r === 'number') return { st: 'ok', key: 'connections.ping.ms', ms: r };
    if (r === null) return { st: 'critical', key: 'connections.ping.down', ms: null };
    if (r === 'tunnel') return { st: 'info', key: 'tunnel.badge', ms: null };
    return { st: 'pending', key: null, ms: null };
  }
</script>

<script lang="ts">
  import {
    ArrowDown,
    ArrowUp,
    ArrowUpDown,
    ArrowUpRight,
    Cable,
    ChevronDown,
    ChevronRight,
    Folder,
    Globe,
    Monitor,
    Pencil,
    Server,
    SquareTerminal,
    Star,
  } from '@lucide/svelte';
  import type { Component } from 'svelte';
  import type { Connection, ConnectionKind } from '$lib/bridge/types';
  import {
    NO_GROUP,
    type Grouping,
    type ListGroup,
    type SortDir,
    type SortKey,
  } from '$lib/models/connectionList';
  import { toCardMeta } from '$lib/models/connection';
  import { timeAgo } from '$lib/utils/timeAgo';
  import { t } from '$lib/i18n';
  import Button from '../ui/Button.svelte';
  import Checkbox from '../ui/Checkbox.svelte';
  import Dot from '../ui/Dot.svelte';
  import IconButton from '../ui/IconButton.svelte';
  import Pill from '../ui/Pill.svelte';
  import Tag from '../ui/Tag.svelte';

  interface Props {
    groups: ListGroup[];
    grouping: Grouping;
    view: 'table' | 'cards';
    favorites: ReadonlySet<string>;
    reach: Readonly<Record<string, Reach>>;
    tunnelName: (c: Connection) => string | null;
    selectedId: string | null;
    sortKey: SortKey;
    sortDir: SortDir;
    onSort: (key: SortKey) => void;
    onSelect: (c: Connection) => void;
    onClear: () => void;
    onConnect: (c: Connection) => void;
    onEdit: (c: Connection) => void;
    onFavorite: (c: Connection) => void;
    checked: ReadonlySet<string>;
    allChecked: boolean;
    onCheck: (c: Connection, on: boolean) => void;
    onCheckAll: (on: boolean) => void;
  }

  let {
    groups,
    grouping,
    view,
    favorites,
    reach,
    tunnelName,
    selectedId,
    sortKey,
    sortDir,
    onSort,
    onSelect,
    onClear,
    onConnect,
    onEdit,
    onFavorite,
    checked,
    allChecked,
    onCheck,
    onCheckAll,
  }: Props = $props();

  const KIND_ICONS: Record<ConnectionKind, Component<{ size?: number }>> = {
    ssh: SquareTerminal,
    rdp: Monitor,
    web: Globe,
  };
  const KIND_LABELS: Record<ConnectionKind, string> = {
    ssh: 'filters.ssh',
    rdp: 'filters.rdp',
    web: 'filters.web',
  };

  let closed = $state<Record<string, boolean>>({});
  function toggle(key: string): void {
    closed = { ...closed, [key]: !closed[key] };
  }

  function groupTitle(key: string): string {
    if (grouping === 'kind') return $t(KIND_LABELS[key as ConnectionKind]);
    if (key === NO_GROUP)
      return $t(grouping === 'host' ? 'connections.group.noHost' : 'connections.group.noTag');
    return key;
  }

  function groupIcon(key: string): Component<{ size?: number }> {
    if (grouping === 'kind') return KIND_ICONS[key as ConnectionKind];
    return grouping === 'host' ? Server : Folder;
  }

  function target(c: Connection): string {
    return c.kind === 'web' ? c.url || '-' : toCardMeta(c);
  }

  function onRowKey(e: KeyboardEvent, c: Connection): void {
    if (e.target !== e.currentTarget) return;
    if (e.key === 'Enter') onConnect(c);
    else if (e.key === ' ') {
      e.preventDefault();
      onSelect(c);
    }
  }

  // ↑/↓ walk the rows in their visible order (folded groups skipped), Esc drops the selection.
  let wrap: HTMLElement | undefined = $state();
  function onListKey(e: KeyboardEvent): void {
    // A text field keeps its keys; a row checkbox does not need ↑/↓ or Esc.
    if (e.target instanceof HTMLInputElement && e.target.type !== 'checkbox') return;
    if (e.key === 'Escape') {
      onClear();
      return;
    }
    if (e.key !== 'ArrowDown' && e.key !== 'ArrowUp') return;
    e.preventDefault();
    const rows = [...(wrap?.querySelectorAll<HTMLElement>('[data-testid="conn-row"]') ?? [])];
    // A connection with two tags is listed twice under folder grouping: start from the focused
    // row, not from the first row carrying the selected id, or ↓ would jump back to that copy.
    const focused = rows.indexOf(document.activeElement as HTMLElement);
    const i = focused >= 0 ? focused : rows.findIndex((r) => r.dataset.id === selectedId);
    const next =
      rows[e.key === 'ArrowDown' ? Math.min(rows.length - 1, i + 1) : Math.max(0, i - 1)];
    const c = next && groups.flatMap((g) => g.connections).find((x) => x.id === next.dataset.id);
    if (!next || !c) return;
    next.focus();
    onSelect(c);
  }

  // A click on the row checkbox (its label or box) only checks; it neither selects nor connects.
  function fromCheck(e: MouseEvent): boolean {
    return e.target instanceof Element && e.target.closest('.cell-check') !== null;
  }

  // Clicks on the row's own buttons must neither select nor connect the row.
  function stop(e: Event): void {
    e.stopPropagation();
  }
</script>

{#snippet sortHead(key: SortKey, label: string)}
  {@const on = sortKey === key}
  {@const Icon = on ? (sortDir === 'asc' ? ArrowUp : ArrowDown) : ArrowUpDown}
  <button
    type="button"
    class="sort-head"
    class:on
    aria-pressed={on}
    data-sort={on ? sortDir : undefined}
    onclick={() => onSort(key)}
  >
    {label}<Icon size={11} />
  </button>
{/snippet}

{#snippet ping(c: Connection)}
  {@const v = reachView(reach[c.id])}
  <span class="ping" class:known={v.key != null} data-testid="conn-ping">
    <Dot st={v.st} size={7} />{v.key ? $t(v.key, { ms: v.ms ?? '' }) : '—'}
  </span>
{/snippet}

{#snippet star(c: Connection)}
  {@const on = favorites.has(c.id)}
  <button
    type="button"
    class="star"
    class:on
    aria-pressed={on}
    aria-label={$t(on ? 'connections.favorite.remove' : 'connections.favorite.add')}
    title={$t(on ? 'connections.favorite.remove' : 'connections.favorite.add')}
    onclick={(e) => {
      stop(e);
      onFavorite(c);
    }}
  >
    <Star size={13} fill={on ? 'currentColor' : 'none'} />
  </button>
{/snippet}

{#snippet connect(c: Connection)}
  <Button
    size="sm"
    variant={c.kind === 'web' ? 'secondary' : 'primary'}
    iconRight={c.kind === 'web' ? ArrowUpRight : undefined}
    onclick={(e: MouseEvent) => {
      stop(e);
      onConnect(c);
    }}>{$t(c.kind === 'web' ? 'connections.open' : 'action.connect')}</Button
  >
{/snippet}

{#snippet check(c: Connection)}
  <span class="cell-check">
    <Checkbox
      checked={checked.has(c.id)}
      ariaLabel={$t('connections.bulk.check', { name: c.name || $t('list.noName') })}
      onChange={(on) => onCheck(c, on)}
    />
  </span>
{/snippet}

{#snippet checkAll()}
  <span class="cell-check">
    <Checkbox
      checked={allChecked}
      ariaLabel={$t('connections.bulk.checkAll')}
      onChange={(on) => onCheckAll(on)}
    />
  </span>
{/snippet}

{#snippet kindTile(c: Connection, size: number)}
  {@const Icon = KIND_ICONS[c.kind]}
  <span class="kind-tile kind-{c.kind}" style:width="{size}px" style:height="{size}px">
    <Icon size={Math.round(size / 2)} />
  </span>
{/snippet}

{#snippet row(c: Connection)}
  {@const tunnel = tunnelName(c)}
  <div
    class="row"
    class:selected={selectedId === c.id}
    role="option"
    tabindex="0"
    aria-selected={selectedId === c.id}
    data-testid="conn-row"
    data-id={c.id}
    onclick={(e) => {
      if (!fromCheck(e)) onSelect(c);
    }}
    ondblclick={(e) => {
      if (!fromCheck(e)) onConnect(c);
    }}
    onkeydown={(e) => onRowKey(e, c)}
  >
    {@render check(c)}
    <div class="cell-name">
      {@render kindTile(c, 32)}
      <div class="name-block">
        <div class="name-line">
          <span class="conn-name">{c.name || $t('list.noName')}</span>
          {@render star(c)}
        </div>
        <div class="sub-target">{target(c)}</div>
      </div>
    </div>
    <div class="cell-target">
      <span class="target">{target(c)}</span>
      {#if tunnel}
        <span class="tunnel" title={tunnel}><Cable size={13} /></span>
      {/if}
    </div>
    {@render ping(c)}
    <div class="cell-tags">
      {#each (c.tags ?? []).slice(0, 2) as tag (tag)}
        <Tag size="sm" tone="neutral">{tag}</Tag>
      {/each}
      {#if (c.tags ?? []).length > 2}
        <span class="more">+{c.tags.length - 2}</span>
      {/if}
    </div>
    <span class="last">{timeAgo(c.lastUsed, $t)}</span>
    <div class="actions">
      {@render connect(c)}
      <IconButton
        size="sm"
        icon={Pencil}
        label={$t('action.edit')}
        onclick={(e: MouseEvent) => {
          stop(e);
          onEdit(c);
        }}
      />
    </div>
  </div>
{/snippet}

{#snippet card(c: Connection)}
  {@const tunnel = tunnelName(c)}
  <div
    class="conn-card"
    class:selected={selectedId === c.id}
    role="option"
    tabindex="0"
    aria-selected={selectedId === c.id}
    data-testid="conn-row"
    data-id={c.id}
    onclick={(e) => {
      if (!fromCheck(e)) onSelect(c);
    }}
    ondblclick={(e) => {
      if (!fromCheck(e)) onConnect(c);
    }}
    onkeydown={(e) => onRowKey(e, c)}
  >
    <div class="card-head">
      {@render check(c)}
      {@render kindTile(c, 34)}
      <div class="name-block">
        <div class="name-line">
          <span class="conn-name">{c.name || $t('list.noName')}</span>
          {@render star(c)}
        </div>
        <div class="card-target">{target(c)}</div>
      </div>
    </div>
    <div class="card-status">
      {@render ping(c)}
      {#if tunnel}
        <Pill tone="accent" title={tunnel}><Cable size={11} />{$t('tunnel.badge')}</Pill>
      {/if}
    </div>
    <div class="card-foot">
      <span class="last">{timeAgo(c.lastUsed, $t)}</span>
      {@render connect(c)}
      <IconButton
        size="sm"
        icon={Pencil}
        label={$t('action.edit')}
        onclick={(e: MouseEvent) => {
          stop(e);
          onEdit(c);
        }}
      />
    </div>
  </div>
{/snippet}

<div
  class="table-wrap"
  role="listbox"
  aria-label={$t('page.connections')}
  tabindex="-1"
  bind:this={wrap}
  onkeydown={onListKey}
>
  {#if view === 'table'}
    <div class="row head" role="presentation">
      {@render checkAll()}
      {@render sortHead('name', $t('connections.col.name'))}
      <span class="col-head cell-target">{$t('connections.col.target')}</span>
      {@render sortHead('ping', $t('connections.col.ping'))}
      <span class="col-head cell-tags">{$t('connections.col.tags')}</span>
      {@render sortHead('lastUsed', $t('connections.col.lastUsed'))}
      <span></span>
    </div>
  {:else}
    <div class="cards-head" role="presentation">
      {@render checkAll()}
      <span>{$t('connections.bulk.checkAll')}</span>
    </div>
  {/if}
  {#each groups as g (g.key)}
    {@const flat = grouping === 'none'}
    {@const isClosed = !flat && !!closed[g.key]}
    <div class="group" data-testid="conn-group">
      {#if !flat}
        {@const Icon = groupIcon(g.key)}
        <button
          type="button"
          class="group-head"
          aria-expanded={!isClosed}
          onclick={() => toggle(g.key)}
        >
          {#if isClosed}<ChevronRight size={14} />{:else}<ChevronDown size={14} />{/if}
          <Icon size={15} />
          <span class="group-title">{groupTitle(g.key)}</span>
          <span class="group-count">{g.connections.length}</span>
          <span class="group-rule"></span>
        </button>
      {/if}
      {#if !isClosed}
        {#if view === 'table'}
          {#each g.connections as c (c.id)}
            {@render row(c)}
          {/each}
        {:else}
          <div class="cards">
            {#each g.connections as c (c.id)}
              {@render card(c)}
            {/each}
          </div>
        {/if}
      {/if}
    </div>
  {/each}
</div>

<style>
  .table-wrap {
    container-type: inline-size;
    padding: 0 var(--sp-2);
  }
  .row {
    display: grid;
    grid-template-columns:
      20px minmax(190px, 1.4fr) minmax(170px, 1.3fr) 110px minmax(110px, 1fr)
      92px 150px;
    align-items: center;
    gap: 12px;
    min-height: 54px;
    padding: 6px 12px;
    border: 1px solid transparent;
    border-radius: var(--radius-md);
    cursor: pointer;
  }
  .cell-check {
    display: inline-flex;
    align-items: center;
  }
  .cards-head {
    display: flex;
    align-items: center;
    gap: 10px;
    margin-top: var(--sp-2);
    padding: 6px 12px;
    font-size: 12px;
    color: var(--text-subtle);
  }
  .row:hover {
    background: var(--surface-hover);
  }
  .row.selected,
  .conn-card.selected {
    border-color: var(--border-strong);
    background: var(--surface-raised);
  }
  .row:focus-visible,
  .conn-card:focus-visible {
    outline: 2px solid var(--accent);
    outline-offset: -2px;
  }
  .row.head {
    position: sticky;
    top: 0;
    z-index: 2;
    min-height: 36px;
    margin-top: var(--sp-2);
    border-radius: 0;
    border-bottom: 1px solid var(--border);
    background: var(--bg);
    cursor: default;
  }
  .row.head:hover {
    background: var(--bg);
  }
  .sort-head,
  .col-head {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    padding: 0;
    border: none;
    background: transparent;
    font-family: var(--font-mono);
    font-size: 10.5px;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: var(--text-subtle);
    white-space: nowrap;
  }
  .sort-head {
    cursor: pointer;
  }
  .sort-head.on {
    color: var(--text-strong);
  }
  .cell-name,
  .card-head {
    display: flex;
    align-items: center;
    gap: 11px;
    min-width: 0;
  }
  .name-block {
    flex: 1;
    min-width: 0;
  }
  .name-line {
    display: flex;
    align-items: center;
    gap: 6px;
    min-width: 0;
  }
  .conn-name {
    font-size: 13.5px;
    font-weight: 600;
    color: var(--text-strong);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .sub-target,
  .card-target,
  .target {
    font-family: var(--font-mono);
    font-size: 11.5px;
    color: var(--text-subtle);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .sub-target {
    display: none;
  }
  .target {
    font-size: 12px;
    color: var(--text-muted);
  }
  .cell-target {
    display: flex;
    align-items: center;
    gap: 8px;
    min-width: 0;
  }
  .tunnel {
    display: inline-flex;
    flex: 0 0 auto;
    color: var(--accent);
  }
  .cell-tags {
    display: flex;
    gap: 4px;
    min-width: 0;
    overflow: hidden;
  }
  .more,
  .last {
    font-family: var(--font-mono);
    font-size: 11px;
    color: var(--text-subtle);
    white-space: nowrap;
  }
  .ping {
    display: inline-flex;
    align-items: center;
    gap: 7px;
    font-family: var(--font-mono);
    font-size: 12px;
    color: var(--text-subtle);
    white-space: nowrap;
  }
  .ping.known {
    color: var(--text);
  }
  .actions {
    display: flex;
    align-items: center;
    justify-content: flex-end;
    gap: 2px;
  }
  .star {
    display: inline-flex;
    padding: 2px;
    border: none;
    background: transparent;
    color: var(--text-subtle);
    opacity: 0.55;
    cursor: pointer;
  }
  .star.on {
    color: var(--text-strong);
    opacity: 1;
  }
  .kind-tile {
    display: inline-grid;
    flex: 0 0 auto;
    place-items: center;
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    background: var(--surface);
    color: var(--text-muted);
  }
  .group-head {
    display: flex;
    align-items: center;
    gap: 10px;
    width: 100%;
    padding: 16px 12px 8px;
    border: none;
    background: transparent;
    color: var(--text-muted);
    font: inherit;
    cursor: pointer;
    user-select: none;
  }
  .group-title {
    font-size: 13.5px;
    font-weight: 600;
    color: var(--text-strong);
    white-space: nowrap;
  }
  .group-count {
    font-family: var(--font-mono);
    font-size: 11px;
    color: var(--text-subtle);
  }
  .group-rule {
    flex: 1;
    min-width: 20px;
    height: 1px;
    background: var(--border);
  }
  .cards {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(min(100%, 250px), 1fr));
    gap: 12px;
    padding: 4px 12px 8px;
  }
  .conn-card {
    display: flex;
    flex-direction: column;
    gap: 12px;
    padding: 14px;
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    background: var(--surface);
    cursor: pointer;
  }
  .card-status,
  .card-foot {
    display: flex;
    align-items: center;
    gap: 8px;
    flex-wrap: wrap;
  }
  .card-foot .last {
    flex: 1;
  }

  /* The mockup's compact table under 820 px of list width: no target and tag columns, the
     target moves under the name. */
  @container (max-width: 819px) {
    .row {
      grid-template-columns: 20px minmax(170px, 1fr) 110px 92px 150px;
    }
    .cell-target,
    .cell-tags {
      display: none;
    }
    .sub-target {
      display: block;
    }
  }
</style>
