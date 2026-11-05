<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import type { Component } from 'svelte';
  import {
    Cable,
    Folder,
    FolderOpen,
    Globe,
    History,
    Layers,
    Monitor,
    SquareTerminal,
    Star,
  } from '@lucide/svelte';
  import type { ConnectionKind } from '$lib/bridge/types';
  import { KINDS, LIBRARIES, type Library } from '$lib/models/connectionList';
  import { t } from '$lib/i18n';

  interface Props {
    library: Library;
    kind: ConnectionKind | null;
    tag: string | null;
    libraryCounts: Record<Library, number>;
    kindCounts: Record<ConnectionKind, number>;
    tags: [string, number][];
    onLibrary: (library: Library) => void;
    onKind: (kind: ConnectionKind | null) => void;
    onTag: (tag: string | null) => void;
  }

  let { library, kind, tag, libraryCounts, kindCounts, tags, onLibrary, onKind, onTag }: Props =
    $props();

  const LIBRARY_ICONS: Record<Library, Component<{ size?: number }>> = {
    all: Layers,
    favorites: Star,
    recent: History,
    tunnel: Cable,
  };
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
  const KIND_ICONS: Record<ConnectionKind, Component<{ size?: number }>> = {
    ssh: SquareTerminal,
    rdp: Monitor,
    web: Globe,
  };
</script>

{#snippet item(
  label: string,
  count: number,
  active: boolean,
  Icon: Component<{ size?: number }>,
  onclick: () => void,
)}
  <button type="button" class="rail-item" class:active aria-pressed={active} {onclick}>
    <Icon size={14} />
    <span class="rail-label">{label}</span>
    <span class="rail-count">{count}</span>
  </button>
{/snippet}

<nav class="rail" aria-label={$t('connections.library')}>
  <div class="eyebrow rail-head">{$t('connections.library')}</div>
  {#each LIBRARIES as l (l)}
    {@render item($t(LIBRARY_LABELS[l]), libraryCounts[l], library === l, LIBRARY_ICONS[l], () =>
      onLibrary(l),
    )}
  {/each}

  <div class="eyebrow rail-head">{$t('connections.type')}</div>
  {#each KINDS as k (k)}
    {@render item($t(KIND_LABELS[k]), kindCounts[k], kind === k, KIND_ICONS[k], () =>
      onKind(kind === k ? null : k),
    )}
  {/each}

  {#if tags.length > 0}
    <div class="eyebrow rail-head">{$t('connections.folders')}</div>
    {#each tags as [name, count] (name)}
      {@render item(name, count, tag === name, tag === name ? FolderOpen : Folder, () =>
        onTag(tag === name ? null : name),
      )}
    {/each}
  {/if}
</nav>

<style>
  .rail {
    display: flex;
    flex-direction: column;
    gap: 1px;
    padding: var(--sp-4) var(--sp-3);
    border-right: 1px solid var(--border);
    overflow-y: auto;
  }
  .rail-head {
    padding: var(--sp-5) 10px var(--sp-2);
  }
  .rail-head:first-child {
    padding-top: 0;
  }
  .rail-item {
    display: flex;
    align-items: center;
    gap: 9px;
    width: 100%;
    height: 32px;
    padding: 0 10px;
    border: none;
    border-radius: var(--radius-sm);
    background: transparent;
    color: var(--text-muted);
    font: inherit;
    font-size: 13px;
    font-weight: 500;
    cursor: pointer;
  }
  .rail-item:hover {
    background: var(--surface-hover);
  }
  .rail-item.active {
    color: var(--text-strong);
    font-weight: 600;
  }
  .rail-label {
    flex: 1;
    text-align: left;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .rail-count {
    font-family: var(--font-mono);
    font-size: 11px;
    color: var(--text-subtle);
  }
  .rail-item.active .rail-count {
    color: var(--text);
  }
</style>
