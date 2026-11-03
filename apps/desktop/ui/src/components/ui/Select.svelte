<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import { t } from '$lib/i18n';
  import { getField } from './field';

  type Size = 'sm' | 'md' | 'lg';
  type Option = { value: string; label: string } | string;

  interface Props {
    value?: string;
    options: Option[];
    placeholder?: string;
    size?: Size;
    disabled?: boolean;
    fullWidth?: boolean;
    id?: string;
    name?: string;
    onChange?: (value: string) => void;
  }

  let {
    value = $bindable(''),
    options,
    placeholder,
    size = 'md',
    disabled = false,
    fullWidth = false,
    id,
    name,
    onChange,
  }: Props = $props();

  const field = getField();
  const norm = $derived(options.map((o) => (typeof o === 'string' ? { value: o, label: o } : o)));
</script>

<!-- A native select under the pill: keyboard, type-ahead and form submit stay the platform's. -->
<span class="select select-{size}" class:full={fullWidth} class:disabled>
  <select
    bind:value
    id={id ?? field?.id}
    {name}
    {disabled}
    aria-invalid={field?.invalid || undefined}
    aria-describedby={field?.describedBy}
    onchange={() => onChange?.(value)}
  >
    {#if value === ''}
      <option value="" disabled>{placeholder ?? $t('ui.select')}</option>
    {/if}
    {#each norm as o (o.value)}
      <option value={o.value}>{o.label}</option>
    {/each}
  </select>
  <svg
    class="chevron"
    width="14"
    height="14"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    stroke-width="2"
    stroke-linecap="round"
    stroke-linejoin="round"
    aria-hidden="true"><path d="m6 9 6 6 6-6" /></svg
  >
</span>

<style>
  .select {
    position: relative;
    display: inline-flex;
    align-items: center;
  }
  .full {
    display: flex;
    width: 100%;
  }
  .disabled {
    opacity: 0.5;
  }
  select {
    width: 100%;
    box-sizing: border-box;
    padding: 0 36px 0 14px;
    border: 1px solid var(--border-strong);
    border-radius: var(--radius-pill);
    background: var(--surface-inset);
    color: var(--text-strong);
    font: inherit;
    appearance: none;
    cursor: pointer;
    transition:
      border-color var(--dur-fast) var(--ease-standard),
      box-shadow var(--dur-fast) var(--ease-standard);
  }
  select:focus-visible {
    outline: none;
    border-color: var(--accent);
    box-shadow: var(--ring-shadow);
  }
  select[aria-invalid='true'] {
    border-color: var(--danger-border);
  }
  select:disabled {
    cursor: not-allowed;
  }
  .select-sm select {
    height: 34px;
    font-size: var(--text-sm);
  }
  .select-md select {
    height: 42px;
    font-size: var(--text-base);
  }
  .select-lg select {
    height: 50px;
    font-size: var(--text-lg);
  }
  .chevron {
    position: absolute;
    right: 14px;
    color: var(--text-subtle);
    pointer-events: none;
  }
</style>
