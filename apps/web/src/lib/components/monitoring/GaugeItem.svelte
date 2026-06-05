<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import { TEMP_GAUGE_MAX } from '$lib/utils/monitoring';

  interface Props {
    label: string;
    value: number;
    cls: 'gauge-ok' | 'gauge-warn' | 'gauge-crit';
    detail?: string | null;
    metric?: string | null;
    unit?: string;
    active?: boolean;
    onClick?: () => void;
  }

  let {
    label,
    value,
    cls,
    detail = null,
    metric = null,
    unit = '%',
    active = false,
    onClick,
  }: Props = $props();

  const isTemp = $derived(unit === '\u00b0C');
  const barWidth = $derived(
    isTemp ? Math.min((value / TEMP_GAUGE_MAX) * 100, 100) : Math.min(value, 100),
  );
  const display = $derived(isTemp ? `${value.toFixed(1)}\u00b0C` : `${value.toFixed(1)}%`);
  const clickable = $derived(!!metric && !!onClick);
</script>

<div
  class="mon-gauge-item"
  class:mon-gauge-clickable={clickable}
  class:mon-gauge-active={active}
  role={clickable ? 'button' : undefined}
  tabindex={clickable ? 0 : undefined}
  onclick={() => clickable && onClick?.()}
  onkeydown={(e) => {
    if (clickable && (e.key === 'Enter' || e.key === ' ')) {
      e.preventDefault();
      onClick?.();
    }
  }}
>
  <span class="mon-gauge-label">{label}</span>
  <div class="mon-gauge-bar">
    <div class="mon-gauge-fill {cls}" style="width:{barWidth}%"></div>
    <span class="mon-gauge-text">{display}</span>
  </div>
  {#if detail}
    <span class="mon-gauge-detail">{detail}</span>
  {/if}
</div>
