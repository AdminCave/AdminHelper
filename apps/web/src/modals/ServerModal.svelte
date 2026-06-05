<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import Modal from '$lib/components/ui/Modal.svelte';
  import Button from '$lib/components/ui/Button.svelte';
  import { t } from '$lib/i18n';
  import { servers } from '$lib/stores/servers';
  import { showToast } from '$lib/stores/notifications';
  import { parseTags } from '$lib/utils/tags';
  import * as monApi from '$lib/api/monitoring';
  import type { Server, MonitoringTemplate } from '$lib/api/types';

  interface Props {
    open: boolean;
    editing: Server | null;
    onClose: () => void;
  }

  let { open, editing, onClose }: Props = $props();

  let name = $state('');
  let hostname = $state('');
  let osType = $state('');
  let tagsInput = $state('');
  let notes = $state('');
  let templates = $state<MonitoringTemplate[]>([]);
  let selectedTemplateIds = $state<string[]>([]);
  let originalAssignedIds = $state<string[]>([]);
  let submitting = $state(false);

  $effect(() => {
    if (open) {
      name = editing?.name ?? '';
      hostname = editing?.hostname ?? '';
      osType = editing?.osType ?? '';
      tagsInput = (editing?.tags ?? []).join(', ');
      notes = editing?.notes ?? '';
      selectedTemplateIds = [];
      originalAssignedIds = [];
      loadTemplates();
    }
  });

  async function loadTemplates() {
    try {
      templates = await monApi.listTemplates();
      if (editing) {
        const assignments = await monApi.listAssignmentsForServer(editing.id);
        originalAssignedIds = assignments.map((a) => a.templateId);
        selectedTemplateIds = [...originalAssignedIds];
      }
    } catch {
      templates = [];
    }
  }

  async function syncTemplates(serverId: string, serverHostname: string, serverName: string) {
    const oldIds = new Set(originalAssignedIds);
    const newIds = new Set(selectedTemplateIds);
    const toAdd = [...newIds].filter((id) => !oldIds.has(id));
    const toRemove = [...oldIds].filter((id) => !newIds.has(id));
    const calls = [
      ...toAdd.map((id) =>
        monApi.assignTemplate(id, serverId, serverHostname, serverName).catch(() => null),
      ),
      ...toRemove.map((id) => monApi.unassignTemplate(id, serverId).catch(() => null)),
    ];
    if (calls.length) await Promise.all(calls);
  }

  async function onSubmit(e: SubmitEvent) {
    e.preventDefault();
    submitting = true;
    try {
      const data = {
        name: name.trim(),
        hostname: hostname.trim(),
        os_type: osType || null,
        tags: parseTags(tagsInput),
        notes: notes.trim(),
      };
      let serverId: string;
      if (editing) {
        const upd = await servers.update(editing.id, data);
        serverId = upd.id;
        showToast($t('toast.server.saved'));
      } else {
        const created = await servers.create(data);
        serverId = created.id;
        showToast($t('toast.server.created'));
      }
      await syncTemplates(serverId, data.hostname, data.name);
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
  title={editing ? $t('modal.server.title') : $t('modal.server.titleNew')}
  width="620px"
  {onClose}
>
  <form class="modal-form" onsubmit={onSubmit} id="srv-form">
    <div class="field">
      <label for="sfName">{$t('label.name')} *</label>
      <input id="sfName" required placeholder="prod-web-01" bind:value={name} />
    </div>
    <div class="field">
      <label for="sfHostname">{$t('modal.server.hostname')}</label>
      <input id="sfHostname" required placeholder="192.168.1.10" bind:value={hostname} />
    </div>
    <div class="field">
      <label for="sfOsType">{$t('modal.server.os')}</label>
      <select id="sfOsType" bind:value={osType}>
        <option value="">{$t('modal.server.osNone')}</option>
        <option value="linux">Linux</option>
        <option value="windows">Windows</option>
        <option value="macos">macOS</option>
        <option value="freebsd">FreeBSD</option>
      </select>
    </div>
    <div class="field">
      <label for="sfTags">{$t('modal.server.tagsComma')}</label>
      <input id="sfTags" placeholder="prod, web, rack-a" bind:value={tagsInput} />
    </div>
    <div class="field">
      <label for="sfNotes">{$t('modal.server.notes')}</label>
      <textarea id="sfNotes" placeholder={$t('modal.server.notesPlaceholder')} bind:value={notes}
      ></textarea>
    </div>
    <div class="field full">
      <label for="sfTemplates">{$t('modal.server.monitorTemplates')}</label>
      <select
        id="sfTemplates"
        multiple
        size="3"
        style="min-height:60px"
        bind:value={selectedTemplateIds}
      >
        {#each templates as tpl (tpl.id)}
          <option value={tpl.id}>{tpl.name}</option>
        {/each}
      </select>
      <small style="color:var(--text-muted)">{$t('modal.server.multiSelect')}</small>
    </div>
  </form>
  {#snippet footer()}
    <Button variant="ghost" onclick={onClose}>{$t('action.cancel')}</Button>
    <Button
      variant="primary"
      type="submit"
      disabled={submitting}
      onclick={() => (document.getElementById('srv-form') as HTMLFormElement)?.requestSubmit()}
    >
      {$t('action.save')}
    </Button>
  {/snippet}
</Modal>
