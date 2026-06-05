<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  interface Props {
    size?: number;
  }
  let { size = 20 }: Props = $props();
</script>

<span class="spinner-inline" style:--size="{size}px" aria-hidden="true"></span>

<style>
  .spinner-inline {
    display: inline-block;
    width: var(--size);
    height: var(--size);
    border: 2px solid var(--border, #334155);
    border-top-color: var(--accent, #3b82f6);
    border-radius: 50%;
    animation: spin 0.8s linear infinite;
    vertical-align: middle;
  }
  @keyframes spin {
    to {
      transform: rotate(360deg);
    }
  }
</style>
