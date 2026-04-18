<script lang="ts">
  import { monitoringAlerts, toggleAlert } from '$lib/stores/monitoring';
</script>

<div class="mon-alert-list" id="monAlertList">
  {#if $monitoringAlerts.length === 0}
    <div class="mon-empty">Keine Alert-Regeln</div>
  {:else}
    {#each $monitoringAlerts as rule (rule.id)}
      <div class="mon-alert-card">
        <div class="mon-alert-info">
          <div class="mon-alert-name">{rule.name}</div>
          <div class="mon-alert-meta">
            Channel: {rule.channel}
            {#if rule.matchSeverity}· Schweregrad: {rule.matchSeverity}{/if}
            · Cooldown: {rule.cooldownMinutes}m
          </div>
        </div>
        <div class="mon-alert-actions">
          <span class="mon-dot {rule.enabled ? 'mon-ok' : 'mon-unknown'}"></span>
          <button
            class="btn small {rule.enabled ? 'ghost' : 'primary'}"
            onclick={() => void toggleAlert(rule.id)}
          >
            {rule.enabled ? 'Deaktivieren' : 'Aktivieren'}
          </button>
        </div>
      </div>
    {/each}
  {/if}
</div>
