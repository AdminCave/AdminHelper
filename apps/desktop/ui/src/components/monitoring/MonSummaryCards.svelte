<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import { filteredChecks } from '$lib/stores/monitoring';
  import { computeSummary } from '$lib/models/monitoring';
  import { t } from '$lib/i18n';

  let summary = $derived(computeSummary($filteredChecks));
</script>

<div class="mon-summary-cards" id="monSummaryCards">
  <div class="mon-summary-card">
    <div class="mon-summary-value">{summary.total}</div>
    <div class="mon-summary-label">{$t('monitoring.summary.total')}</div>
  </div>
  <div class="mon-summary-card mon-summary-ok">
    <div class="mon-summary-value">{summary.ok}</div>
    <div class="mon-summary-label">{$t('monitoring.status.ok')}</div>
  </div>
  <div class="mon-summary-card mon-summary-warning">
    <div class="mon-summary-value">{summary.warning}</div>
    <div class="mon-summary-label">{$t('monitoring.status.warning')}</div>
  </div>
  <div class="mon-summary-card mon-summary-critical">
    <div class="mon-summary-value">{summary.critical}</div>
    <div class="mon-summary-label">{$t('monitoring.status.critical')}</div>
  </div>
</div>
