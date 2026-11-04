<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import Modal from '$lib/components/ui/Modal.svelte';
  import Button from '$lib/components/ui/Button.svelte';
  import Checkbox from '$lib/components/ui/Checkbox.svelte';
  import FormField from '$lib/components/ui/FormField.svelte';
  import Input from '$lib/components/ui/Input.svelte';
  import { t } from '$lib/i18n';
  import { users } from '$lib/stores/users';
  import { auth, currentUser } from '$lib/stores/auth';
  import * as serversApi from '$lib/api/servers';
  import { showToast, showError } from '$lib/stores/notifications';
  import type { ServerSummary, User } from '$lib/api/types';
  import {
    endsOwnSession,
    userCreatePayload,
    userUpdatePayload,
    validateUserForm,
    type UserForm,
  } from '$lib/utils/userForm';

  interface Props {
    open: boolean;
    editing: User | null;
    onClose: () => void;
  }

  let { open, editing, onClose }: Props = $props();

  let username = $state('');
  let password = $state('');
  let isAdmin = $state(false);
  let serverList = $state<ServerSummary[]>([]);
  let serverLoadFailed = $state(false);
  let selectedServerIds = $state<Set<string>>(new Set());
  let submitting = $state(false);

  $effect(() => {
    if (open) {
      username = editing?.username ?? '';
      password = '';
      isAdmin = editing?.is_admin ?? false;
      selectedServerIds = new Set(editing?.server_ids ?? []);
      void loadServers();
    }
  });

  // Read-only fetch of the server inventory (managed in the desktop) so an admin
  // can still assign servers to a user here in the web.
  async function loadServers() {
    serverLoadFailed = false;
    try {
      serverList = await serversApi.listSummaries();
    } catch (err) {
      // Surface the failure instead of showing the empty "no servers" state — otherwise an admin
      // thinks there are no servers, saves the user with no assignments, and (when editing) can't
      // see the existing ones. Distinguish load-failed from genuinely-empty (4.78).
      serverList = [];
      serverLoadFailed = true;
      showError(err);
    }
  }

  function toggleServer(id: string) {
    // eslint-disable-next-line svelte/prefer-svelte-reactivity -- transient copy; reactivity comes from the reassignment to $state below
    const next = new Set(selectedServerIds);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    selectedServerIds = next;
  }

  async function onSubmit(e: SubmitEvent) {
    e.preventDefault();
    const form: UserForm = { username, password, isAdmin, serverIds: [...selectedServerIds] };
    const missing = validateUserForm(form, editing);
    if (missing) {
      showToast($t(missing), 'error');
      return;
    }
    submitting = true;
    try {
      if (editing) {
        const ownPassword = endsOwnSession(form, editing, $currentUser?.id);
        const updated = await users.update(editing.id, userUpdatePayload(form));
        if (ownPassword) {
          // A new password ends every session of the account on the server (tokens_valid_after);
          // logging out now says so, instead of a "Session expired" at the next click.
          onClose();
          await auth.logout();
          showToast($t('toast.user.ownPasswordChanged'), 'info', 8000);
          return;
        }
        auth.applySelfUpdate(updated);
        showToast($t('toast.user.saved'));
      } else {
        await users.create(userCreatePayload(form));
        showToast($t('toast.user.created'));
      }
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
  title={editing ? $t('modal.user.title') : $t('modal.user.titleNew')}
  width="520px"
  {onClose}
>
  <form class="form" onsubmit={onSubmit} id="user-form">
    <FormField label={$t('modal.user.username')} id="ufUsername">
      <Input required disabled={!!editing} bind:value={username} />
    </FormField>
    <FormField
      label={editing ? $t('modal.user.passwordEdit') : $t('modal.user.password')}
      id="ufPassword"
    >
      <Input
        type="password"
        required={!editing}
        bind:value={password}
        autocomplete="new-password"
      />
    </FormField>
    <Checkbox bind:checked={isAdmin} label={$t('modal.user.adminRights')} />
    <div class="servers">
      <span class="servers-label">{$t('modal.user.assignServers')}</span>
      <div class="server-list">
        {#if serverLoadFailed}
          <span class="note failed">{$t('page.users.serverLoadFailed')}</span>
        {:else if serverList.length === 0}
          <span class="note">{$t('page.users.noServers')}</span>
        {:else}
          {#each serverList as s (s.id)}
            <Checkbox
              checked={selectedServerIds.has(s.id)}
              label={s.name}
              description={s.hostname}
              onChange={() => toggleServer(s.id)}
            />
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
      loading={submitting}
      disabled={submitting}
      form="user-form"
    >
      {$t('action.save')}
    </Button>
  {/snippet}
</Modal>

<style>
  .form {
    display: flex;
    flex-direction: column;
    gap: var(--space-4);
  }
  .servers {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
  }
  .servers-label {
    color: var(--text-muted);
    font-size: var(--text-sm);
  }
  .server-list {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    max-height: 180px;
    overflow-y: auto;
    padding: var(--space-3);
    border: 1px solid var(--border);
    border-radius: var(--radius-md);
  }
  .note {
    color: var(--text-muted);
    font-size: var(--text-sm);
  }
  .failed {
    color: var(--danger);
  }
</style>
