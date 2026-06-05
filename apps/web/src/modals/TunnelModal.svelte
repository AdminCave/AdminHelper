<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import Modal from '$lib/components/ui/Modal.svelte';
  import Button from '$lib/components/ui/Button.svelte';
  import { t } from '$lib/i18n';
  import { frpTunnels } from '$lib/stores/frp';
  import { servers as serversStore } from '$lib/stores/servers';
  import { showToast } from '$lib/stores/notifications';
  import { parseTags } from '$lib/utils/tags';
  import type {
    FrpTunnel,
    FrpTunnelInput,
    FrpTunnelType,
    FrpProtocol,
    FrpConfig,
    Server,
  } from '$lib/api/types';

  interface Props {
    open: boolean;
    editing: FrpTunnel | null;
    config: FrpConfig;
    onClose: () => void;
  }

  let { open, editing, config, onClose }: Props = $props();

  let serverId = $state('');
  let tunnelName = $state('');
  let tunnelType = $state<FrpTunnelType>('stcp');
  let protocol = $state<FrpProtocol>('ssh');
  let localIp = $state('127.0.0.1');
  let localPort = $state<number | ''>('');
  let secretKey = $state('');
  let visitorPort = $state<number | ''>('');
  let customDomains = $state('');
  let tagsInput = $state('');
  let autoConn = $state(false);
  let autoConnUser = $state('');
  let submitting = $state(false);

  const serverList = $derived<Server[]>($serversStore);

  $effect(() => {
    if (open) {
      serverId = editing?.serverId ?? '';
      tunnelName = editing?.name ?? '';
      tunnelType = editing?.tunnelType ?? 'stcp';
      protocol = editing?.protocol ?? 'ssh';
      localIp = editing?.localIp ?? '127.0.0.1';
      localPort = editing?.localPort ?? '';
      secretKey = editing?.secretKey ?? '';
      visitorPort = editing?.visitorPort ?? '';
      customDomains = editing?.customDomains ?? '';
      tagsInput = (editing?.tags ?? []).join(', ');
      autoConn = !!editing?.connectionId;
      autoConnUser = '';
    }
  });

  const isStcp = $derived(tunnelType === 'stcp');

  function onServerChange() {
    if (!tagsInput.trim()) {
      const server = serverList.find((s) => s.id === serverId);
      if (server && server.tags && server.tags.length > 0) {
        tagsInput = server.tags.join(', ');
      }
    }
  }

  function onProtocolChange() {
    if (localPort === '') {
      if (protocol === 'ssh') localPort = 22;
      else if (protocol === 'rdp') localPort = 3389;
      else if (protocol === 'web') localPort = 8006;
    }
  }

  async function onSubmit(e: SubmitEvent) {
    e.preventDefault();
    submitting = true;
    try {
      const data: FrpTunnelInput = {
        server_id: serverId,
        frp_config_id: config.id,
        name: tunnelName.trim(),
        tunnel_type: tunnelType,
        protocol,
        local_ip: localIp.trim(),
        local_port: Number(localPort),
        secret_key: secretKey.trim() || null,
        custom_domains: customDomains.trim() || null,
        visitor_port: visitorPort === '' ? null : Number(visitorPort),
        auto_create_connection: autoConn,
        auto_connection_username: autoConnUser.trim() || null,
        tags: parseTags(tagsInput),
      };
      if (editing) {
        await frpTunnels.update(editing.id, data);
        showToast($t('toast.tunnel.saved'));
      } else {
        await frpTunnels.create(data);
        showToast($t('toast.tunnel.created'));
      }
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
  title={editing ? $t('modal.tunnel.title') : $t('modal.tunnel.titleNew')}
  width="720px"
  {onClose}
>
  <form class="modal-form" onsubmit={onSubmit} id="tunnel-form">
    <div class="field full">
      <label for="ftServer">{$t('modal.tunnel.server')} *</label>
      <select id="ftServer" required bind:value={serverId} onchange={onServerChange}>
        <option value="">{$t('modal.tunnel.selectServer')}</option>
        {#each serverList as s (s.id)}
          <option value={s.id}>{s.name} ({s.hostname})</option>
        {/each}
      </select>
    </div>
    <div class="field">
      <label for="ftName">{$t('label.name')} *</label>
      <input id="ftName" required placeholder="k01-lnx1-ssh" bind:value={tunnelName} />
    </div>
    <div class="field">
      <label for="ftType">{$t('label.type')} *</label>
      <select id="ftType" bind:value={tunnelType}>
        <option value="stcp">STCP</option>
        <option value="https">HTTPS</option>
      </select>
    </div>
    <div class="field">
      <label for="ftProtocol">{$t('modal.tunnel.protocol')}</label>
      <select id="ftProtocol" bind:value={protocol} onchange={onProtocolChange}>
        <option value="ssh">SSH</option>
        <option value="rdp">RDP</option>
        <option value="web">Web</option>
      </select>
    </div>
    <div class="field">
      <label for="ftLocalIp">{$t('modal.tunnel.localIp')}</label>
      <input id="ftLocalIp" bind:value={localIp} />
    </div>
    <div class="field">
      <label for="ftLocalPort">{$t('modal.tunnel.localPort')} *</label>
      <input id="ftLocalPort" type="number" required bind:value={localPort} />
    </div>
    {#if isStcp}
      <div class="field full">
        <label for="ftSecret">{$t('modal.tunnel.secretKey')}</label>
        <input
          id="ftSecret"
          placeholder={$t('modal.tunnel.secretPlaceholder')}
          bind:value={secretKey}
        />
      </div>
      <div class="field">
        <label for="ftVisitorPort">{$t('modal.tunnel.visitorPort')}</label>
        <input id="ftVisitorPort" type="number" bind:value={visitorPort} />
      </div>
    {:else}
      <div class="field full">
        <label for="ftDomains">{$t('modal.tunnel.customDomains')}</label>
        <input id="ftDomains" placeholder="tunnel.example.net" bind:value={customDomains} />
      </div>
    {/if}
    <div class="field full">
      <label for="ftTags">{$t('modal.server.tagsComma')}</label>
      <input id="ftTags" placeholder="prod, web" bind:value={tagsInput} />
    </div>
    <div class="field full">
      <label style="display:flex;align-items:center;gap:8px">
        <input type="checkbox" bind:checked={autoConn} />
        {$t('modal.tunnel.autoConnection')}
      </label>
    </div>
    {#if autoConn}
      <div class="field full">
        <label for="ftAutoConnUser">{$t('modal.tunnel.autoConnUser')}</label>
        <input id="ftAutoConnUser" bind:value={autoConnUser} />
      </div>
    {/if}
  </form>
  {#snippet footer()}
    <Button variant="ghost" onclick={onClose}>{$t('action.cancel')}</Button>
    <Button
      variant="primary"
      type="submit"
      disabled={submitting}
      onclick={() => (document.getElementById('tunnel-form') as HTMLFormElement)?.requestSubmit()}
    >
      {$t('action.save')}
    </Button>
  {/snippet}
</Modal>
