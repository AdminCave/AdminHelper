<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  // Every object kind with all its fixture states, kinds with problems first: the catalogue Kevin
  // signs off. The kinds start closed, so the whole catalogue fits on one screen.
  import EmptyState from '../../../components/ui/EmptyState.svelte';
  import type { MonObject } from '../model';
  import KindGroups from './KindGroups.svelte';

  interface Props {
    objects: MonObject[];
    now: Date;
    selected?: string;
    onOpen: (key: string) => void;
  }

  let { objects, now, selected, onOpen }: Props = $props();

  let allOpen = $state(false);
  const kinds = $derived(new Set(objects.map((o) => o.kind)).size);
</script>

{#if objects.length === 0}
  <EmptyState title="Noch keine Objekte" description="Die Fixtures je Objektart folgen." />
{:else}
  <header class="head">
    <h2>Objektarten <span class="count">{kinds} Arten · {objects.length} Objekte</span></h2>
    <button type="button" class="toggle" onclick={() => (allOpen = !allOpen)}
      >{allOpen ? 'Alle zuklappen' : 'Alle aufklappen'}</button
    >
  </header>
  <KindGroups {objects} {now} {selected} open={allOpen} showServer {onOpen} />
{/if}

<style>
  .head {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    margin-bottom: var(--space-3);
  }
  h2 {
    margin: 0;
    font-size: var(--text-xl);
    color: var(--text-strong);
  }
  .count {
    margin-left: var(--space-2);
    font-size: var(--text-sm);
    font-weight: 400;
    color: var(--text-subtle);
  }
  .toggle {
    padding: 0;
    border: 0;
    background: none;
    font: inherit;
    font-size: var(--text-sm);
    color: var(--accent);
    cursor: pointer;
  }
</style>
