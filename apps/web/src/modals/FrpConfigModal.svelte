<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import Modal from '$lib/components/ui/Modal.svelte';
  import Button from '$lib/components/ui/Button.svelte';
  import { confirmDialog } from '$lib/components/ui/ConfirmDialog.svelte';
  import { t } from '$lib/i18n';
  import { frpConfig } from '$lib/stores/frp';
  import { showToast, showError } from '$lib/stores/notifications';
  import { supervisorStatus } from '$lib/api/frp';
  import type { FrpConfig, FrpConfigInput } from '$lib/api/types';

  interface Props {
    open: boolean;
    editing: FrpConfig | null;
    onClose: () => void;
  }

  let { open, editing, onClose }: Props = $props();

  // '' until typed into; Svelte binds an emptied number input as null, not '' (to_number in its
  // input bindings).
  type NumberField = number | '' | null;

  let name = $state('');
  let serverAddr = $state('');
  let bindPort = $state<NumberField>(7000);
  let vhostPort = $state<NumberField>('');
  let authToken = $state('');
  let subdomainHost = $state('');
  let maxPorts = $state<NumberField>('');
  let dashboardPort = $state<NumberField>('');
  let dashboardUser = $state('');
  let dashboardPassword = $state('');
  let submitting = $state(false);
  // The host port the stack publishes for frps; null while unknown, and then nothing is warned.
  let publishedBindPort = $state<number | null>(null);

  $effect(() => {
    if (open) {
      name = editing?.name ?? '';
      serverAddr = editing?.serverAddr ?? '';
      bindPort = editing?.bindPort ?? 7000;
      vhostPort = editing?.vhostHttpsPort ?? '';
      // Secrets are never pre-filled — leaving them empty when editing keeps the
      // stored value unchanged (the GET masks them anyway, so there is nothing
      // to round-trip). Same pattern as the password field in UserModal.
      authToken = '';
      subdomainHost = editing?.subdomainHost ?? '';
      maxPorts = editing?.maxPortsPerClient ?? '';
      dashboardPort = editing?.dashboardPort ?? '';
      dashboardUser = editing?.dashboardUser ?? '';
      dashboardPassword = '';
    }
  });

  $effect(() => {
    if (open) void loadPublishedBindPort();
  });

  async function loadPublishedBindPort() {
    try {
      publishedBindPort = (await supervisorStatus()).publishedBindPort ?? null;
    } catch {
      // Network, 403, or 404 from a server without the route: no warning, no toast.
      publishedBindPort = null;
    }
  }

  function num(v: NumberField): number | null {
    return v === '' || v === null ? null : Number(v);
  }

  const portMismatch = $derived(
    publishedBindPort !== null && (num(bindPort) ?? 7000) !== publishedBindPort,
  );

  // Every field but name and server_addr lands in frps.toml, and frps restarts once that file
  // changes. Compared as sent against the stored values, an empty text and null alike; the
  // secrets count once typed, since the stored ones come back masked.
  function restartsFrps(data: FrpConfigInput, stored: FrpConfig): boolean {
    return (
      data.bind_port !== stored.bindPort ||
      data.vhost_https_port !== (stored.vhostHttpsPort ?? null) ||
      data.subdomain_host !== (stored.subdomainHost || null) ||
      data.max_ports_per_client !== (stored.maxPortsPerClient ?? null) ||
      data.dashboard_port !== (stored.dashboardPort ?? null) ||
      data.dashboard_user !== (stored.dashboardUser || null) ||
      data.auth_token !== undefined ||
      data.dashboard_password !== undefined
    );
  }

  function confirmRestart(newToken: boolean): Promise<boolean> {
    let message = $t('modal.frpConfig.confirm.restart');
    if (newToken) message += ` ${$t('modal.frpConfig.confirm.newToken')}`;
    return confirmDialog(message, { confirmLabel: $t('action.save') });
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
        subdomain_host: subdomainHost.trim() || null,
        max_ports_per_client: num(maxPorts),
        dashboard_port: num(dashboardPort),
        dashboard_user: dashboardUser.trim() || null,
      };
      // Secrets: send only when the operator typed something. Omitting them on
      // edit leaves the stored value untouched (PUT applies only sent fields);
      // on create an empty auth_token tells the server to auto-generate one.
      const trimmedToken = authToken.trim();
      const trimmedDashPass = dashboardPassword.trim();
      if (trimmedToken) {
        data.auth_token = trimmedToken;
      } else if (!editing) {
        data.auth_token = null;
      }
      if (trimmedDashPass) {
        data.dashboard_password = trimmedDashPass;
      } else if (!editing) {
        data.dashboard_password = null;
      }
      if (editing && restartsFrps(data, editing) && !(await confirmRestart(!!data.auth_token))) {
        return;
      }
      await frpConfig.save(data, editing);
      showToast(editing ? $t('toast.frpConfig.saved') : $t('toast.frpConfig.created'));
      onClose();
    } catch (err) {
      showError(err);
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
      <input
        id="fcBindPort"
        type="number"
        aria-describedby={portMismatch ? 'fcBindPortWarning' : undefined}
        bind:value={bindPort}
      />
      {#if portMismatch}
        <small
          id="fcBindPortWarning"
          style="color:var(--warning)"
          data-testid="frp-bind-port-warning"
        >
          {$t('modal.frpConfig.bindPortMismatch', { port: publishedBindPort })}
        </small>
      {/if}
    </div>
    <div class="field">
      <label for="fcVhostPort">{$t('modal.frpConfig.vhostPort')}</label>
      <input id="fcVhostPort" type="number" bind:value={vhostPort} />
    </div>
    <div class="field full">
      <label for="fcAuthToken">{$t('modal.frpConfig.authToken')}</label>
      <input
        id="fcAuthToken"
        type="password"
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
    <Button variant="primary" type="submit" disabled={submitting} form="frp-config-form">
      {$t('action.save')}
    </Button>
  {/snippet}
</Modal>
