<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  // A numeric metric against its threshold: the bar is the value, the ticks are where warning and
  // critical start. Only a breached value takes colour; the text beside it stays the source.
  import type { Metric } from './model';
  import { meterOf } from './grammar';

  interface Props {
    metric: Metric;
    width?: number;
  }

  let { metric, width = 56 }: Props = $props();

  const scale = $derived(meterOf(metric));
</script>

{#if scale}
  <span
    class="meter"
    data-status={metric.status ?? 'ok'}
    style:width="{width}px"
    aria-hidden="true"
  >
    <span class="fill" style:width="{scale.fill}%"></span>
    {#if scale.warn !== undefined}<span class="tick warn" style:left="{scale.warn}%"></span>{/if}
    {#if scale.crit !== undefined}<span class="tick crit" style:left="{scale.crit}%"></span>{/if}
  </span>
{/if}

<style>
  .meter {
    position: relative;
    display: inline-block;
    flex: none;
    height: 6px;
    border-radius: var(--radius-pill);
    background: var(--surface-inset);
    box-shadow: inset 0 0 0 1px var(--border-faint);
    vertical-align: middle;
  }
  .fill {
    position: absolute;
    inset: 0 auto 0 0;
    border-radius: inherit;
    background: var(--text-subtle);
    transform-origin: left center;
    animation: fill-in 700ms var(--ease-out) 150ms backwards;
  }
  @keyframes fill-in {
    from {
      transform: scaleX(0);
    }
  }
  @media (prefers-reduced-motion: reduce) {
    .fill {
      animation: none;
    }
  }
  .meter[data-status='warning'] .fill {
    background: var(--warning);
  }
  .meter[data-status='critical'] .fill {
    background: var(--danger);
  }
  .tick {
    position: absolute;
    top: -2px;
    bottom: -2px;
    width: 2px;
    margin-left: -1px;
    border-radius: 1px;
  }
  .tick.warn {
    background: var(--warning);
  }
  .tick.crit {
    background: var(--danger);
  }
</style>
