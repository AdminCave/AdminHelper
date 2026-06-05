<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import Modal from '$lib/components/ui/Modal.svelte';
  import Button from '$lib/components/ui/Button.svelte';
  import { t } from '$lib/i18n';
  import { showToast } from '$lib/stores/notifications';
  import { confirmDialog } from '$lib/components/ui/ConfirmDialog.svelte';
  import * as api from '$lib/api/connections';

  interface Props {
    open: boolean;
    onClose: () => void;
    onImported: () => void | Promise<void>;
  }

  let { open, onClose, onImported }: Props = $props();

  let fileInput = $state<HTMLInputElement | null>(null);
  let mode = $state<'merge' | 'replace'>('merge');
  let info = $state('');
  let busy = $state(false);

  $effect(() => {
    if (open) {
      mode = 'merge';
      info = '';
      if (fileInput) fileInput.value = '';
    }
  });

  async function readFile(file: File): Promise<unknown[] | null> {
    try {
      const text = await file.text();
      const data = JSON.parse(text);
      return Array.isArray(data) ? data : null;
    } catch {
      return null;
    }
  }

  async function onFileChange() {
    const f = fileInput?.files?.[0];
    if (!f) {
      info = '';
      return;
    }
    const parsed = await readFile(f);
    if (parsed === null) {
      info = $t('import.invalidJson');
      return;
    }
    info = $t(parsed.length !== 1 ? 'import.foundPlural' : 'import.found', {
      count: parsed.length,
    });
  }

  async function onSubmit() {
    const f = fileInput?.files?.[0];
    if (!f) {
      showToast($t('import.selectFile'), 'error');
      return;
    }
    const parsed = await readFile(f);
    if (parsed === null) {
      showToast($t('import.invalidJsonShort'), 'error');
      return;
    }
    const msg =
      mode === 'replace'
        ? $t('import.confirmReplace', { count: parsed.length })
        : $t(parsed.length !== 1 ? 'import.confirmMergePlural' : 'import.confirmMerge', {
            count: parsed.length,
          });
    if (!(await confirmDialog(msg))) return;
    busy = true;
    try {
      const result = await api.importConnections(parsed, mode);
      showToast(
        $t(result.imported !== 1 ? 'import.resultPlural' : 'import.result', {
          count: result.imported,
        }),
      );
      await onImported();
      onClose();
    } catch (err) {
      showToast(err instanceof Error ? err.message : 'Fehler', 'error');
    } finally {
      busy = false;
    }
  }
</script>

<Modal {open} title={$t('import.title')} width="480px" {onClose}>
  <div class="modal-form">
    <div class="field">
      <label for="importFile">{$t('import.file')}</label>
      <input
        id="importFile"
        bind:this={fileInput}
        type="file"
        accept=".json,application/json"
        style="padding:6px 0;color:var(--text)"
        onchange={onFileChange}
      />
    </div>
    <div class="field">
      <label for="importMode">{$t('import.mode')}</label>
      <select id="importMode" bind:value={mode}>
        <option value="merge">{$t('import.modeMerge')}</option>
        <option value="replace">{$t('import.modeReplace')}</option>
      </select>
    </div>
    {#if info}
      <p style="font-size:13px;color:var(--text-muted);margin:0">{info}</p>
    {/if}
  </div>
  {#snippet footer()}
    <Button variant="ghost" onclick={onClose}>{$t('action.cancel')}</Button>
    <Button variant="primary" disabled={busy} onclick={onSubmit}>{$t('import.submit')}</Button>
  {/snippet}
</Modal>
