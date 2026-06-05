<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import Modal from '$lib/components/ui/Modal.svelte';
  import Button from '$lib/components/ui/Button.svelte';
  import { t } from '$lib/i18n';
  import { playbooks } from '$lib/stores/ansible';
  import * as api from '$lib/api/ansible';
  import { showToast } from '$lib/stores/notifications';
  import { parseTags } from '$lib/utils/tags';
  import type { Playbook } from '$lib/api/types';

  interface Props {
    open: boolean;
    editing: Playbook | null;
    onClose: () => void;
  }

  let { open, editing, onClose }: Props = $props();

  let name = $state('');
  let filename = $state('');
  let description = $state('');
  let tagsInput = $state('');
  let content = $state('');
  let submitting = $state(false);

  $effect(() => {
    if (open) {
      name = editing?.name ?? '';
      filename = editing?.filename ?? '';
      description = editing?.description ?? '';
      tagsInput = (editing?.tags ?? []).join(', ');
      content = '';
      if (editing) {
        api
          .content(editing.id)
          .then((data) => (content = data.content))
          .catch(() => (content = ''));
      }
    }
  });

  async function onSubmit(e: SubmitEvent) {
    e.preventDefault();
    submitting = true;
    try {
      const data = {
        name: name.trim(),
        filename: filename.trim(),
        description: description.trim(),
        tags: parseTags(tagsInput),
        content,
      };
      if (editing) {
        await playbooks.update(editing.id, data);
        showToast($t('toast.playbook.saved'));
      } else {
        await playbooks.create(data);
        showToast($t('toast.playbook.created'));
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
  title={editing ? $t('modal.playbook.title') : $t('modal.playbook.titleNew')}
  width="820px"
  {onClose}
>
  <form class="modal-form" onsubmit={onSubmit} id="playbook-form">
    <div class="field">
      <label for="pbName">{$t('label.name')} *</label>
      <input id="pbName" required bind:value={name} />
    </div>
    <div class="field">
      <label for="pbFilename">{$t('modal.playbook.filename')}</label>
      <input id="pbFilename" required placeholder="deploy.yml" bind:value={filename} />
    </div>
    <div class="field full">
      <label for="pbDesc">{$t('modal.hook.description')}</label>
      <input id="pbDesc" placeholder={$t('modal.hook.descPlaceholder')} bind:value={description} />
    </div>
    <div class="field full">
      <label for="pbTags">{$t('modal.server.tagsComma')}</label>
      <input id="pbTags" placeholder="prod, deploy" bind:value={tagsInput} />
    </div>
    <div class="field full">
      <label for="pbContent">{$t('modal.playbook.content')}</label>
      <textarea
        id="pbContent"
        required
        style="min-height:300px;font-family:monospace;font-size:13px"
        bind:value={content}
      ></textarea>
    </div>
  </form>
  {#snippet footer()}
    <Button variant="ghost" onclick={onClose}>{$t('action.cancel')}</Button>
    <Button
      variant="primary"
      type="submit"
      disabled={submitting}
      onclick={() => (document.getElementById('playbook-form') as HTMLFormElement)?.requestSubmit()}
    >
      {$t('action.save')}
    </Button>
  {/snippet}
</Modal>
