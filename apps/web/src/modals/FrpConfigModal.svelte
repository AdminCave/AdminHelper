<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import Modal from '$lib/components/ui/Modal.svelte';
  import Button from '$lib/components/ui/Button.svelte';
  import FormField from '$lib/components/ui/FormField.svelte';
  import Input from '$lib/components/ui/Input.svelte';
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

  // The port fields hold strings, but Svelte reads a number input back as a number, and an emptied
  // one as null (to_number in its input bindings); num() takes all three.
  type NumberField = string | number | null;

  let name = $state('');
  let serverAddr = $state('');
  let bindPort = $state('7000');
  let vhostPort = $state('');
  let authToken = $state('');
  let subdomainHost = $state('');
  let maxPorts = $state('');
  let dashboardPort = $state('');
  let dashboardUser = $state('');
  let dashboardPassword = $state('');
  let submitting = $state(false);
  // The host port the stack publishes for frps; null while unknown, and then nothing is warned.
  let publishedBindPort = $state<number | null>(null);

  $effect(() => {
    if (open) {
      name = editing?.name ?? '';
      serverAddr = editing?.serverAddr ?? '';
      bindPort = String(editing?.bindPort ?? 7000);
      vhostPort = String(editing?.vhostHttpsPort ?? '');
      // Secrets are never pre-filled — leaving them empty when editing keeps the
      // stored value unchanged (the GET masks them anyway, so there is nothing
      // to round-trip). Same pattern as the password field in UserModal.
      authToken = '';
      subdomainHost = editing?.subdomainHost ?? '';
      maxPorts = String(editing?.maxPortsPerClient ?? '');
      dashboardPort = String(editing?.dashboardPort ?? '');
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
  <form class="form" onsubmit={onSubmit} id="frp-config-form">
    <FormField label={$t('label.name')} id="fcName" required>
      <Input required bind:value={name} />
    </FormField>
    <FormField label={$t('modal.frpConfig.serverAddr')} id="fcServerAddr" required>
      <Input required placeholder="frps.example.net" bind:value={serverAddr} />
    </FormField>
    <div class="bind" class:warn={portMismatch}>
      <FormField
        label={$t('modal.frpConfig.bindPort')}
        id="fcBindPort"
        hint={portMismatch
          ? $t('modal.frpConfig.bindPortMismatch', { port: publishedBindPort })
          : undefined}
      >
        <Input type="number" bind:value={bindPort} />
      </FormField>
    </div>
    <FormField label={$t('modal.frpConfig.vhostPort')} id="fcVhostPort">
      <Input type="number" bind:value={vhostPort} />
    </FormField>
    <div class="full">
      <FormField label={$t('modal.frpConfig.authToken')} id="fcAuthToken">
        <Input
          type="password"
          placeholder={$t('modal.frpConfig.authTokenPlaceholder')}
          bind:value={authToken}
        />
      </FormField>
    </div>
    <div class="full">
      <FormField label={$t('modal.frpConfig.subdomainHost')} id="fcSubdomainHost">
        <Input placeholder="ops.example.net" bind:value={subdomainHost} />
      </FormField>
    </div>
    <FormField label={$t('modal.frpConfig.maxPorts')} id="fcMaxPorts">
      <Input type="number" bind:value={maxPorts} />
    </FormField>
    <FormField label={$t('modal.frpConfig.dashPort')} id="fcDashPort">
      <Input type="number" bind:value={dashboardPort} />
    </FormField>
    <FormField label={$t('modal.frpConfig.dashUser')} id="fcDashUser">
      <Input bind:value={dashboardUser} />
    </FormField>
    <FormField label={$t('modal.frpConfig.dashPass')} id="fcDashPass">
      <Input type="password" bind:value={dashboardPassword} />
    </FormField>
  </form>
  {#snippet footer()}
    <Button variant="ghost" onclick={onClose}>{$t('action.cancel')}</Button>
    <Button variant="primary" type="submit" disabled={submitting} form="frp-config-form">
      {$t('action.save')}
    </Button>
  {/snippet}
</Modal>

<style>
  .form {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: var(--space-4);
  }
  .full {
    grid-column: 1 / -1;
  }
  .warn :global(.msg) {
    color: var(--warning);
  }
</style>
