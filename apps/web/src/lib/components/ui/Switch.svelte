<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import { getField } from './field';

  interface Props {
    checked?: boolean;
    disabled?: boolean;
    size?: 'sm' | 'md';
    label?: string;
    id?: string;
    onChange?: (checked: boolean) => void;
  }

  let {
    checked = $bindable(false),
    disabled = false,
    size = 'md',
    label,
    id,
    onChange,
  }: Props = $props();

  const field = getField();

  function toggle() {
    checked = !checked;
    onChange?.(checked);
  }
</script>

<!-- A native button: Space and Enter toggle it without a key handler of our own. -->
{#snippet control()}
  <button
    type="button"
    role="switch"
    class="switch switch-{size}"
    id={id ?? field?.id}
    aria-checked={checked}
    aria-label={label}
    aria-labelledby={label ? undefined : field?.labelId}
    aria-describedby={field?.describedBy}
    {disabled}
    onclick={toggle}
  >
    <span class="knob"></span>
  </button>
{/snippet}

{#if label}
  <label class="wrap" class:disabled>
    {@render control()}
    <span class="text">{label}</span>
  </label>
{:else}
  {@render control()}
{/if}

<style>
  .wrap {
    display: inline-flex;
    align-items: center;
    gap: 10px;
    color: var(--text);
    font-size: var(--text-base);
    cursor: pointer;
  }
  .wrap.disabled {
    cursor: not-allowed;
  }
  .switch {
    --w: 44px;
    --h: 24px;
    --k: 18px;
    display: inline-flex;
    align-items: center;
    flex: 0 0 auto;
    box-sizing: border-box;
    width: var(--w);
    height: var(--h);
    padding: calc((var(--h) - var(--k)) / 2 - 1px);
    border: 1px solid var(--border-strong);
    border-radius: var(--radius-pill);
    background: var(--surface-active);
    cursor: pointer;
    transition: background var(--dur-base) var(--ease-out);
  }
  .switch-sm {
    --w: 36px;
    --h: 20px;
    --k: 14px;
  }
  .switch:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }
  .knob {
    width: var(--k);
    height: var(--k);
    border-radius: var(--radius-pill);
    background: var(--text-muted);
    transition:
      transform var(--dur-base) var(--ease-out),
      background var(--dur-base);
  }
  .switch[aria-checked='true'] {
    border-color: transparent;
    background: var(--fill-solid);
  }
  .switch[aria-checked='true'] .knob {
    background: var(--fill-solid-text);
    transform: translateX(calc(var(--w) - var(--h)));
  }
</style>
