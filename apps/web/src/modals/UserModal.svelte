<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import Modal from '$lib/components/ui/Modal.svelte';
  import Button from '$lib/components/ui/Button.svelte';
  import { t } from '$lib/i18n';
  import { users } from '$lib/stores/users';
  import { servers } from '$lib/stores/servers';
  import { showToast } from '$lib/stores/notifications';
  import type { User } from '$lib/api/types';

  interface Props {
    open: boolean;
    editing: User | null;
    onClose: () => void;
  }

  let { open, editing, onClose }: Props = $props();

  let username = $state('');
  let password = $state('');
  let isAdmin = $state(false);
  let selectedServerIds = $state<Set<string>>(new Set());
  let submitting = $state(false);

  $effect(() => {
    if (open) {
      username = editing?.username ?? '';
      password = '';
      isAdmin = editing?.is_admin ?? false;
      selectedServerIds = new Set(editing?.server_ids ?? []);
    }
  });

  function toggleServer(id: string) {
    const next = new Set(selectedServerIds);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    selectedServerIds = next;
  }

  async function onSubmit(e: SubmitEvent) {
    e.preventDefault();
    submitting = true;
    try {
      const server_ids = [...selectedServerIds];
      if (editing) {
        const payload: { is_admin: boolean; server_ids: string[]; password?: string } = {
          is_admin: isAdmin,
          server_ids,
        };
        if (password) payload.password = password;
        await users.update(editing.id, payload);
        showToast($t('toast.user.saved'));
      } else {
        if (!password) {
          showToast($t('modal.user.passwordRequired'), 'error');
          submitting = false;
          return;
        }
        await users.create({
          username: username.trim(),
          password,
          is_admin: isAdmin,
          server_ids,
        });
        showToast($t('toast.user.created'));
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
  title={editing ? $t('modal.user.title') : $t('modal.user.titleNew')}
  width="520px"
  {onClose}
>
  <form class="modal-form" onsubmit={onSubmit} id="user-form">
    <div class="field">
      <label for="ufUsername">{$t('modal.user.username')}</label>
      <input id="ufUsername" required disabled={!!editing} bind:value={username} />
    </div>
    <div class="field">
      <label for="ufPassword">
        {editing ? $t('modal.user.passwordEdit') : $t('modal.user.password')}
      </label>
      <input
        id="ufPassword"
        type="password"
        required={!editing}
        bind:value={password}
        autocomplete="new-password"
      />
    </div>
    <div class="field">
      <label style="display:flex;align-items:center;gap:8px;cursor:pointer">
        <input type="checkbox" bind:checked={isAdmin} />
        <span>{$t('modal.user.adminRights')}</span>
      </label>
    </div>
    <div class="field full">
      <span
        class="label-like"
        style="display:block;font-size:13px;color:var(--text-muted);margin-bottom:6px"
      >
        {$t('modal.user.assignServers')}
      </span>
      <div
        style="display:flex;flex-direction:column;gap:6px;max-height:180px;overflow-y:auto;padding:8px;border:1px solid var(--border);border-radius:6px"
      >
        {#if $servers.length === 0}
          <span style="color:var(--text-muted);font-size:12px">
            {$t('page.users.noServers')}
          </span>
        {:else}
          {#each $servers as s (s.id)}
            <label style="display:flex;align-items:center;gap:8px;cursor:pointer">
              <input
                type="checkbox"
                checked={selectedServerIds.has(s.id)}
                onchange={() => toggleServer(s.id)}
              />
              <span>{s.name}</span>
              <span style="color:var(--text-muted);font-size:11px">{s.hostname}</span>
            </label>
          {/each}
        {/if}
      </div>
    </div>
  </form>
  {#snippet footer()}
    <Button variant="ghost" onclick={onClose}>{$t('action.cancel')}</Button>
    <Button
      variant="primary"
      type="submit"
      disabled={submitting}
      onclick={() => (document.getElementById('user-form') as HTMLFormElement)?.requestSubmit()}
    >
      {$t('action.save')}
    </Button>
  {/snippet}
</Modal>
