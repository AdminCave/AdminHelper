<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  // Every object kind with all its fixture states, worst first: the catalogue Kevin signs off.
  import EmptyState from '../../../components/ui/EmptyState.svelte';
  import ObjectRow from '../ObjectRow.svelte';
  import type { Kind, MonObject } from '../model';
  import { KIND_LABEL, sortObjects } from '../grammar';

  interface Props {
    objects: MonObject[];
    now: Date;
    selected?: string;
    onOpen: (key: string) => void;
  }

  let { objects, now, selected, onOpen }: Props = $props();

  const groups = $derived(
    [...new Set<Kind>(objects.map((o) => o.kind))].map((kind) => ({
      kind,
      list: sortObjects(objects.filter((o) => o.kind === kind)),
    })),
  );
</script>

{#if objects.length === 0}
  <EmptyState title="Noch keine Objekte" description="Die Fixtures je Objektart folgen." />
{:else}
  {#each groups as g (g.kind)}
    <section class="group" aria-label={KIND_LABEL[g.kind]} data-kind={g.kind}>
      <h2>{KIND_LABEL[g.kind]} <span class="count">{g.list.length}</span></h2>
      <div class="list">
        {#each g.list as o (o.key)}
          <ObjectRow object={o} {now} showServer selected={selected === o.key} {onOpen} />
        {/each}
      </div>
    </section>
  {/each}
{/if}

<style>
  .group {
    margin-bottom: var(--space-6);
  }
  h2 {
    margin: 0 0 var(--space-2);
    font-size: var(--text-base);
    color: var(--text-strong);
  }
  .count {
    color: var(--text-subtle);
    font-weight: 400;
  }
  .list {
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    background: var(--surface);
    overflow: hidden;
  }
</style>
