<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import Modal from './ui/Modal.svelte';
  import { filterEntries, type PaletteEntry } from '$lib/palette';
  import { t } from '$lib/i18n';

  interface Props {
    open: boolean;
    entries: PaletteEntry[];
    onClose: () => void;
  }

  let { open, entries, onClose }: Props = $props();

  const uid = $props.id();
  let query = $state('');
  let selected = $state(0);
  let results = $derived(filterEntries(entries, query));
  // The entries may shrink while it is open (a reload); keep the selection on a real row.
  let current = $derived(Math.min(selected, Math.max(results.length - 1, 0)));

  // Every opening starts empty at the first entry.
  $effect.pre(() => {
    if (open) {
      query = '';
      selected = 0;
    }
  });

  function onInput(): void {
    selected = 0;
  }

  // Close first: the modal hands the focus back, then the entry may open its own dialog.
  function choose(entry: PaletteEntry | undefined): void {
    if (!entry) return;
    onClose();
    entry.run();
  }

  function onKeydown(e: KeyboardEvent): void {
    const n = results.length;
    if (e.key === 'ArrowDown' && n > 0) {
      e.preventDefault();
      selected = (current + 1) % n;
    } else if (e.key === 'ArrowUp' && n > 0) {
      e.preventDefault();
      selected = (current - 1 + n) % n;
    } else if (e.key === 'Enter') {
      e.preventDefault();
      choose(results[current]);
    }
  }
</script>

<Modal {open} {onClose} width="560px">
  <div class="palette">
    <input
      class="palette-input"
      type="text"
      role="combobox"
      aria-expanded="true"
      aria-controls="{uid}-list"
      aria-activedescendant={results.length > 0 ? `${uid}-opt-${current}` : undefined}
      aria-label={$t('palette.label')}
      placeholder={$t('palette.placeholder')}
      autocomplete="off"
      spellcheck="false"
      bind:value={query}
      oninput={onInput}
      onkeydown={onKeydown}
    />
    {#if results.length > 0}
      <ul class="palette-list" id="{uid}-list" role="listbox" aria-label={$t('palette.label')}>
        {#each results as entry, i (entry.id)}
          <li
            id="{uid}-opt-{i}"
            class="palette-item"
            class:selected={i === current}
            role="option"
            aria-selected={i === current}
            data-kind={entry.kind}
            onclick={() => choose(entry)}
            tabindex="-1"
            onkeydown={() => {}}
            onmousemove={() => (selected = i)}
          >
            <span class="palette-kind">{$t(`palette.kind.${entry.kind}`)}</span>
            <span class="palette-label">{entry.label}</span>
            {#if entry.hint}<span class="palette-hint">{entry.hint}</span>{/if}
          </li>
        {/each}
      </ul>
    {:else}
      <div class="palette-empty">{$t('palette.empty')}</div>
    {/if}
  </div>
</Modal>

<style>
  .palette {
    display: flex;
    flex-direction: column;
    gap: var(--sp-3);
  }
  .palette-input {
    width: 100%;
    box-sizing: border-box;
    padding: 10px 12px;
    border: 1px solid var(--border-strong);
    border-radius: var(--radius-md);
    background: var(--bg);
    color: var(--text-strong);
    font: inherit;
    font-size: 15px;
  }
  .palette-input:focus {
    outline: none;
    border-color: var(--accent);
  }
  .palette-list {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: 2px;
  }
  .palette-item {
    display: flex;
    align-items: center;
    gap: var(--sp-3);
    padding: 8px 10px;
    border-radius: var(--radius-sm);
    cursor: pointer;
    color: var(--text);
  }
  .palette-item.selected {
    background: var(--surface-raised);
    color: var(--text-strong);
  }
  .palette-kind {
    flex: none;
    width: 84px;
    color: var(--text-muted);
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.04em;
  }
  .palette-label {
    flex: 1;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .palette-hint {
    flex: none;
    color: var(--text-muted);
    font-family: var(--font-mono);
    font-size: 12px;
  }
  .palette-empty {
    padding: var(--sp-4) 10px;
    color: var(--text-muted);
  }
</style>
