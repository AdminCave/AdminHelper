<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import { t } from '$lib/i18n';

  interface Props {
    size?: number;
    stroke?: number;
    label?: string;
  }

  let { size = 18, stroke = 2, label }: Props = $props();
</script>

<span
  class="spinner"
  role="status"
  aria-label={label ?? $t('loading.generic')}
  style:width="{size}px"
  style:height="{size}px"
  style:border-width="{stroke}px"
></span>

<style>
  .spinner {
    display: inline-block;
    flex: 0 0 auto;
    box-sizing: border-box;
    border-style: solid;
    border-color: currentColor;
    border-top-color: transparent;
    border-radius: var(--radius-pill);
    animation: ac-spin 0.6s linear infinite;
  }
  @keyframes ac-spin {
    to {
      transform: rotate(360deg);
    }
  }
  @media (prefers-reduced-motion: reduce) {
    .spinner {
      animation-duration: 1.8s;
    }
  }
</style>
