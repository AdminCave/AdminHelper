<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import type { Snippet } from 'svelte';

  interface Props {
    label?: string;
    for_?: string;
    required?: boolean;
    hint?: string;
    error?: string;
    children: Snippet;
  }

  let { label, for_, required = false, hint, error, children }: Props = $props();
</script>

<div class="field" class:has-error={!!error}>
  {#if label}
    <label for={for_}>
      {label}{#if required}<span class="req">*</span>{/if}
    </label>
  {/if}
  {@render children()}
  {#if hint && !error}
    <div class="field-hint">{hint}</div>
  {/if}
  {#if error}
    <div class="field-error">{error}</div>
  {/if}
</div>

<style>
  .req {
    color: var(--danger, #ef4444);
    margin-left: 2px;
  }
  .field-hint {
    font-size: 12px;
    color: var(--muted, #94a3b8);
    margin-top: 4px;
  }
  .field-error {
    font-size: 12px;
    color: var(--danger, #ef4444);
    margin-top: 4px;
  }
</style>
