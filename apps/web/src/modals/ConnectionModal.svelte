<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import Modal from '$lib/components/ui/Modal.svelte';
  import Button from '$lib/components/ui/Button.svelte';
  import { t } from '$lib/i18n';
  import { connections } from '$lib/stores/connections';
  import { servers } from '$lib/stores/servers';
  import { showToast } from '$lib/stores/notifications';
  import { parseTags } from '$lib/utils/tags';
  import type { Connection, ConnectionKind } from '$lib/api/types';

  interface Props {
    open: boolean;
    editing: Connection | null;
    onClose: () => void;
  }

  let { open, editing, onClose }: Props = $props();

  let name = $state('');
  let kind = $state<ConnectionKind>('ssh');
  let host = $state('');
  let port = $state('');
  let username = $state('');
  let domain = $state('');
  let url = $state('');
  let keyPath = $state('');
  let serverId = $state('');
  let tagsInput = $state('');
  let notes = $state('');
  let submitting = $state(false);

  $effect(() => {
    if (open) {
      name = editing?.name ?? '';
      kind = (editing?.kind as ConnectionKind) ?? 'ssh';
      host = editing?.host ?? '';
      port = editing?.port != null ? String(editing.port) : '';
      username = editing?.username ?? '';
      domain = editing?.domain ?? '';
      url = editing?.url ?? '';
      keyPath = editing?.keyPath ?? '';
      serverId = editing?.serverId ?? '';
      tagsInput = (editing?.tags ?? []).join(', ');
      notes = editing?.notes ?? '';
    }
  });

  // Visibility of the kind-dependent fields
  const showHost = $derived(kind !== 'web');
  const showPort = $derived(kind !== 'web');
  const showDomain = $derived(kind === 'rdp');
  const showUrl = $derived(kind === 'web');
  const showKey = $derived(kind === 'ssh');

  // Default port on kind change, when the field is empty
  $effect(() => {
    if (!showPort) return;
    if (port !== '') return;
    if (kind === 'ssh') port = '22';
    else if (kind === 'rdp') port = '3389';
  });

  async function onSubmit(e: SubmitEvent) {
    e.preventDefault();
    submitting = true;
    try {
      const data: Partial<Connection> = {
        name: name.trim(),
        kind,
        host: host.trim(),
        port: port ? Number.parseInt(port, 10) : null,
        username: username.trim(),
        domain: domain.trim(),
        url: url.trim(),
        keyPath: keyPath.trim(),
        tags: parseTags(tagsInput),
        notes: notes.trim(),
        trustCert: false,
        serverId: serverId || null,
      };
      if (editing) {
        await connections.update(editing.id, data);
        showToast($t('toast.connection.saved'));
      } else {
        await connections.create(data);
        showToast($t('toast.connection.created'));
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
  title={editing ? $t('modal.connection.title') : $t('modal.connection.titleNew')}
  width="720px"
  {onClose}
>
  <form class="conn-form" onsubmit={onSubmit} id="conn-form">
    <div class="field">
      <label for="cfName">{$t('label.name')} *</label>
      <input id="cfName" required placeholder="Mein Server" bind:value={name} />
    </div>
    <div class="field">
      <label for="cfKind">{$t('table.type')} *</label>
      <select id="cfKind" bind:value={kind}>
        <option value="ssh">SSH</option>
        <option value="rdp">RDP</option>
        <option value="web">Web</option>
      </select>
    </div>
    {#if showHost}
      <div class="field">
        <label for="cfHost">{$t('modal.connection.host')}</label>
        <input id="cfHost" placeholder="192.168.1.1" bind:value={host} />
      </div>
    {/if}
    {#if showPort}
      <div class="field">
        <label for="cfPort">{$t('modal.connection.port')}</label>
        <input id="cfPort" type="number" placeholder="22" bind:value={port} />
      </div>
    {/if}
    <div class="field">
      <label for="cfUser">{$t('modal.connection.username')}</label>
      <input id="cfUser" placeholder="root" bind:value={username} />
    </div>
    {#if showDomain}
      <div class="field">
        <label for="cfDomain">{$t('modal.connection.domain')}</label>
        <input id="cfDomain" placeholder="CORP" bind:value={domain} />
      </div>
    {/if}
    {#if showUrl}
      <div class="field">
        <label for="cfUrl">{$t('modal.connection.url')}</label>
        <input id="cfUrl" placeholder="https://..." bind:value={url} />
      </div>
    {/if}
    {#if showKey}
      <div class="field">
        <label for="cfKey">{$t('modal.connection.keyPath')}</label>
        <input id="cfKey" placeholder="~/.ssh/id_rsa" bind:value={keyPath} />
      </div>
    {/if}
    <div class="field">
      <label for="cfServer">{$t('modal.connection.server')}</label>
      <select id="cfServer" bind:value={serverId}>
        <option value="">{$t('modal.connection.noServer')}</option>
        {#each $servers as s (s.id)}
          <option value={s.id}>{s.name} ({s.hostname})</option>
        {/each}
      </select>
    </div>
    <div class="field full">
      <label for="cfTags">{$t('modal.connection.tagsComma')}</label>
      <input id="cfTags" placeholder="prod, web, linux" bind:value={tagsInput} />
    </div>
    <div class="field full">
      <label for="cfNotes">{$t('modal.connection.notes')}</label>
      <textarea
        id="cfNotes"
        placeholder={$t('modal.connection.notesPlaceholder')}
        bind:value={notes}
      ></textarea>
    </div>
  </form>
  {#snippet footer()}
    <Button variant="ghost" onclick={onClose}>{$t('action.cancel')}</Button>
    <Button
      variant="primary"
      type="submit"
      disabled={submitting}
      onclick={() => (document.getElementById('conn-form') as HTMLFormElement)?.requestSubmit()}
    >
      {$t('action.save')}
    </Button>
  {/snippet}
</Modal>
