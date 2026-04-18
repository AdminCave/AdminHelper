<script lang="ts">
  import { monitoringChecks, monitoringServers, monitoring, setFilter } from '$lib/stores/monitoring';

  let serverIds = $derived(
    [...new Set($monitoringChecks.map((c) => c.serverId).filter(Boolean) as string[])].sort(),
  );
  let types = $derived([...new Set($monitoringChecks.map((c) => c.checkType))].sort());

  function serverLabel(id: string): string {
    const srv = $monitoringServers.find((s) => s.id === id);
    return srv ? srv.name || srv.hostname || id : id;
  }

  let filters = $derived($monitoring.filters);
</script>

<div class="mon-filter-bar" id="monFilterBar">
  <select
    class="mon-filter-select"
    value={filters.server}
    onchange={(e) => setFilter('server', (e.currentTarget as HTMLSelectElement).value)}
  >
    <option value="">Alle Server</option>
    {#each serverIds as id}
      <option value={id}>{serverLabel(id)}</option>
    {/each}
  </select>

  <select
    class="mon-filter-select"
    value={filters.type}
    onchange={(e) => setFilter('type', (e.currentTarget as HTMLSelectElement).value)}
  >
    <option value="">Alle Typen</option>
    {#each types as tp}
      <option value={tp}>{tp.toUpperCase()}</option>
    {/each}
  </select>

  <select
    class="mon-filter-select"
    value={filters.status}
    onchange={(e) => setFilter('status', (e.currentTarget as HTMLSelectElement).value)}
  >
    <option value="">Alle Status</option>
    <option value="ok">OK</option>
    <option value="warning">Warning</option>
    <option value="critical">Critical</option>
    <option value="unknown">Unknown</option>
    <option value="pending">Pending</option>
  </select>

  <input
    type="search"
    class="mon-filter-search"
    placeholder="Suche…"
    value={filters.search}
    oninput={(e) => setFilter('search', (e.currentTarget as HTMLInputElement).value)}
  />
</div>
