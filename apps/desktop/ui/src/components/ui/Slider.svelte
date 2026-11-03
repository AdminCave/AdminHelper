<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import { getField } from './field';

  interface Props {
    value?: number;
    min?: number;
    max?: number;
    step?: number;
    label?: string;
    showValue?: boolean;
    suffix?: string;
    disabled?: boolean;
    id?: string;
    onChange?: (value: number) => void;
  }

  const uid = $props.id();
  let {
    value = $bindable(50),
    min = 0,
    max = 100,
    step = 1,
    label,
    showValue = false,
    suffix = '',
    disabled = false,
    id,
    onChange,
  }: Props = $props();

  const field = getField();
  const inputId = $derived(id ?? field?.id ?? `${uid}-range`);
  const pct = $derived(max > min ? ((value - min) / (max - min)) * 100 : 0);
</script>

<div class="slider" class:disabled>
  {#if label || showValue}
    <div class="head">
      {#if label}<label class="label" for={inputId}>{label}</label>{/if}
      {#if showValue}<span class="value">{value}{suffix}</span>{/if}
    </div>
  {/if}
  <!-- A native range: arrow keys, Home/End and PageUp/Down stay the platform's. -->
  <input
    type="range"
    id={inputId}
    {min}
    {max}
    {step}
    {disabled}
    bind:value
    aria-describedby={field?.describedBy}
    aria-valuetext={suffix ? `${value}${suffix}` : undefined}
    style:--pct="{pct}%"
    oninput={() => onChange?.(value)}
  />
</div>

<style>
  .slider {
    width: 100%;
  }
  .disabled {
    opacity: 0.5;
  }
  .head {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    margin-bottom: 10px;
  }
  .label {
    color: var(--text-muted);
    font-size: var(--text-sm);
  }
  .value {
    color: var(--text-strong);
    font-family: var(--font-mono);
    font-size: 13px;
  }
  input {
    width: 100%;
    height: 20px;
    margin: 0;
    background: transparent;
    appearance: none;
    cursor: pointer;
  }
  input:disabled {
    cursor: not-allowed;
  }
  input::-webkit-slider-runnable-track {
    height: 5px;
    border-radius: var(--radius-pill);
    background: linear-gradient(
      to right,
      var(--fill-solid) var(--pct),
      var(--surface-active) var(--pct)
    );
  }
  input::-webkit-slider-thumb {
    width: 18px;
    height: 18px;
    margin-top: -6.5px;
    border: 2px solid var(--bg);
    border-radius: var(--radius-pill);
    background: var(--fill-solid);
    box-shadow: var(--shadow-sm);
    appearance: none;
  }
  input:focus-visible {
    outline: none;
  }
  input:focus-visible::-webkit-slider-thumb {
    box-shadow: var(--ring-shadow);
  }
</style>
