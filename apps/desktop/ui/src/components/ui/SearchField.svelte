<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import { t } from '$lib/i18n';
  import Kbd from './Kbd.svelte';
  import { getField } from './field';

  type Size = 'sm' | 'md' | 'lg';

  interface Props {
    value?: string;
    placeholder?: string;
    // Key hint shown while the field is empty; empty string hides it.
    shortcut?: string;
    size?: Size;
    fullWidth?: boolean;
    label?: string;
    onClear?: () => void;
    oninput?: (e: Event) => void;
    onkeydown?: (e: KeyboardEvent) => void;
    input?: HTMLInputElement;
  }

  let {
    value = $bindable(''),
    placeholder,
    shortcut = '',
    size = 'md',
    fullWidth = true,
    label,
    onClear,
    oninput,
    onkeydown,
    input = $bindable(),
  }: Props = $props();

  const field = getField();

  function clear() {
    value = '';
    onClear?.();
    input?.focus();
  }
</script>

<div class="search search-{size}" class:full={fullWidth}>
  <svg
    class="glyph"
    width="17"
    height="17"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    stroke-width="2"
    stroke-linecap="round"
    stroke-linejoin="round"
    aria-hidden="true"><circle cx="11" cy="11" r="7" /><path d="m21 21-4.3-4.3" /></svg
  >
  <input
    bind:this={input}
    bind:value
    type="search"
    placeholder={placeholder ?? $t('ui.search')}
    id={field?.id}
    aria-label={label ?? (field ? undefined : (placeholder ?? $t('ui.search')))}
    aria-describedby={field?.describedBy}
    {oninput}
    {onkeydown}
  />
  {#if value}
    <button type="button" class="clear" aria-label={$t('ui.clear')} onclick={clear}>×</button>
  {:else if shortcut}
    <Kbd>{shortcut}</Kbd>
  {/if}
</div>

<style>
  .search {
    display: inline-flex;
    align-items: center;
    gap: 10px;
    box-sizing: border-box;
    padding: 0 8px 0 16px;
    border: 1px solid var(--border-strong);
    border-radius: var(--radius-pill);
    background: var(--surface-inset);
    transition:
      border-color var(--dur-fast) var(--ease-standard),
      box-shadow var(--dur-fast) var(--ease-standard);
  }
  .full {
    display: flex;
    width: 100%;
  }
  .search:focus-within {
    border-color: var(--accent);
    box-shadow: var(--ring-shadow);
  }
  .search-sm {
    height: 36px;
  }
  .search-md {
    height: 44px;
  }
  .search-lg {
    height: 52px;
  }
  .glyph {
    flex: 0 0 auto;
    color: var(--text-subtle);
  }
  input {
    flex: 1;
    min-width: 0;
    padding: 0;
    border: 0;
    outline: none;
    background: transparent;
    color: var(--text-strong);
    font: inherit;
    font-size: var(--text-base);
  }
  input::placeholder {
    color: var(--text-subtle);
  }
  /* The own clear button replaces the engine's. */
  input::-webkit-search-cancel-button {
    display: none;
  }
  .clear {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 26px;
    height: 26px;
    padding: 0;
    border: 0;
    border-radius: var(--radius-pill);
    background: var(--surface-active);
    color: var(--text-muted);
    font-size: 15px;
    line-height: 1;
    cursor: pointer;
  }
  .clear:hover {
    color: var(--text);
  }
</style>
