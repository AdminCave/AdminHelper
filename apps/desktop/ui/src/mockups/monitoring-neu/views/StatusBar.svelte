<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  // Objects by state as one segmented bar, worst first; every segment names its count on hover.
  // The bar never stands alone: the caller puts the figures or a legend beside it.
  import type { Status } from '../model';
  import { STATUS_LABEL } from '../grammar';
  import { BAR_ORDER } from './servers';

  interface Props {
    counts: Record<Status, number>;
    hidden?: number;
    /** 3 or 4 in a list, 8 beside figures, up to 28 with a legend. */
    height?: number;
    label?: string;
    /** Wipe the bar in from the left when it appears. */
    grow?: boolean;
  }

  let { counts, hidden = 0, height = 4, label, grow = false }: Props = $props();

  const segments = $derived([
    ...BAR_ORDER.filter((st) => counts[st] > 0).map((st) => ({
      st: st as string,
      n: counts[st],
      text: `${counts[st]} ${STATUS_LABEL[st]}`,
    })),
    ...(hidden ? [{ st: 'hidden', n: hidden, text: `${hidden} ausgeblendet` }] : []),
  ]);
</script>

<span
  class="status-bar"
  class:tall={height >= 16}
  class:grow
  style:height="{height}px"
  role="img"
  aria-label={label ?? segments.map((s) => s.text).join(', ')}
>
  {#each segments as s (s.st)}
    <span class="seg" data-st={s.st} style:flex-grow={s.n} title={s.text}></span>
  {/each}
</span>

<style>
  .status-bar {
    display: flex;
    gap: 1px;
    width: 100%;
    overflow: hidden;
    border-radius: var(--radius-pill);
  }
  .status-bar.tall {
    gap: 2px;
    border-radius: 4px;
  }
  .seg {
    flex-basis: 0;
    min-width: 3px;
    background: var(--border-strong);
  }
  .seg[data-st='critical'] {
    background: var(--danger);
  }
  .seg[data-st='warning'] {
    background: var(--warning);
  }
  .seg[data-st='unknown'],
  .seg[data-st='stale'] {
    background: var(--text-subtle);
  }
  .seg[data-st='info'] {
    background: var(--info);
  }
  .seg[data-st='not-collected'] {
    background: var(--border-strong);
  }
  .seg[data-st='ok'] {
    background: var(--success);
    opacity: 0.55;
  }
  .seg[data-st='hidden'] {
    background: var(--border);
  }
  .seg:hover {
    opacity: 1;
    filter: brightness(1.15);
  }
  .grow {
    animation: sb-wipe 900ms var(--ease-out) 120ms backwards;
  }
  @keyframes sb-wipe {
    from {
      clip-path: inset(0 100% 0 0 round 4px);
    }
    to {
      clip-path: inset(0 0 0 0 round 4px);
    }
  }
  @media (prefers-reduced-motion: reduce) {
    .grow {
      animation: none;
    }
  }
</style>
