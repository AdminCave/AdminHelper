<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import { onMount } from 'svelte';
  import { t, language } from '$lib/i18n';
  import { playbooks } from '$lib/stores/ansible';
  import { showToast } from '$lib/stores/notifications';
  import { extractAllTags } from '$lib/utils/tags';
  import * as api from '$lib/api/ansible';
  import Button from '$lib/components/ui/Button.svelte';
  import EmptyState from '$lib/components/ui/EmptyState.svelte';
  import { confirmDialog } from '$lib/components/ui/ConfirmDialog.svelte';
  import PlaybookModal from '$modals/PlaybookModal.svelte';
  import type { Playbook } from '$lib/api/types';

  let search = $state('');
  let tagFilter = $state('');
  let expanded = $state<Set<string>>(new Set());
  let previews = $state<Record<string, string | null>>({});
  let modalOpen = $state(false);
  let editing = $state<Playbook | null>(null);

  onMount(() => {
    load();
  });

  async function load() {
    try {
      await playbooks.refresh();
    } catch (err) {
      showToast(err instanceof Error ? err.message : 'Fehler', 'error');
    }
  }

  const allTags = $derived(extractAllTags($playbooks));

  const filtered = $derived.by(() => {
    const q = search.toLowerCase();
    return $playbooks.filter((p) => {
      if (tagFilter && !(p.tags ?? []).includes(tagFilter)) return false;
      if (!q) return true;
      return (
        p.name.toLowerCase().includes(q) ||
        p.filename.toLowerCase().includes(q) ||
        (p.description ?? '').toLowerCase().includes(q) ||
        (p.tags ?? []).some((tg) => tg.toLowerCase().includes(q))
      );
    });
  });

  function formatDate(iso: string | null | undefined): string {
    if (!iso) return '';
    const loc = $language === 'de' ? 'de-DE' : 'en-GB';
    try {
      return new Date(iso).toLocaleDateString(loc);
    } catch {
      return '';
    }
  }

  async function toggleCard(id: string) {
    const willOpen = !expanded.has(id);
    expanded = new Set(
      expanded.has(id) ? [...expanded].filter((x) => x !== id) : [...expanded, id],
    );
    if (willOpen && previews[id] === undefined) {
      previews = { ...previews, [id]: null };
      try {
        const data = await api.content(id);
        previews = { ...previews, [id]: data.content };
      } catch {
        previews = { ...previews, [id]: $t('page.ansible.loadError') };
      }
    }
  }

  function openCreate() {
    editing = null;
    modalOpen = true;
  }

  function openEdit(p: Playbook) {
    editing = p;
    modalOpen = true;
  }

  async function handleClose() {
    modalOpen = false;
    editing = null;
    previews = {};
    await load();
  }

  async function removePlaybook(p: Playbook) {
    if (
      !(await confirmDialog($t('confirm.playbook.delete'), { confirmLabel: $t('action.delete') }))
    )
      return;
    try {
      await playbooks.remove(p.id);
      showToast($t('toast.playbook.deleted'));
    } catch (err) {
      showToast(err instanceof Error ? err.message : 'Fehler', 'error');
    }
  }
</script>

<div class="page active">
  <div class="page-header">
    <div>
      <div class="page-title">{$t('page.ansible.title')}</div>
      <div class="page-subtitle">{$t('page.ansible.subtitle')}</div>
    </div>
    <div style="display:flex;gap:10px;align-items:center">
      <select class="filter-select" bind:value={tagFilter}>
        <option value="">{$t('label.allTags')}</option>
        {#each allTags as tag (tag)}
          <option value={tag}>{tag}</option>
        {/each}
      </select>
      <input
        type="search"
        class="search-input"
        placeholder={$t('action.searchDots')}
        bind:value={search}
      />
      <Button variant="primary" onclick={openCreate}>{$t('page.ansible.add')}</Button>
    </div>
  </div>

  <div class="panel" style="display:flex;flex-direction:column;gap:12px">
    {#if filtered.length === 0}
      <EmptyState message={$t('page.ansible.empty')} />
    {:else}
      {#each filtered as p (p.id)}
        {@const open = expanded.has(p.id)}
        {@const dateLabel = formatDate(p.updatedAt ?? p.createdAt)}
        <div class="server-card">
          <div
            class="server-card-header"
            role="button"
            tabindex="0"
            onclick={() => toggleCard(p.id)}
            onkeydown={(e) => e.key === 'Enter' && toggleCard(p.id)}
          >
            <div style="display:flex;align-items:center;gap:10px;flex:1;min-width:0">
              <span class="server-chevron" class:open>&#x25B6;</span>
              <div style="min-width:0">
                <strong>{p.name}</strong>
                {#if p.description}
                  <span style="color:var(--text-muted);font-size:13px;margin-left:8px">
                    {p.description}
                  </span>
                {/if}
              </div>
              <span style="color:var(--text-muted);font-size:12px;flex-shrink:0">
                {p.filename}
              </span>
              {#if dateLabel}
                <span style="color:var(--text-muted);font-size:11px;flex-shrink:0">
                  {dateLabel}
                </span>
              {/if}
              {#if (p.tags ?? []).length}
                <div style="display:flex;gap:4px;flex-shrink:0">
                  {#each p.tags ?? [] as tag (tag)}
                    <span class="tag">{tag}</span>
                  {/each}
                </div>
              {/if}
            </div>
            <div
              style="display:flex;gap:6px;flex-shrink:0"
              role="toolbar"
              tabindex="-1"
              onclick={(e) => e.stopPropagation()}
              onkeydown={(e) => e.stopPropagation()}
            >
              <button class="btn small" onclick={() => openEdit(p)}>{$t('action.edit')}</button>
              <button class="btn small ghost" onclick={() => removePlaybook(p)}>
                {$t('action.delete')}
              </button>
            </div>
          </div>
          {#if open}
            <div class="server-card-body">
              <pre
                style="margin:0;padding:12px;font-size:13px;overflow-x:auto;background:var(--bg-elevated);border-radius:6px">{previews[
                  p.id
                ] ?? $t('page.ansible.contentLoading')}</pre>
            </div>
          {/if}
        </div>
      {/each}
    {/if}
  </div>
</div>

<PlaybookModal open={modalOpen} {editing} onClose={handleClose} />
