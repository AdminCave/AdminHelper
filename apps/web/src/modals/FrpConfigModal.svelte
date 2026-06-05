<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import Modal from '$lib/components/ui/Modal.svelte';
  import Button from '$lib/components/ui/Button.svelte';
  import { t } from '$lib/i18n';
  import { frpConfig } from '$lib/stores/frp';
  import { showToast } from '$lib/stores/notifications';
  import type { FrpConfig, FrpConfigInput } from '$lib/api/types';

  interface Props {
    open: boolean;
    editing: FrpConfig | null;
    onClose: () => void;
  }

  let { open, editing, onClose }: Props = $props();

  let name = $state('');
  let serverAddr = $state('');
  let bindPort = $state<number | ''>(7000);
  let vhostPort = $state<number | ''>('');
  let authToken = $state('');
  let subdomainHost = $state('');
  let maxPorts = $state<number | ''>('');
  let dashboardPort = $state<number | ''>('');
  let dashboardUser = $state('');
  let dashboardPassword = $state('');
  let submitting = $state(false);

  $effect(() => {
    if (open) {
      name = editing?.name ?? '';
      serverAddr = editing?.serverAddr ?? '';
      bindPort = editing?.bindPort ?? 7000;
      vhostPort = editing?.vhostHttpsPort ?? '';
      authToken = editing?.authToken ?? '';
      subdomainHost = editing?.subdomainHost ?? '';
      maxPorts = editing?.maxPortsPerClient ?? '';
      dashboardPort = editing?.dashboardPort ?? '';
      dashboardUser = editing?.dashboardUser ?? '';
      dashboardPassword = editing?.dashboardPassword ?? '';
    }
  });

  function num(v: number | ''): number | null {
    return v === '' ? null : Number(v);
  }

  async function onSubmit(e: SubmitEvent) {
    e.preventDefault();
    submitting = true;
    try {
      const data: FrpConfigInput = {
        name: name.trim(),
        server_addr: serverAddr.trim(),
        bind_port: num(bindPort) ?? 7000,
        vhost_https_port: num(vhostPort),
        auth_token: authToken.trim() || null,
        subdomain_host: subdomainHost.trim() || null,
        max_ports_per_client: num(maxPorts),
        dashboard_port: num(dashboardPort),
        dashboard_user: dashboardUser.trim() || null,
        dashboard_password: dashboardPassword.trim() || null,
      };
      await frpConfig.save(data, editing);
      showToast(editing ? $t('toast.frpConfig.saved') : $t('toast.frpConfig.created'));
      onClose();
    } catch (err) {
      showToast(err instanceof Error ? err.message : 'Fehler', 'error');
    } finally {
      submitting = false;
    }
  }
</script>

<Modal
  {open}
  title={editing ? $t('modal.frpConfig.title') : $t('modal.frpConfig.titleNew')}
  width="720px"
  {onClose}
>
  <form class="modal-form" onsubmit={onSubmit} id="frp-config-form">
    <div class="field">
      <label for="fcName">{$t('label.name')} *</label>
      <input id="fcName" required bind:value={name} />
    </div>
    <div class="field">
      <label for="fcServerAddr">{$t('modal.frpConfig.serverAddr')} *</label>
      <input id="fcServerAddr" required placeholder="frps.example.net" bind:value={serverAddr} />
    </div>
    <div class="field">
      <label for="fcBindPort">{$t('modal.frpConfig.bindPort')}</label>
      <input id="fcBindPort" type="number" bind:value={bindPort} />
    </div>
    <div class="field">
      <label for="fcVhostPort">{$t('modal.frpConfig.vhostPort')}</label>
      <input id="fcVhostPort" type="number" bind:value={vhostPort} />
    </div>
    <div class="field full">
      <label for="fcAuthToken">{$t('modal.frpConfig.authToken')}</label>
      <input
        id="fcAuthToken"
        placeholder={$t('modal.frpConfig.authTokenPlaceholder')}
        bind:value={authToken}
      />
    </div>
    <div class="field full">
      <label for="fcSubdomainHost">{$t('modal.frpConfig.subdomainHost')}</label>
      <input id="fcSubdomainHost" placeholder="ops.example.net" bind:value={subdomainHost} />
    </div>
    <div class="field">
      <label for="fcMaxPorts">{$t('modal.frpConfig.maxPorts')}</label>
      <input id="fcMaxPorts" type="number" bind:value={maxPorts} />
    </div>
    <div class="field">
      <label for="fcDashPort">{$t('modal.frpConfig.dashPort')}</label>
      <input id="fcDashPort" type="number" bind:value={dashboardPort} />
    </div>
    <div class="field">
      <label for="fcDashUser">{$t('modal.frpConfig.dashUser')}</label>
      <input id="fcDashUser" bind:value={dashboardUser} />
    </div>
    <div class="field">
      <label for="fcDashPass">{$t('modal.frpConfig.dashPass')}</label>
      <input id="fcDashPass" type="password" bind:value={dashboardPassword} />
    </div>
  </form>
  {#snippet footer()}
    <Button variant="ghost" onclick={onClose}>{$t('action.cancel')}</Button>
    <Button
      variant="primary"
      type="submit"
      disabled={submitting}
      onclick={() =>
        (document.getElementById('frp-config-form') as HTMLFormElement)?.requestSubmit()}
    >
      {$t('action.save')}
    </Button>
  {/snippet}
</Modal>
