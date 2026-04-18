<script lang="ts">
  import type { MonitorCheck } from '$lib/api/types';
  import HeroPing from './HeroPing.svelte';
  import HeroAgentPing from './HeroAgentPing.svelte';
  import HeroResources from './HeroResources.svelte';
  import HeroService from './HeroService.svelte';
  import HeroDocker from './HeroDocker.svelte';
  import HeroProxmox from './HeroProxmox.svelte';
  import HeroZfs from './HeroZfs.svelte';
  import HeroSmart from './HeroSmart.svelte';

  interface Props { check: MonitorCheck; }
  let { check }: Props = $props();
</script>

{#if check.checkType === 'ping' || check.checkType === 'tcp' || check.checkType === 'http'}
  <HeroPing {check} />
{:else if check.checkType === 'agent_ping'}
  <HeroAgentPing {check} />
{:else if check.checkType === 'agent_resources'}
  <HeroResources {check} />
{:else if check.checkType === 'service_process'}
  <HeroService {check} />
{:else if check.checkType === 'docker_health'}
  <HeroDocker {check} />
{:else if check.checkType === 'proxmox_backup'}
  <HeroProxmox {check} />
{:else if check.checkType === 'zfs_health'}
  <HeroZfs {check} />
{:else if check.checkType === 'smart_health'}
  <HeroSmart {check} />
{/if}
