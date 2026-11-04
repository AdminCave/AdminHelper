<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import { onMount } from 'svelte';
  import { SvelteSet } from 'svelte/reactivity';
  import { t } from '$lib/i18n';
  import { formatDateTime } from '$lib/utils/datetime';
  import { hooks } from '$lib/stores/hooks';
  import { showToast, showError } from '$lib/stores/notifications';
  import { HOOK_TYPE_LABEL } from '$lib/utils/hooks';
  import * as hookApi from '$lib/api/hooks';
  import Trash2 from '@lucide/svelte/icons/trash-2';
  import Button from '$lib/components/ui/Button.svelte';
  import EmptyState from '$lib/components/ui/EmptyState.svelte';
  import IconButton from '$lib/components/ui/IconButton.svelte';
  import Panel from '$lib/components/ui/Panel.svelte';
  import Pill from '$lib/components/ui/Pill.svelte';
  import Switch from '$lib/components/ui/Switch.svelte';
  import Tag from '$lib/components/ui/Tag.svelte';
  import { confirmDialog } from '$lib/components/ui/ConfirmDialog.svelte';
  import HookModal from '$modals/HookModal.svelte';
  import WebhookTokenModal from '$modals/WebhookTokenModal.svelte';
  import HookRunResultModal from '$modals/HookRunResultModal.svelte';
  import type { Hook, HookDetail, HookRunResult, HookType } from '$lib/api/types';

  const TYPE_TONE: Record<HookType, 'accent' | 'warn' | 'muted'> = {
    webhook: 'accent',
    event: 'warn',
    schedule: 'muted',
  };

  let modalOpen = $state(false);
  let editing = $state<HookDetail | null>(null);
  let tokenOpen = $state(false);
  let tokenValue = $state('');
  let tokenTitle = $state<string | undefined>(undefined);
  let runOpen = $state(false);
  let runResult = $state<HookRunResult | null>(null);
  let runName = $state('');
  // Hook ids currently executing — guards runHook against a double-click / parallel run (4.147).
  const running = new SvelteSet<string>();

  onMount(() => {
    load();
  });

  async function load() {
    try {
      await hooks.refresh();
    } catch (err) {
      showError(err);
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
      showError(err);
    }
  }

  function handleModalClose(created?: { token?: string | null }) {
    modalOpen = false;
    editing = null;
    if (created?.token) {
      tokenValue = created.token;
      tokenTitle = $t('toast.hook.created');
      tokenOpen = true;
    }
    // No refetch: HookModal writes through the hooks store, so the list is current.
  }

  async function removeHook(h: Hook) {
    if (!(await confirmDialog($t('confirm.hook.delete'), { confirmLabel: $t('action.delete') })))
      return;
    try {
      await hooks.remove(h.id);
      showToast($t('toast.hook.deleted'));
    } catch (err) {
      showError(err);
    }
  }

  async function runHook(h: Hook) {
    if (running.has(h.id)) return;
    running.add(h.id);
    showToast($t('toast.hook.running'));
    try {
      const result = await hookApi.run(h.id);
      runResult = result;
      runName = h.name;
      runOpen = true;
    } catch (err) {
      showError(err);
    } finally {
      running.delete(h.id);
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
      showError(err);
    }
  }

  // The Switch flips itself on click; after a failed toggle the store keeps the old value and
  // the prop does not change, so the switch is rebuilt from it. Only then: a rebuild on success
  // would drop the keyboard focus.
  let toggleFailures = $state(0);

  async function toggleEnabled(h: Hook) {
    try {
      await hooks.toggle(h.id);
    } catch (err) {
      toggleFailures++;
      showError(err);
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

  <Panel pad={0}>
    {#if $hooks.length === 0}
      <EmptyState framed={false} message={$t('page.hooks.empty')} />
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
                  <div class="sub">{h.description}</div>
                {/if}
              </td>
              <td>
                <Pill tone={TYPE_TONE[h.hook_type]}>{HOOK_TYPE_LABEL[h.hook_type]}</Pill>
              </td>
              <td>
                {#if h.hook_type === 'webhook'}
                  <code class="trigger">/api/hooks/trigger/…</code>
                {:else if h.hook_type === 'event'}
                  <div class="tags">
                    {#each h.event_triggers ?? [] as evt (evt)}
                      <Tag tone="neutral" size="sm">{evt}</Tag>
                    {/each}
                  </div>
                {:else if h.hook_type === 'schedule'}
                  <strong>{h.schedule_interval ?? '–'}</strong>
                  {#if h.next_run}
                    <div class="sub">
                      {$t('page.hooks.next', { time: formatDateTime(h.next_run) })}
                    </div>
                  {/if}
                {/if}
              </td>
              <td>
                {#key toggleFailures}
                  <Switch
                    size="sm"
                    checked={h.enabled}
                    label={$t('page.hooks.active')}
                    onChange={() => toggleEnabled(h)}
                  />
                {/key}
              </td>
              <td class="sub">{formatDateTime(h.last_run)}</td>
              <td>
                <div class="actions">
                  <Button variant="secondary" size="sm" onclick={() => openEdit(h)}>
                    {$t('action.edit')}
                  </Button>
                  <Button
                    variant="secondary"
                    size="sm"
                    loading={running.has(h.id)}
                    onclick={() => runHook(h)}
                  >
                    {$t('action.run')}
                  </Button>
                  {#if h.hook_type === 'webhook'}
                    <Button variant="ghost" size="sm" onclick={() => rotateToken(h)}>
                      {$t('page.hooks.rotateToken')}
                    </Button>
                  {/if}
                  <IconButton
                    icon={Trash2}
                    size="sm"
                    label={$t('action.delete')}
                    onclick={() => removeHook(h)}
                  />
                </div>
              </td>
            </tr>
          {/each}
        </tbody>
      </table>
    {/if}
  </Panel>
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

<style>
  .sub {
    margin-top: 2px;
    color: var(--text-muted);
    font-size: var(--text-xs);
  }
  .trigger {
    color: var(--accent);
    font-size: var(--text-xs);
  }
  .tags {
    display: flex;
    flex-wrap: wrap;
    gap: 4px;
  }
  .actions {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: flex-end;
    gap: var(--space-2);
  }
</style>
