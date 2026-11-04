<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import { filteredChecks } from '$lib/stores/monitoring';
  import { computeSummary } from '$lib/models/monitoring';
  import { t } from '$lib/i18n';
  import Dot from '../ui/Dot.svelte';

  let summary = $derived(computeSummary($filteredChecks));
</script>

<div class="mon-summary-cards" id="monSummaryCards">
  <div class="mon-summary-card">
    <div>
      <div class="mon-summary-value">{summary.total}</div>
      <div class="mon-summary-label">{$t('monitoring.summary.total')}</div>
    </div>
  </div>
  <div class="mon-summary-card mon-summary-ok">
    <Dot st="ok" size={10} ring />
    <div>
      <div class="mon-summary-value">{summary.ok}</div>
      <div class="mon-summary-label">{$t('monitoring.status.ok')}</div>
    </div>
  </div>
  <div class="mon-summary-card mon-summary-warning">
    <Dot st="warning" size={10} ring />
    <div>
      <div class="mon-summary-value">{summary.warning}</div>
      <div class="mon-summary-label">{$t('monitoring.status.warning')}</div>
    </div>
  </div>
  <div class="mon-summary-card mon-summary-critical">
    <Dot st="critical" size={10} ring />
    <div>
      <div class="mon-summary-value">{summary.critical}</div>
      <div class="mon-summary-label">{$t('monitoring.status.critical')}</div>
    </div>
  </div>
</div>

<style>
  .mon-summary-cards {
    display: flex;
    flex-wrap: wrap;
    gap: 14px;
  }
  .mon-summary-card {
    display: flex;
    flex: 1 1 140px;
    align-items: center;
    gap: 14px;
    padding: 14px 18px;
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    background: var(--surface);
  }
  .mon-summary-value {
    color: var(--text-strong);
    font-family: var(--font-mono);
    font-size: 26px;
    font-variant-numeric: tabular-nums;
    font-weight: 600;
    line-height: 1;
  }
  .mon-summary-label {
    margin-top: 6px;
    color: var(--text-muted);
    font-size: 12px;
    white-space: nowrap;
  }
</style>
