<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import { t } from '$lib/i18n';
  import Dot from '../../ui/Dot.svelte';
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
  <span class="mon-section-icon" aria-hidden="true">
    <MonSectionIcon name={icon} />
  </span>
  <span class="mon-section-title">{title}</span>
  {#if count != null}
    <span class="mon-section-count">{count} {$t('monitoring.grid.checks')}</span>
  {/if}
  {#if subtitle}
    <span class="mon-section-sub">{subtitle}</span>
  {/if}
  <span class="mon-section-worst"><Dot st={worst} /></span>
</div>

<style>
  .mon-section-head {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 12px 16px;
  }
  .mon-section-icon {
    display: inline-flex;
    flex-shrink: 0;
    color: var(--text-muted);
  }
  .mon-section-title {
    color: var(--text-strong);
    font-size: 13.5px;
    font-weight: 600;
  }
  .mon-section-count,
  .mon-section-sub {
    color: var(--text-subtle);
    font-family: var(--font-mono);
    font-size: 11px;
  }
  .mon-section-worst {
    display: inline-flex;
    margin-left: auto;
  }
</style>
