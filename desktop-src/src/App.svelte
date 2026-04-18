<script lang="ts">
  import { onMount } from 'svelte';
  import { hydrate, ready, needsLogin } from '$lib/stores/session';
  import Login from './components/Login.svelte';
  import AppShell from './components/AppShell.svelte';

  onMount(() => {
    hydrate();
  });
</script>

{#if !$ready}
  <div class="app-shell" style="display: flex; align-items: center; justify-content: center;">
    <div style="color: var(--text-muted);">Lade…</div>
  </div>
{:else if $needsLogin}
  <Login />
{:else}
  <AppShell />
{/if}
