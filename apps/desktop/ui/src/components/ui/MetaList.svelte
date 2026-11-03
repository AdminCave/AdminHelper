<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  interface Props {
    // Key/value rows; values set in mono unless the row says otherwise.
    rows: { key: string; value: string; mono?: boolean }[];
  }

  let { rows }: Props = $props();
</script>

<dl class="meta">
  {#each rows as r, i (i)}
    <dt>{r.key}</dt>
    <dd class:mono={r.mono ?? true}>{r.value}</dd>
  {/each}
</dl>

<style>
  .meta {
    display: grid;
    grid-template-columns: minmax(110px, 160px) 1fr;
    gap: 9px 16px;
    margin: 0;
    font-size: var(--text-sm);
  }
  dt {
    color: var(--text-subtle);
  }
  dd {
    min-width: 0;
    margin: 0;
    color: var(--text);
    overflow-wrap: anywhere;
  }
  .mono {
    font-family: var(--font-mono);
  }
</style>
