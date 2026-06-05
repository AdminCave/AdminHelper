<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import { onMount } from 'svelte';
  import { t, language } from '$lib/i18n';
  import { hooks } from '$lib/stores/hooks';
  import { showToast } from '$lib/stores/notifications';
  import { HOOK_TYPE_LABEL } from '$lib/utils/hooks';
  import * as hookApi from '$lib/api/hooks';
  import Button from '$lib/components/ui/Button.svelte';
  import EmptyState from '$lib/components/ui/EmptyState.svelte';
  import { confirmDialog } from '$lib/components/ui/ConfirmDialog.svelte';
  import HookModal from '$modals/HookModal.svelte';
  import WebhookTokenModal from '$modals/WebhookTokenModal.svelte';
  import HookRunResultModal from '$modals/HookRunResultModal.svelte';
  import type { Hook, HookDetail, HookRunResult } from '$lib/api/types';

  let modalOpen = $state(false);
  let editing = $state<HookDetail | null>(null);
  let tokenOpen = $state(false);
  let tokenValue = $state('');
  let tokenTitle = $state<string | undefined>(undefined);
  let runOpen = $state(false);
  let runResult = $state<HookRunResult | null>(null);
  let runName = $state('');

  onMount(() => {
    load();
  });

  async function load() {
    try {
      await hooks.refresh();
    } catch (err) {
      showToast(err instanceof Error ? err.message : 'Fehler', 'error');
    }
  }

  function formatDateTime(iso: string | null | undefined): string {
    if (!iso) return '–';
    const loc = $language === 'de' ? 'de-DE' : 'en-GB';
    try {
      return new Date(iso).toLocaleString(loc);
    } catch {
      return '–';
    }
  }

  function openCreate() {
    editing = null;
    modalOpen = true;
  }

  async function openEdit(h: Hook) {
    try {
      const full = await hookApi.get(h.id);
      editing = full;
      modalOpen = true;
    } catch (err) {
      showToast(err instanceof Error ? err.message : 'Fehler', 'error');
    }
  }

  async function handleModalClose(created?: { token?: string | null }) {
    modalOpen = false;
    editing = null;
    if (created?.token) {
      tokenValue = created.token;
      tokenTitle = $t('toast.hook.created');
      tokenOpen = true;
    }
    await load();
  }

  async function removeHook(h: Hook) {
    if (!(await confirmDialog($t('confirm.hook.delete'), { confirmLabel: $t('action.delete') })))
      return;
    try {
      await hooks.remove(h.id);
      showToast($t('toast.hook.deleted'));
    } catch (err) {
      showToast(err instanceof Error ? err.message : 'Fehler', 'error');
    }
  }

  async function runHook(h: Hook) {
    showToast($t('toast.hook.running'));
    try {
      const result = await hookApi.run(h.id);
      runResult = result;
      runName = h.name;
      runOpen = true;
    } catch (err) {
      showToast(err instanceof Error ? err.message : 'Fehler', 'error');
    }
  }

  async function rotateToken(h: Hook) {
    const msg = $t('confirm.hook.rotateToken', { name: h.name });
    if (!(await confirmDialog(msg))) return;
    try {
      const result = await hookApi.rotate(h.id);
      tokenValue = result.token;
      tokenTitle = $t('toast.hook.tokenGenerated');
      tokenOpen = true;
    } catch (err) {
      showToast(err instanceof Error ? err.message : 'Fehler', 'error');
    }
  }

  async function toggleEnabled(h: Hook) {
    try {
      await hooks.toggle(h.id);
    } catch (err) {
      showToast(err instanceof Error ? err.message : 'Fehler', 'error');
    }
  }
</script>

<div class="page active">
  <div class="page-header">
    <div>
      <div class="page-title">{$t('page.hooks.title')}</div>
      <div class="page-subtitle">{$t('page.hooks.subtitle')}</div>
    </div>
    <Button variant="primary" onclick={openCreate}>{$t('page.hooks.add')}</Button>
  </div>

  <div class="panel">
    {#if $hooks.length === 0}
      <EmptyState message={$t('page.hooks.empty')} />
    {:else}
      <table class="data-table">
        <thead>
          <tr>
            <th>{$t('label.name')}</th>
            <th>{$t('table.type')}</th>
            <th></th>
            <th></th>
            <th>{$t('page.hooks.lastRun')}</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {#each $hooks as h (h.id)}
            <tr>
              <td>
                <strong>{h.name}</strong>
                {#if h.description}
                  <br />
                  <span style="font-size:11px;color:var(--text-muted)">{h.description}</span>
                {/if}
              </td>
              <td>
                <span class="badge badge-{h.hook_type}">{HOOK_TYPE_LABEL[h.hook_type]}</span>
              </td>
              <td>
                {#if h.hook_type === 'webhook'}
                  <code style="font-size:11px;color:var(--accent)">/api/hooks/trigger/…</code>
                {:else if h.hook_type === 'event'}
                  <div style="display:flex;gap:4px;flex-wrap:wrap">
                    {#each h.event_triggers ?? [] as evt (evt)}
                      <span class="tag">{evt}</span>
                    {/each}
                  </div>
                {:else if h.hook_type === 'schedule'}
                  <strong>{h.schedule_interval ?? '–'}</strong>
                  {#if h.next_run}
                    <br />
                    <span style="font-size:11px;color:var(--text-muted)">
                      {$t('page.hooks.next', { time: formatDateTime(h.next_run) })}
                    </span>
                  {/if}
                {/if}
              </td>
              <td>
                <span class="badge badge-{h.enabled ? 'active' : 'inactive'}">
                  {h.enabled ? $t('page.hooks.active') : $t('page.hooks.inactive')}
                </span>
              </td>
              <td style="font-size:12px;color:var(--text-muted)">
                {formatDateTime(h.last_run)}
              </td>
              <td>
                <div style="display:flex;gap:6px;flex-wrap:wrap">
                  <button class="btn small" onclick={() => openEdit(h)}>
                    {$t('action.edit')}
                  </button>
                  <button class="btn small ghost" onclick={() => runHook(h)}>
                    {$t('action.run')}
                  </button>
                  {#if h.hook_type === 'webhook'}
                    <button class="btn small ghost" onclick={() => rotateToken(h)}>
                      {$t('page.hooks.rotateToken')}
                    </button>
                  {/if}
                  <button class="btn small ghost" onclick={() => toggleEnabled(h)}>
                    {h.enabled ? $t('action.disable') : $t('action.enable')}
                  </button>
                  <button class="btn small ghost" onclick={() => removeHook(h)}>
                    {$t('action.delete')}
                  </button>
                </div>
              </td>
            </tr>
          {/each}
        </tbody>
      </table>
    {/if}
  </div>
</div>

<HookModal open={modalOpen} {editing} onClose={handleModalClose} />
<WebhookTokenModal
  open={tokenOpen}
  title={tokenTitle}
  token={tokenValue}
  onClose={() => {
    tokenOpen = false;
    tokenValue = '';
    tokenTitle = undefined;
  }}
/>
<HookRunResultModal
  open={runOpen}
  hookName={runName}
  result={runResult}
  onClose={() => {
    runOpen = false;
    runResult = null;
  }}
/>
