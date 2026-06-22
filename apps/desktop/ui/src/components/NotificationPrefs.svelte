<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import { onMount } from 'svelte';
  import { get } from 'svelte/store';
  import { session } from '$lib/stores/session';
  import { t } from '$lib/i18n';
  import { notificationsApi } from '$lib/api/notifications';
  import { monitoringApi } from '$lib/api/monitoring';
  import type {
    NotificationScopeType,
    NotificationSeverity,
    NotificationSubscriptionInput,
    Server,
  } from '$lib/api/types';

  // Local editable shape. channelTelegram and categories are preserved but not
  // exposed in the UI yet — they must survive a load/save round-trip (the PUT is
  // replace-all), otherwise editing here would silently wipe a filter set via
  // another client.
  interface EditRule {
    scopeType: NotificationScopeType;
    scopeRef: string;
    minSeverity: NotificationSeverity;
    channelEmail: boolean;
    channelTelegram: boolean;
    categories: string[] | null;
    enabled: boolean;
  }

  const SCOPES: NotificationScopeType[] = ['all', 'tag', 'server'];
  const SEVERITIES: NotificationSeverity[] = ['info', 'warning', 'critical'];

  // categories is stored server-side as a JSON-array string; parse it back to a
  // string[] so it survives the round-trip (malformed → null, not a crash).
  function parseCategories(raw: string | null | undefined): string[] | null {
    if (!raw) return null;
    try {
      const v = JSON.parse(raw);
      return Array.isArray(v) ? v.map(String) : null;
    } catch {
      return null;
    }
  }

  let email = $state('');
  let rules = $state<EditRule[]>([]);
  let servers = $state<Server[]>([]);
  let loading = $state(true);
  let saving = $state(false);
  let savedMsg = $state('');
  let errorMsg = $state('');

  // All distinct tags across the inventory, for the tag-scope dropdown.
  let allTags = $derived(
    [...new Set(servers.flatMap((s) => s.tags ?? []))].sort((a, b) => a.localeCompare(b)),
  );

  onMount(load);

  async function load(): Promise<void> {
    const sess = get(session);
    if (!sess) {
      loading = false;
      return;
    }
    loading = true;
    errorMsg = '';
    try {
      const [prefs, srv] = await Promise.all([
        notificationsApi.fetchPrefs(sess),
        monitoringApi.fetchServers(sess).catch(() => [] as Server[]),
      ]);
      email = prefs.email ?? '';
      servers = Array.isArray(srv) ? srv : [];
      rules = (prefs.subscriptions ?? []).map((s) => ({
        scopeType: s.scopeType,
        scopeRef: s.scopeRef ?? '',
        minSeverity: s.minSeverity,
        channelEmail: s.channelEmail,
        channelTelegram: s.channelTelegram,
        categories: parseCategories(s.categories),
        enabled: s.enabled,
      }));
    } catch (err) {
      errorMsg = err instanceof Error ? err.message : String(err);
    } finally {
      loading = false;
    }
  }

  function addRule(): void {
    rules = [
      ...rules,
      {
        scopeType: 'all',
        scopeRef: '',
        minSeverity: 'warning',
        channelEmail: false,
        channelTelegram: false,
        categories: null,
        enabled: true,
      },
    ];
  }

  function removeRule(index: number): void {
    rules = rules.filter((_, i) => i !== index);
  }

  async function save(): Promise<void> {
    const sess = get(session);
    if (!sess) return;
    saving = true;
    savedMsg = '';
    errorMsg = '';
    const subscriptions: NotificationSubscriptionInput[] = rules.map((r) => ({
      scope_type: r.scopeType,
      scope_ref: r.scopeType === 'all' ? null : r.scopeRef.trim(),
      min_severity: r.minSeverity,
      channel_email: r.channelEmail,
      channel_telegram: r.channelTelegram,
      categories: r.categories,
      enabled: r.enabled,
    }));
    try {
      await notificationsApi.savePrefs(sess, {
        email: email.trim() || null,
        subscriptions,
      });
      savedMsg = $t('notifPrefs.saved');
    } catch (err) {
      errorMsg = err instanceof Error ? err.message : String(err);
    } finally {
      saving = false;
    }
  }
</script>

<div class="np">
  {#if loading}
    <span class="np-muted">{$t('notifPrefs.loading')}</span>
  {:else}
    <label class="np-field">
      <span class="np-label">{$t('notifPrefs.email')}</span>
      <input type="email" bind:value={email} placeholder={$t('notifPrefs.emailPlaceholder')} />
    </label>

    <div class="np-rules-head">
      <span class="np-label">{$t('notifPrefs.rules')}</span>
      <button type="button" class="btn ghost small" onclick={addRule}>
        {$t('notifPrefs.addRule')}
      </button>
    </div>

    {#if rules.length === 0}
      <span class="np-muted">{$t('notifPrefs.noRules')}</span>
    {/if}

    {#each rules as rule, i (i)}
      <div class="np-rule">
        <div class="np-rule-row">
          <select bind:value={rule.scopeType} aria-label={$t('notifPrefs.scope')}>
            {#each SCOPES as sc (sc)}
              <option value={sc}>{$t(`notifPrefs.scope.${sc}`)}</option>
            {/each}
          </select>

          {#if rule.scopeType === 'server'}
            <select bind:value={rule.scopeRef} aria-label={$t('notifPrefs.scope.server')}>
              <option value="">{$t('notifPrefs.pickServer')}</option>
              {#each servers as s (s.id)}
                <option value={s.id}>{s.name}</option>
              {/each}
            </select>
          {:else if rule.scopeType === 'tag'}
            <select bind:value={rule.scopeRef} aria-label={$t('notifPrefs.scope.tag')}>
              <option value="">{$t('notifPrefs.pickTag')}</option>
              {#each allTags as tag (tag)}
                <option value={tag}>{tag}</option>
              {/each}
            </select>
          {/if}

          <select bind:value={rule.minSeverity} aria-label={$t('notifPrefs.minSeverity')}>
            {#each SEVERITIES as sev (sev)}
              <option value={sev}>{$t(`notifPrefs.sev.${sev}`)}</option>
            {/each}
          </select>

          <button
            type="button"
            class="btn ghost small np-remove"
            onclick={() => removeRule(i)}
            aria-label={$t('notifPrefs.remove')}
          >
            ✕
          </button>
        </div>
        <div class="np-rule-row np-rule-toggles">
          <label class="np-check">
            <input type="checkbox" bind:checked={rule.channelEmail} />
            <span>{$t('notifPrefs.channelEmail')}</span>
          </label>
          <label class="np-check">
            <input type="checkbox" bind:checked={rule.enabled} />
            <span>{$t('notifPrefs.enabled')}</span>
          </label>
        </div>
      </div>
    {/each}

    <div class="np-actions">
      <button type="button" class="btn primary small" onclick={save} disabled={saving}>
        {$t('notifPrefs.save')}
      </button>
      {#if savedMsg}<span class="np-ok">{savedMsg}</span>{/if}
      {#if errorMsg}<span class="np-err">{errorMsg}</span>{/if}
    </div>
  {/if}
</div>

<style>
  .np {
    display: flex;
    flex-direction: column;
    gap: var(--sp-2, 8px);
    padding-top: var(--sp-2, 8px);
  }
  .np-field {
    display: flex;
    flex-direction: column;
    gap: var(--sp-1, 4px);
  }
  .np-label {
    font-size: 12px;
    color: var(--text-muted);
  }
  .np-muted {
    font-size: 12px;
    color: var(--text-muted);
  }
  .np-rules-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-top: var(--sp-2, 8px);
  }
  .np-rule {
    display: flex;
    flex-direction: column;
    gap: var(--sp-2, 6px);
    padding: var(--sp-2, 8px);
    border: 1px solid var(--border);
    border-radius: var(--radius-sm, 6px);
  }
  .np-rule-row {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: var(--sp-2, 8px);
  }
  .np-rule-toggles {
    gap: var(--sp-4, 16px);
  }
  .np-check {
    display: flex;
    align-items: center;
    gap: var(--sp-2, 6px);
    font-size: 13px;
  }
  .np-remove {
    margin-left: auto;
  }
  .np input,
  .np select {
    background: var(--bg-input, var(--bg-panel));
    border: 1px solid var(--border);
    border-radius: var(--radius-sm, 6px);
    color: var(--text);
    padding: var(--sp-2, 6px) var(--sp-3, 10px);
    font-size: 13px;
    font-family: inherit;
  }
  .np-actions {
    display: flex;
    align-items: center;
    gap: var(--sp-3, 12px);
    margin-top: var(--sp-2, 8px);
  }
  .np-ok {
    font-size: 12px;
    color: var(--accent);
  }
  .np-err {
    font-size: 12px;
    color: var(--danger);
  }
</style>
