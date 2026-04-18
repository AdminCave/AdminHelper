<script lang="ts">
  import { worstStatus, statusClass, type ServerGroup } from '$lib/models/monitoring';
  import MonCheckRow from './MonCheckRow.svelte';

  interface Props { group: ServerGroup; }
  let { group }: Props = $props();

  let worst = $derived(worstStatus(group.checks));
  let open = $state(true);

  function toggle(): void {
    open = !open;
  }
</script>

<div class="mon-server-group" class:open>
  <div
    class="mon-server-header"
    role="button"
    tabindex="0"
    onclick={toggle}
    onkeydown={(e) => e.key === 'Enter' && toggle()}
  >
    <span class="mon-chevron">▸</span>
    <span class="mon-dot {statusClass(worst)}"></span>
    <span class="mon-server-name">{group.serverName || group.serverId || 'Ohne Server'}</span>
    <span class="mon-server-count">{group.checks.length}</span>
  </div>
  <div class="mon-server-body">
    {#each group.checks as check (check.id)}
      <MonCheckRow {check} />
    {/each}
  </div>
</div>
