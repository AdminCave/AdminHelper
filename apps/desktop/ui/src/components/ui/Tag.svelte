<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import type { Snippet } from 'svelte';
  import { t } from '$lib/i18n';

  type Tone = 'accent' | 'neutral' | 'outline';
  type Size = 'sm' | 'md';

  interface Props {
    tone?: Tone;
    size?: Size;
    mono?: boolean;
    onClick?: (e: MouseEvent) => void;
    onRemove?: () => void;
    removeLabel?: string;
    children: Snippet;
  }

  let {
    tone = 'accent',
    size = 'md',
    mono = true,
    onClick,
    onRemove,
    removeLabel,
    children,
  }: Props = $props();

  function remove(e: MouseEvent) {
    // Tags sit in clickable rows and chips: removing must not also trigger those.
    e.stopPropagation();
    onRemove?.();
  }
</script>

<!-- Two sibling controls, never one inside the other: children of role=button are
     presentational, so a nested remove button would vanish for screen readers. -->
<span class="ui-tag ui-tag-{tone} ui-tag-{size}" class:mono class:clickable={!!onClick}>
  {#if onClick}
    <button type="button" class="main" onclick={onClick}>{@render children()}</button>
  {:else}
    <span class="text">{@render children()}</span>
  {/if}
  {#if onRemove}
    <button
      type="button"
      class="remove"
      aria-label={removeLabel ?? $t('action.delete')}
      onclick={remove}>×</button
    >
  {/if}
</span>

<style>
  .ui-tag {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    border: 1px solid transparent;
    border-radius: var(--radius-pill);
    font-weight: 500;
    white-space: nowrap;
  }
  .ui-tag-sm {
    height: 20px;
    padding: 0 var(--space-2);
    font-size: 11px;
  }
  .ui-tag-md {
    height: 24px;
    padding: 0 10px;
    font-size: var(--text-xs);
  }
  .mono {
    font-family: var(--font-mono);
  }
  .ui-tag-accent {
    background: var(--accent-muted);
    border-color: var(--accent-border);
    color: var(--accent);
  }
  .ui-tag-neutral {
    background: var(--surface-raised);
    border-color: var(--border);
    color: var(--text-muted);
  }
  .ui-tag-outline {
    border-color: var(--border-strong);
    color: var(--text-muted);
  }
  .main {
    padding: 0;
    border: 0;
    background: transparent;
    color: inherit;
    font: inherit;
    cursor: pointer;
  }
  .clickable:hover {
    border-color: var(--border-strong);
  }
  .remove {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 14px;
    height: 14px;
    margin-right: -4px;
    padding: 0;
    border: 0;
    border-radius: var(--radius-pill);
    background: transparent;
    color: inherit;
    font-size: 13px;
    line-height: 1;
    cursor: pointer;
    opacity: 0.7;
  }
  .remove:hover {
    opacity: 1;
    background: var(--surface-hover);
  }
</style>
