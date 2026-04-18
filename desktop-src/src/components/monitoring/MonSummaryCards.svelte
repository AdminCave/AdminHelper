<script lang="ts">
  import { filteredChecks } from '$lib/stores/monitoring';
  import { computeSummary } from '$lib/models/monitoring';

  let summary = $derived(computeSummary($filteredChecks));
</script>

<div class="mon-summary-cards" id="monSummaryCards">
  <div class="mon-summary-card">
    <div class="mon-summary-value">{summary.total}</div>
    <div class="mon-summary-label">Gesamt</div>
  </div>
  <div class="mon-summary-card mon-summary-ok">
    <div class="mon-summary-value">{summary.ok}</div>
    <div class="mon-summary-label">OK</div>
  </div>
  <div class="mon-summary-card mon-summary-warning">
    <div class="mon-summary-value">{summary.warning}</div>
    <div class="mon-summary-label">Warnung</div>
  </div>
  <div class="mon-summary-card mon-summary-critical">
    <div class="mon-summary-value">{summary.critical}</div>
    <div class="mon-summary-label">Kritisch</div>
  </div>
</div>
