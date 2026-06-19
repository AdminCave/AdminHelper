<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import type { FrpConfig, FrpProtocol, FrpTunnel, FrpTunnelType } from '$lib/api/types';
  import {
    TUNNEL_TYPES,
    TUNNEL_PROTOCOLS,
    PROTOCOL_DEFAULT_PORT,
    emptyTunnelForm,
    tunnelToForm,
    parseTags,
    formToInput,
    validateTunnelForm,
    type TunnelForm,
  } from '$lib/models/frpTunnel';
  import { frpApi } from '$lib/api/frp';
  import { session } from '$lib/stores/session';
  import { reportError, showStatus } from '$lib/stores/statusBar';
  import { t } from '$lib/i18n';

  interface Props {
    open: boolean;
    editing: FrpTunnel | null;
    serverId: string;
    configs: FrpConfig[];
    onClose: () => void;
    onSaved: () => void;
  }
  let { open, editing, serverId, configs, onClose, onSaved }: Props = $props();

  let form = $state<TunnelForm>(emptyTunnelForm(''));
  let tagsInput = $state('');
  let saving = $state(false);
  let confirmDelete = $state(false);

  let isNew = $derived(editing === null);
  let isStcp = $derived(form.tunnelType === 'stcp');

  $effect(() => {
    if (!open) return;
    // Derive tagsInput from the local `next`, not from `form`: reading `form`
    // after assigning it would make this effect depend on the state it writes,
    // which self-triggers an infinite loop (effect_update_depth_exceeded) that
    // breaks the modal's reactivity (dead inputs and buttons).
    const next = editing
      ? tunnelToForm(editing)
      : // Preselect the only config so the common single-config setup is one click.
        emptyTunnelForm(serverId, configs.length === 1 ? configs[0].id : '');
    form = next;
    tagsInput = (next.tags ?? []).join(', ');
    confirmDelete = false;
  });

  function onProtocolChange(): void {
    if (form.localPort === null) {
      form = { ...form, localPort: PROTOCOL_DEFAULT_PORT[form.protocol] };
    }
  }

  function errMsg(err: unknown): string {
    return err instanceof Error ? err.message : String(err);
  }

  async function onDelete(): Promise<void> {
    const s = $session;
    if (!s || !form.id) return;
    if (!confirmDelete) {
      confirmDelete = true;
      return;
    }
    saving = true;
    try {
      await frpApi.removeTunnel(s, form.id);
      showStatus($t('infra.tun.deleted'));
      onSaved();
      onClose();
    } catch (err) {
      reportError(errMsg(err));
    } finally {
      saving = false;
    }
  }

  async function onSave(): Promise<void> {
    const s = $session;
    if (!s) return;
    const next: TunnelForm = { ...form, tags: parseTags(tagsInput) };
    const result = validateTunnelForm(next);
    if (!result.ok) {
      reportError(result.message ?? $t('infra.validation.failed'));
      return;
    }
    saving = true;
    try {
      const input = formToInput(next);
      if (next.id) {
        await frpApi.updateTunnel(s, next.id, input);
        showStatus($t('infra.tun.updated'));
      } else {
        await frpApi.createTunnel(s, input);
        showStatus($t('infra.tun.created'));
      }
      onSaved();
      onClose();
    } catch (err) {
      reportError(errMsg(err));
    } finally {
      saving = false;
    }
  }
</script>

{#if open}
  <div
    class="editor-overlay"
    role="dialog"
    aria-modal="true"
    onclick={(e) => {
      if (e.target === e.currentTarget) onClose();
    }}
    onkeydown={(e) => e.key === 'Escape' && onClose()}
    tabindex="-1"
  >
    <div class="editor-panel">
      <div class="panel-header">
        <h2 class="panel-title">
          {isNew ? $t('infra.tun.new') : form.name || $t('infra.tun.edit')}
        </h2>
        <button class="btn ghost small" onclick={onClose} aria-label={$t('editor.close')}>×</button>
      </div>

      <div class="form-grid">
        <label class="field span2">
          <span class="field-label">{$t('infra.tun.config')}</span>
          <select
            value={form.frpConfigId}
            onchange={(e) =>
              (form = { ...form, frpConfigId: (e.currentTarget as HTMLSelectElement).value })}
          >
            <option value="">{$t('infra.tun.selectConfig')}</option>
            {#each configs as cfg (cfg.id)}
              <option value={cfg.id}>{cfg.name}</option>
            {/each}
          </select>
        </label>

        <label class="field">
          <span class="field-label">{$t('infra.field.name')}</span>
          <input type="text" bind:value={form.name} placeholder="k01-lnx1-ssh" required />
        </label>

        <label class="field">
          <span class="field-label">{$t('infra.tun.type')}</span>
          <select
            value={form.tunnelType}
            onchange={(e) =>
              (form = {
                ...form,
                tunnelType: (e.currentTarget as HTMLSelectElement).value as FrpTunnelType,
              })}
          >
            {#each TUNNEL_TYPES as type (type)}
              <option value={type}>{type.toUpperCase()}</option>
            {/each}
          </select>
        </label>

        <label class="field">
          <span class="field-label">{$t('infra.tun.protocol')}</span>
          <select
            value={form.protocol}
            onchange={(e) => {
              form = {
                ...form,
                protocol: (e.currentTarget as HTMLSelectElement).value as FrpProtocol,
              };
              onProtocolChange();
            }}
          >
            {#each TUNNEL_PROTOCOLS as proto (proto)}
              <option value={proto}>{proto.toUpperCase()}</option>
            {/each}
          </select>
        </label>

        <label class="field">
          <span class="field-label">{$t('infra.tun.localIp')}</span>
          <input type="text" bind:value={form.localIp} />
        </label>

        <label class="field">
          <span class="field-label">{$t('infra.tun.localPort')}</span>
          <input
            type="number"
            value={form.localPort ?? ''}
            oninput={(e) => {
              const v = (e.currentTarget as HTMLInputElement).value;
              form = { ...form, localPort: v === '' ? null : Number(v) };
            }}
            required
          />
        </label>

        {#if isStcp}
          <label class="field span2">
            <span class="field-label">{$t('infra.tun.secretKey')}</span>
            <input
              type="text"
              bind:value={form.secretKey}
              placeholder={$t('infra.tun.secretHint')}
            />
          </label>
          <label class="field">
            <span class="field-label">{$t('infra.tun.visitorPort')}</span>
            <input
              type="number"
              value={form.visitorPort ?? ''}
              oninput={(e) => {
                const v = (e.currentTarget as HTMLInputElement).value;
                form = { ...form, visitorPort: v === '' ? null : Number(v) };
              }}
            />
          </label>
        {:else}
          <label class="field span2">
            <span class="field-label">{$t('infra.tun.customDomains')}</span>
            <input type="text" bind:value={form.customDomains} placeholder="tunnel.example.net" />
          </label>
        {/if}

        <label class="field span2">
          <span class="field-label">{$t('infra.field.tags')}</span>
          <input
            type="text"
            bind:value={tagsInput}
            placeholder={$t('infra.field.tags.placeholder')}
          />
        </label>

        <label class="field checkbox span2">
          <input type="checkbox" bind:checked={form.autoCreateConnection} />
          <span>{$t('infra.tun.autoConnection')}</span>
        </label>

        {#if form.autoCreateConnection}
          <label class="field span2">
            <span class="field-label">{$t('infra.tun.autoConnUser')}</span>
            <input type="text" bind:value={form.autoConnectionUsername} />
          </label>
        {/if}
      </div>

      <div class="panel-actions">
        {#if !isNew}
          <button class="btn danger" onclick={onDelete} disabled={saving}>
            {confirmDelete ? $t('infra.server.confirmDelete') : $t('action.delete')}
          </button>
        {/if}
        <div style="flex: 1;"></div>
        <button class="btn" onclick={onClose} disabled={saving}>{$t('action.cancel')}</button>
        <button class="btn primary" onclick={onSave} disabled={saving}>{$t('action.save')}</button>
      </div>
    </div>
  </div>
{/if}

<style>
  .editor-overlay {
    position: fixed;
    inset: 0;
    background: rgba(0, 0, 0, 0.55);
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 50;
    padding: var(--sp-4);
  }
  .editor-panel {
    background: var(--bg-panel);
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    width: 100%;
    max-width: 640px;
    max-height: 90vh;
    overflow-y: auto;
    display: flex;
    flex-direction: column;
  }
  .panel-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: var(--sp-4) var(--sp-5);
    border-bottom: 1px solid var(--border);
  }
  .panel-title {
    margin: 0;
    font-size: 16px;
    font-weight: 600;
  }
  .form-grid {
    padding: var(--sp-5);
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: var(--sp-4);
  }
  .field {
    display: flex;
    flex-direction: column;
    gap: var(--sp-2);
  }
  .field.span2 {
    grid-column: span 2;
  }
  .field.checkbox {
    flex-direction: row;
    align-items: center;
    gap: var(--sp-2);
  }
  .field-label {
    font-size: 12px;
    color: var(--text-muted);
  }
  .field input,
  .field select {
    background: var(--bg-input, var(--bg-panel));
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    color: var(--text);
    padding: var(--sp-2) var(--sp-3);
    font-size: 13px;
    font-family: inherit;
  }
  .field input:focus,
  .field select:focus {
    outline: 1px solid var(--accent);
  }
  .panel-actions {
    display: flex;
    gap: var(--sp-2);
    padding: var(--sp-4) var(--sp-5);
    border-top: 1px solid var(--border);
    align-items: center;
  }
</style>
