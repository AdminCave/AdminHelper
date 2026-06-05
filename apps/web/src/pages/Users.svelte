<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import { onMount } from 'svelte';
  import { t, language } from '$lib/i18n';
  import { users } from '$lib/stores/users';
  import { servers } from '$lib/stores/servers';
  import { currentUser } from '$lib/stores/auth';
  import { showToast } from '$lib/stores/notifications';
  import Button from '$lib/components/ui/Button.svelte';
  import EmptyState from '$lib/components/ui/EmptyState.svelte';
  import { confirmDialog } from '$lib/components/ui/ConfirmDialog.svelte';
  import UserModal from '$modals/UserModal.svelte';
  import type { User } from '$lib/api/types';

  let modalOpen = $state(false);
  let editing = $state<User | null>(null);

  onMount(() => {
    load();
  });

  async function load() {
    try {
      await Promise.all([users.refresh(), servers.refresh()]);
    } catch (err) {
      showToast(err instanceof Error ? err.message : 'Fehler', 'error');
    }
  }

  function formatDate(iso: string | undefined): string {
    if (!iso) return '–';
    const loc = $language === 'de' ? 'de-DE' : 'en-US';
    try {
      return new Date(iso).toLocaleDateString(loc);
    } catch {
      return '–';
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

  async function handleClose() {
    modalOpen = false;
    await load();
  }

  async function removeUser(u: User) {
    if (!(await confirmDialog($t('confirm.user.delete'), { confirmLabel: $t('action.delete') })))
      return;
    try {
      await users.remove(u.id);
      showToast($t('toast.user.deleted'));
    } catch (err) {
      showToast(err instanceof Error ? err.message : 'Fehler', 'error');
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

  <div class="panel">
    {#if $users.length === 0}
      <EmptyState message={$t('page.users.empty')} />
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
                {#if isMe}
                  <span style="color:var(--text-muted);font-size:12px;margin-left:6px">
                    {$t('page.users.me')}
                  </span>
                {/if}
              </td>
              <td>
                <span class="badge badge-{u.is_admin ? 'admin' : 'user'}">
                  {u.is_admin ? $t('role.admin') : $t('role.user')}
                </span>
              </td>
              <td>{formatDate(u.created_at)}</td>
              <td>
                <div style="display:flex;gap:6px">
                  <button class="btn small" onclick={() => openEdit(u)}>
                    {$t('action.edit')}
                  </button>
                  {#if !isMe}
                    <button class="btn small ghost" onclick={() => removeUser(u)}>
                      {$t('action.delete')}
                    </button>
                  {/if}
                </div>
              </td>
            </tr>
          {/each}
        </tbody>
      </table>
    {/if}
  </div>
</div>

<UserModal open={modalOpen} {editing} onClose={handleClose} />
