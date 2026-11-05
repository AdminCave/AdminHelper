<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import { onMount } from 'svelte';
  import { t } from '$lib/i18n';
  import { formatDate } from '$lib/utils/datetime';
  import { users } from '$lib/stores/users';
  import { currentUser } from '$lib/stores/auth';
  import { showToast, showError } from '$lib/stores/notifications';
  import Trash2 from '@lucide/svelte/icons/trash-2';
  import Button from '$lib/components/ui/Button.svelte';
  import EmptyState from '$lib/components/ui/EmptyState.svelte';
  import IconButton from '$lib/components/ui/IconButton.svelte';
  import Panel from '$lib/components/ui/Panel.svelte';
  import Pill from '$lib/components/ui/Pill.svelte';
  import { confirmDialog } from '$lib/components/ui/ConfirmDialog.svelte';
  import UserModal from '$modals/UserModal.svelte';
  import EnrollTokenModal from '$modals/EnrollTokenModal.svelte';
  import type { User } from '$lib/api/types';

  let modalOpen = $state(false);
  let editing = $state<User | null>(null);
  let enrollFor = $state<User | null>(null);

  onMount(() => {
    load();
  });

  async function load() {
    try {
      await users.refresh();
    } catch (err) {
      showError(err);
    }
  }

  function openCreate() {
    editing = null;
    modalOpen = true;
  }

  function openEdit(u: User) {
    editing = u;
    modalOpen = true;
  }

  function handleClose() {
    modalOpen = false;
    // No refetch: UserModal writes through the users store, so the list is current.
  }

  async function removeUser(u: User) {
    if (!(await confirmDialog($t('confirm.user.delete'), { confirmLabel: $t('action.delete') })))
      return;
    try {
      await users.remove(u.id);
      showToast($t('toast.user.deleted'));
    } catch (err) {
      showError(err);
    }
  }
</script>

<div class="page active">
  <div class="page-header">
    <div>
      <div class="page-title">{$t('page.users.title')}</div>
      <div class="page-subtitle">{$t('page.users.subtitle')}</div>
    </div>
    <Button variant="primary" onclick={openCreate}>{$t('page.users.add')}</Button>
  </div>

  <Panel pad={0}>
    {#if $users.length === 0}
      <EmptyState framed={false} message={$t('page.users.empty')} />
    {:else}
      <table class="data-table">
        <thead>
          <tr>
            <th>{$t('page.users.username')}</th>
            <th>{$t('page.users.role')}</th>
            <th>{$t('label.created')}</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {#each $users as u (u.id)}
            {@const isMe = u.id === $currentUser?.id}
            <tr>
              <td>
                <strong>{u.username}</strong>
                {#if isMe}<span class="me">{$t('page.users.me')}</span>{/if}
              </td>
              <td>
                <Pill tone={u.is_admin ? 'warn' : 'accent'}>
                  {u.is_admin ? $t('role.admin') : $t('role.user')}
                </Pill>
              </td>
              <td>{formatDate(u.created_at)}</td>
              <td>
                <div class="actions">
                  <Button variant="secondary" size="sm" onclick={() => openEdit(u)}>
                    {$t('action.edit')}
                  </Button>
                  <Button variant="secondary" size="sm" onclick={() => (enrollFor = u)}>
                    {$t('page.users.enrollToken')}
                  </Button>
                  {#if !isMe}
                    <IconButton
                      icon={Trash2}
                      size="sm"
                      label={$t('action.delete')}
                      onclick={() => removeUser(u)}
                    />
                  {/if}
                </div>
              </td>
            </tr>
          {/each}
        </tbody>
      </table>
    {/if}
  </Panel>
</div>

<UserModal open={modalOpen} {editing} onClose={handleClose} />
<EnrollTokenModal
  open={enrollFor !== null}
  username={enrollFor?.username ?? ''}
  onClose={() => (enrollFor = null)}
/>

<style>
  .me {
    margin-left: var(--space-2);
    color: var(--text-muted);
    font-size: var(--text-xs);
  }
  .actions {
    display: flex;
    align-items: center;
    justify-content: flex-end;
    gap: var(--space-2);
  }
</style>
