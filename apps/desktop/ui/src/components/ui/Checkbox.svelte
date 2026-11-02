<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  interface Props {
    checked?: boolean;
    disabled?: boolean;
    label?: string;
    description?: string;
    name?: string;
    onChange?: (checked: boolean) => void;
  }

  let {
    checked = $bindable(false),
    disabled = false,
    label,
    description,
    name,
    onChange,
  }: Props = $props();
</script>

<!-- A native checkbox under the drawn box: Space and form submit are the platform's. -->
<label class="check" class:disabled>
  <input
    type="checkbox"
    bind:checked
    {name}
    {disabled}
    aria-label={label ? undefined : name}
    onchange={() => onChange?.(checked)}
  />
  <span class="box" aria-hidden="true">
    {#if checked}
      <svg
        width="13"
        height="13"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        stroke-width="3"
        stroke-linecap="round"
        stroke-linejoin="round"><path d="M20 6 9 17l-5-5" /></svg
      >
    {/if}
  </span>
  {#if label}
    <span class="text">
      <span class="label">{label}</span>
      {#if description}<span class="desc">{description}</span>{/if}
    </span>
  {/if}
</label>

<style>
  .check {
    position: relative;
    display: inline-flex;
    align-items: flex-start;
    gap: 10px;
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
  .box {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    flex: 0 0 auto;
    box-sizing: border-box;
    width: 19px;
    height: 19px;
    border: 1px solid var(--border-strong);
    border-radius: var(--radius-xs);
    background: var(--surface-inset);
    color: var(--fill-solid-text);
    transition:
      background var(--dur-fast),
      border-color var(--dur-fast);
  }
  input:checked + .box {
    border-color: transparent;
    background: var(--fill-solid);
  }
  input:focus-visible + .box {
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
