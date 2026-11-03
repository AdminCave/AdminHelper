<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  interface Props {
    width?: string;
    height?: number;
    radius?: string;
    // Circular placeholder, e.g. for an avatar; width follows height.
    circle?: boolean;
    // Stacked lines; the last one is shortened.
    count?: number;
    gap?: number;
  }

  let {
    width = '100%',
    height = 14,
    radius = 'var(--radius-sm)',
    circle = false,
    count = 1,
    gap = 10,
  }: Props = $props();
</script>

<!-- Decoration only: the region that is loading announces itself (aria-busy). -->
<span class="skeleton" style:gap="{gap}px" aria-hidden="true">
  {#each { length: count }, i (i)}
    <span
      class="line"
      style:width={circle ? `${height}px` : count > 1 && i === count - 1 ? '70%' : width}
      style:height="{height}px"
      style:border-radius={circle ? 'var(--radius-pill)' : radius}
    ></span>
  {/each}
</span>

<style>
  .skeleton {
    display: flex;
    flex-direction: column;
  }
  .line {
    display: block;
    background: linear-gradient(
      90deg,
      var(--surface-inset) 0%,
      var(--surface-hover) 50%,
      var(--surface-inset) 100%
    );
    background-size: 200% 100%;
    animation: shimmer 1.4s ease-in-out infinite;
  }
  @media (prefers-reduced-motion: reduce) {
    .line {
      animation: none;
    }
  }
  @keyframes shimmer {
    0% {
      background-position: 200% 0;
    }
    100% {
      background-position: -200% 0;
    }
  }
</style>
