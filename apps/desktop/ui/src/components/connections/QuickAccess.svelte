<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import { ArrowUpRight, ChevronDown, ChevronRight, Star } from '@lucide/svelte';
  import type { Connection } from '$lib/bridge/types';
  import type { Reach } from '$lib/models/connectionList';
  import { toCardMeta } from '$lib/models/connection';
  import { t } from '$lib/i18n';
  import Button from '../ui/Button.svelte';
  import Dot from '../ui/Dot.svelte';
  import { reachView } from './ConnectionTable.svelte';

  interface Props {
    items: Connection[];
    favorites: ReadonlySet<string>;
    reach: Readonly<Record<string, Reach>>;
    onConnect: (c: Connection) => void;
  }

  let { items, favorites, reach, onConnect }: Props = $props();

  let open = $state(true);
</script>

{#if items.length > 0}
  <section class="quick" data-testid="quick-access">
    <button
      type="button"
      class="quick-head eyebrow"
      aria-expanded={open}
      onclick={() => (open = !open)}
    >
      {#if open}<ChevronDown size={12} />{:else}<ChevronRight size={12} />{/if}
      {$t('connections.quick')}
    </button>
    {#if open}
      <div class="quick-grid">
        {#each items as c (c.id)}
          {@const v = reachView(reach[c.id])}
          {@const fav = favorites.has(c.id)}
          <div class="quick-card">
            <div class="quick-top">
              <span class="quick-name">{c.name || $t('list.noName')}</span>
              {#if fav}<Star size={12} fill="currentColor" />{/if}
            </div>
            <div class="quick-target">{c.kind === 'web' ? c.url || '-' : toCardMeta(c)}</div>
            <div class="quick-foot">
              <span class="quick-state">
                <Dot st={v.st} size={7} />
                {#if v.key}{$t(v.key, { ms: v.ms ?? '' })}{:else}{$t(
                    fav ? 'connections.quick.favorite' : 'connections.quick.recent',
                  )}{/if}
              </span>
              <Button
                size="sm"
                variant="secondary"
                iconRight={c.kind === 'web' ? ArrowUpRight : undefined}
                onclick={() => onConnect(c)}
                >{$t(c.kind === 'web' ? 'connections.open' : 'action.connect')}</Button
              >
            </div>
          </div>
        {/each}
      </div>
    {/if}
  </section>
{/if}

<style>
  .quick {
    padding: var(--sp-3) var(--sp-4) 0;
  }
  .quick-head {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    padding: 0 0 var(--sp-2);
    border: none;
    background: transparent;
    cursor: pointer;
  }
  .quick-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
    gap: 10px;
  }
  .quick-card {
    display: flex;
    flex-direction: column;
    gap: 6px;
    padding: 12px;
    border: 1px solid var(--border);
    border-radius: var(--radius-md);
    background: var(--surface);
  }
  .quick-top {
    display: flex;
    align-items: center;
    gap: 6px;
    color: var(--text-strong);
  }
  .quick-name {
    font-size: 13px;
    font-weight: 600;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .quick-target,
  .quick-state {
    font-family: var(--font-mono);
    font-size: 11px;
    color: var(--text-subtle);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .quick-foot {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
  }
  .quick-state {
    display: inline-flex;
    align-items: center;
    gap: 6px;
  }
</style>
