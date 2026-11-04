<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import { Download, Tag as TagIcon, Trash2, X } from '@lucide/svelte';
  import { t } from '$lib/i18n';
  import Button from '../ui/Button.svelte';

  interface Props {
    count: number;
    busy: boolean;
    onAddTag: (tag: string) => void;
    onRemoveTag: (tag: string) => void;
    onExport: () => void;
    onDelete: () => void;
    onClear: () => void;
  }

  let { count, busy, onAddTag, onRemoveTag, onExport, onDelete, onClear }: Props = $props();

  let tag = $state('');
  let clean = $derived(tag.trim());

  function add(): void {
    if (!clean) return;
    onAddTag(clean);
    tag = '';
  }

  function onKey(e: KeyboardEvent): void {
    if (e.key === 'Enter') {
      e.preventDefault();
      add();
    }
  }
</script>

<div class="bulk" role="toolbar" aria-label={$t('connections.bulk')} data-testid="bulk-bar">
  <span class="bulk-count">{$t('connections.bulk.selected', { count })}</span>
  <span class="bulk-tag">
    <TagIcon size={13} />
    <input
      type="text"
      bind:value={tag}
      placeholder={$t('connections.bulk.tag')}
      aria-label={$t('connections.bulk.tag')}
      disabled={busy}
      onkeydown={onKey}
    />
  </span>
  <Button size="sm" variant="secondary" disabled={busy || !clean} onclick={add}
    >{$t('connections.bulk.addTag')}</Button
  >
  <Button
    size="sm"
    variant="secondary"
    disabled={busy || !clean}
    onclick={() => {
      onRemoveTag(clean);
      tag = '';
    }}>{$t('connections.bulk.removeTag')}</Button
  >
  <Button size="sm" variant="secondary" iconLeft={Download} disabled={busy} onclick={onExport}
    >{$t('connections.bulk.export')}</Button
  >
  <Button size="sm" variant="danger" iconLeft={Trash2} disabled={busy} onclick={onDelete}
    >{$t('action.delete')}</Button
  >
  <Button size="sm" variant="ghost" iconLeft={X} onclick={onClear}
    >{$t('connections.bulk.clear')}</Button
  >
</div>

<style>
  .bulk {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 8px;
    margin: var(--sp-3) var(--sp-4) 0;
    padding: 8px 12px;
    border: 1px solid var(--border-strong);
    border-radius: var(--radius-md);
    background: var(--surface);
  }
  .bulk-count {
    margin-right: auto;
    font-size: 13px;
    font-weight: 600;
    color: var(--text-strong);
  }
  .bulk-tag {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 0 10px;
    height: 28px;
    border: 1px solid var(--border-strong);
    border-radius: var(--radius-pill);
    background: var(--surface-inset);
    color: var(--text-subtle);
  }
  .bulk-tag:focus-within {
    border-color: var(--accent);
    box-shadow: var(--ring-shadow);
  }
  .bulk-tag input {
    width: 120px;
    border: none;
    background: transparent;
    color: var(--text);
    font: inherit;
    font-size: 12px;
    outline: none;
  }
</style>
