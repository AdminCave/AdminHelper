<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import { getField } from './field';

  type Option = { value: string; label: string; description?: string } | string;

  interface Props {
    options: Option[];
    value?: string;
    name?: string;
    disabled?: boolean;
    label?: string;
    onChange?: (value: string) => void;
  }

  const uid = $props.id();
  let {
    options,
    value = $bindable(''),
    name = uid,
    disabled = false,
    label,
    onChange,
  }: Props = $props();

  const field = getField();
  const norm = $derived(options.map((o) => (typeof o === 'string' ? { value: o, label: o } : o)));
</script>

<!-- Native radios with one name: the arrow keys move the choice as the platform does. -->
<div
  class="group"
  role="radiogroup"
  aria-label={label}
  aria-labelledby={label ? undefined : field?.labelId}
  aria-describedby={field?.describedBy}
>
  {#each norm as o (o.value)}
    <label class="opt" class:disabled>
      <input
        type="radio"
        {name}
        value={o.value}
        bind:group={value}
        {disabled}
        onchange={() => onChange?.(o.value)}
      />
      <span class="ring" aria-hidden="true"></span>
      <span class="text">
        <span class="label">{o.label}</span>
        {#if o.description}<span class="desc">{o.description}</span>{/if}
      </span>
    </label>
  {/each}
</div>

<style>
  .group {
    display: flex;
    flex-direction: column;
    gap: var(--space-3);
  }
  .opt {
    position: relative;
    display: flex;
    align-items: flex-start;
    gap: 11px;
    cursor: pointer;
  }
  .disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }
  input {
    position: absolute;
    width: 1px;
    height: 1px;
    margin: 0;
    opacity: 0;
  }
  .ring {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    flex: 0 0 auto;
    box-sizing: border-box;
    width: 19px;
    height: 19px;
    border: 1px solid var(--border-strong);
    border-radius: var(--radius-pill);
    background: var(--surface-inset);
    transition: border-color var(--dur-fast);
  }
  input:checked + .ring {
    border-color: var(--text-strong);
  }
  input:checked + .ring::after {
    content: '';
    width: 9px;
    height: 9px;
    border-radius: var(--radius-pill);
    background: var(--text-strong);
  }
  input:focus-visible + .ring {
    box-shadow: var(--ring-shadow);
  }
  .text {
    display: flex;
    flex-direction: column;
    gap: 2px;
  }
  .label {
    color: var(--text);
    font-size: var(--text-base);
    line-height: 1.3;
  }
  .desc {
    color: var(--text-muted);
    font-size: var(--text-sm);
    line-height: 1.4;
  }
</style>
