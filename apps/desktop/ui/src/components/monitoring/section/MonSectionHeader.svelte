<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import { statusClass } from '$lib/models/monitoring';
  import MonSectionIcon from './MonSectionIcon.svelte';

  interface Props {
    icon: string;
    title: string;
    count?: number | null;
    worst?: string;
    subtitle?: string | null;
  }
  let { icon, title, count = null, worst = 'ok', subtitle = null }: Props = $props();
</script>

<div class="mon-section-head">
  <span class="mon-section-stripe {statusClass(worst)}"></span>
  <span class="mon-section-icon {statusClass(worst)}">
    <MonSectionIcon name={icon} />
  </span>
  <span class="mon-section-title">{title}</span>
  {#if count != null}
    <span class="mon-section-count">{count}</span>
  {/if}
  {#if subtitle}
    <span class="mon-section-sub">{subtitle}</span>
  {/if}
</div>
