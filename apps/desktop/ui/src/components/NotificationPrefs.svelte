<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import { errMsg } from '$lib/utils/errors';
  import { onMount } from 'svelte';
  import { get } from 'svelte/store';
  import { session, settings } from '$lib/stores/session';
  import { showNotice } from '$lib/stores/statusBar';
  import { setDesktopPrefs } from '$lib/stores/notifyPrefs';
  import { notifyOs } from '$lib/osNotify';
  import { t, tNow } from '$lib/i18n';
  import { notificationsApi } from '$lib/api/notifications';
  import { monitoringApi } from '$lib/api/monitoring';
  import Button from './ui/Button.svelte';
  import Checkbox from './ui/Checkbox.svelte';
  import Switch from './ui/Switch.svelte';
  import type {
    NotificationAvailableChannels,
    NotificationChannel,
    NotificationMatrix,
    NotificationMatrixRow,
    NotificationPrefs,
    NotificationScopeType,
    NotificationSeverity,
    NotificationSubscriptionInput,
    Server,
  } from '$lib/api/types';

  // Local editable shape. categories is preserved but not exposed in the UI yet — it must
  // survive a load/save round-trip (the PUT is replace-all), otherwise editing here would
  // silently wipe a filter set via another client.
  interface EditRule {
    scopeType: NotificationScopeType;
    scopeRef: string;
    minSeverity: NotificationSeverity;
    categories: string[] | null;
    enabled: boolean;
  }

  type Targeted = Exclude<NotificationChannel, 'desktop'>;

  const SCOPES: NotificationScopeType[] = ['all', 'tag', 'server'];
  const SEVERITIES: NotificationSeverity[] = ['info', 'warning', 'critical'];
  const CHANNELS: NotificationChannel[] = ['desktop', 'email', 'ntfy', 'telegram', 'webhook'];
  const ROWS: NotificationMatrixRow[] = ['critical', 'warning', 'info', 'ok'];
  // The categories the server creates today (spec kern-notify-2, goals).
  const CATEGORIES = ['monitoring', 'security', 'tunnel', 'agent'];
  // The URLs carry their access in them (ntfy ?auth=, a webhook path): shown masked.
  const SECRET: NotificationChannel[] = ['ntfy', 'webhook'];
  // The server's default without a row: the desktop gets everything, nothing else.
  const DEFAULT_MATRIX: NotificationMatrix = {
    critical: ['desktop'],
    warning: ['desktop'],
    info: ['desktop'],
    ok: ['desktop'],
  };

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

  let targets = $state<Record<Targeted, string>>({
    email: '',
    ntfy: '',
    telegram: '',
    webhook: '',
  });
  // What the server holds: the test goes to the stored target, not to an unsaved edit.
  let stored = $state<Record<Targeted, string>>({ email: '', ntfy: '', telegram: '', webhook: '' });
  let matrix = $state<NotificationMatrix>(structuredClone(DEFAULT_MATRIX));
  let disabled = $state<NotificationChannel[]>([]);
  let muted = $state<string[]>([]);
  let available = $state<NotificationAvailableChannels | null>(null);
  let rules = $state<EditRule[]>([]);
  let servers = $state<Server[]>([]);
  let loading = $state(true);
  let saving = $state(false);
  let savedMsg = $state('');
  let errorMsg = $state('');
  let testing = $state<NotificationChannel | null>(null);
  let testResult = $state<Partial<Record<NotificationChannel, { ok: boolean; text: string }>>>({});

  // All distinct tags across the inventory, for the tag-scope dropdown.
  let allTags = $derived(
    [...new Set(servers.flatMap((s) => s.tags ?? []))].sort((a, b) => a.localeCompare(b)),
  );

  onMount(load);

  function targetsOf(p: NotificationPrefs): Record<Targeted, string> {
    return {
      email: p.email ?? '',
      ntfy: p.ntfyUrl ?? '',
      telegram: p.telegramChatId ?? '',
      webhook: p.webhookUrl ?? '',
    };
  }

  function apply(p: NotificationPrefs): void {
    targets = targetsOf(p);
    stored = targetsOf(p);
    matrix = structuredClone(p.matrix ?? DEFAULT_MATRIX);
    disabled = [...(p.disabledChannels ?? [])];
    muted = [...(p.mutedCategories ?? [])];
    available = p.available ?? null;
  }

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
      apply(prefs);
      servers = Array.isArray(srv) ? srv : [];
      rules = (prefs.subscriptions ?? []).map((s) => ({
        scopeType: s.scopeType,
        scopeRef: s.scopeRef ?? '',
        minSeverity: s.minSeverity,
        categories: parseCategories(s.categories),
        enabled: s.enabled,
      }));
    } catch (err) {
      errorMsg = errMsg(err);
    } finally {
      loading = false;
    }
  }

  function isOn(ch: NotificationChannel): boolean {
    return !disabled.includes(ch);
  }

  function setOn(ch: NotificationChannel, on: boolean): void {
    disabled = on ? disabled.filter((c) => c !== ch) : [...disabled, ch];
  }

  function setCell(row: NotificationMatrixRow, ch: NotificationChannel, on: boolean): void {
    const rest = matrix[row].filter((c) => c !== ch);
    // Kept in channel order, as the server stores it.
    matrix[row] = on ? CHANNELS.filter((c) => c === ch || rest.includes(c)) : rest;
  }

  function toggleCategory(cat: string): void {
    muted = muted.includes(cat) ? muted.filter((c) => c !== cat) : [...muted, cat];
  }

  function addRule(): void {
    rules = [
      ...rules,
      { scopeType: 'all', scopeRef: '', minSeverity: 'warning', categories: null, enabled: true },
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
      categories: r.categories,
      enabled: r.enabled,
    }));
    try {
      const saved = await notificationsApi.savePrefs(sess, {
        email: targets.email.trim() || null,
        telegram_chat_id: targets.telegram.trim() || null,
        ntfy_url: targets.ntfy.trim() || null,
        webhook_url: targets.webhook.trim() || null,
        matrix: $state.snapshot(matrix),
        disabled_channels: [...disabled],
        muted_categories: [...muted],
        subscriptions,
      });
      apply(saved);
      setDesktopPrefs(saved);
      savedMsg = $t('notifPrefs.saved');
    } catch (err) {
      errorMsg = errMsg(err);
    } finally {
      saving = false;
    }
  }

  // The desktop tests itself: a toast, and the OS notice while the user opted in.
  async function testDesktop(): Promise<void> {
    const title = tNow('notifPrefs.testTitle');
    const body = tNow('notifPrefs.testBody');
    showNotice({ title, body, tone: 'info' });
    if (get(settings)?.osNotifications) {
      await notifyOs([
        {
          id: 0,
          createdAt: new Date().toISOString(),
          severity: 'info',
          category: 'test',
          eventType: 'test',
          title,
          body,
          read: false,
        },
      ]);
    }
  }

  async function test(ch: NotificationChannel): Promise<void> {
    const sess = get(session);
    if (!sess) return;
    testing = ch;
    const cleared = { ...testResult };
    delete cleared[ch];
    testResult = cleared;
    try {
      if (ch === 'desktop') await testDesktop();
      else await notificationsApi.testChannel(sess, ch);
      testResult = { ...testResult, [ch]: { ok: true, text: $t('notifPrefs.testSent') } };
    } catch (err) {
      testResult = { ...testResult, [ch]: { ok: false, text: errMsg(err) } };
    } finally {
      testing = null;
    }
  }

  function canDeliver(ch: NotificationChannel): boolean {
    return available ? available[ch] : true;
  }

  function unsaved(ch: NotificationChannel): boolean {
    return ch !== 'desktop' && targets[ch].trim() !== stored[ch];
  }
</script>

<div class="np">
  {#if loading}
    <span class="np-muted">{$t('notifPrefs.loading')}</span>
  {:else}
    <section class="np-sec">
      <div class="np-head">
        <span class="np-title">{$t('notifPrefs.channels')}</span>
        <span class="np-muted">{$t('notifPrefs.channelsDesc')}</span>
      </div>
      {#each CHANNELS as ch (ch)}
        <div class="np-channel" data-channel={ch}>
          <span class="np-name">{$t(`notifPrefs.channel.${ch}`)}</span>
          <div class="np-target">
            {#if ch === 'desktop'}
              <span class="np-muted">{$t('notifPrefs.target.desktop')}</span>
            {:else}
              <input
                type={ch === 'email' ? 'email' : SECRET.includes(ch) ? 'password' : 'text'}
                autocomplete="off"
                spellcheck="false"
                bind:value={targets[ch]}
                placeholder={$t(`notifPrefs.target.${ch}`)}
                aria-label={$t(`notifPrefs.targetLabel.${ch}`)}
              />
            {/if}
          </div>
          <div class="np-test">
            {#if !canDeliver(ch)}
              <span class="np-muted">{$t('notifPrefs.unavailable')}</span>
            {:else}
              <Button
                size="sm"
                variant="ghost"
                loading={testing === ch}
                disabled={testing !== null || unsaved(ch)}
                title={unsaved(ch) ? $t('notifPrefs.saveFirst') : undefined}
                onclick={() => test(ch)}
              >
                {$t('notifPrefs.test')}
              </Button>
            {/if}
          </div>
          <Switch
            size="sm"
            checked={isOn(ch)}
            label={$t('notifPrefs.enabled')}
            onChange={(on) => setOn(ch, on)}
          />
          {#if testResult[ch]}
            <span class={testResult[ch]?.ok ? 'np-ok np-result' : 'np-err np-result'}>
              {testResult[ch]?.text}
            </span>
          {/if}
        </div>
      {/each}
    </section>

    <section class="np-sec">
      <div class="np-head">
        <span class="np-title">{$t('notifPrefs.matrix')}</span>
        <span class="np-muted">{$t('notifPrefs.matrixDesc')}</span>
      </div>
      <table class="np-matrix">
        <thead>
          <tr>
            <th scope="col">{$t('notifPrefs.severity')}</th>
            {#each CHANNELS as ch (ch)}
              <th scope="col" class:np-off={!isOn(ch)}>{$t(`notifPrefs.channel.${ch}`)}</th>
            {/each}
          </tr>
        </thead>
        <tbody>
          {#each ROWS as row (row)}
            <tr>
              <th scope="row">{$t(`notifPrefs.row.${row}`)}</th>
              {#each CHANNELS as ch (ch)}
                <td class:np-off={!isOn(ch)}>
                  <Checkbox
                    checked={matrix[row].includes(ch)}
                    disabled={!isOn(ch)}
                    ariaLabel={$t('notifPrefs.cell', {
                      row: $t(`notifPrefs.row.${row}`),
                      channel: $t(`notifPrefs.channel.${ch}`),
                    })}
                    onChange={(on) => setCell(row, ch, on)}
                  />
                </td>
              {/each}
            </tr>
          {/each}
        </tbody>
      </table>
    </section>

    <section class="np-sec">
      <div class="np-head">
        <span class="np-title">{$t('notifPrefs.categories')}</span>
        <span class="np-muted">{$t('notifPrefs.categoriesDesc')}</span>
      </div>
      <div class="np-chips">
        {#each CATEGORIES as cat (cat)}
          <button
            type="button"
            class="np-chip"
            class:active={!muted.includes(cat)}
            aria-pressed={!muted.includes(cat)}
            onclick={() => toggleCategory(cat)}
          >
            {$t(`notifPrefs.cat.${cat}`)}
          </button>
        {/each}
      </div>
    </section>

    <section class="np-sec">
      <div class="np-rules-head">
        <div class="np-head">
          <span class="np-title">{$t('notifPrefs.rules')}</span>
          <span class="np-muted">{$t('notifPrefs.rulesDesc')}</span>
        </div>
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

            <label class="np-check">
              <input type="checkbox" bind:checked={rule.enabled} />
              <span>{$t('notifPrefs.enabled')}</span>
            </label>

            <button
              type="button"
              class="btn ghost small np-remove"
              onclick={() => removeRule(i)}
              aria-label={$t('notifPrefs.remove')}
            >
              ✕
            </button>
          </div>
        </div>
      {/each}
    </section>

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
  .np-muted {
    font-size: 12px;
    color: var(--text-muted);
  }
  .np-sec {
    display: flex;
    flex-direction: column;
    gap: var(--sp-2, 8px);
    margin-top: var(--sp-3, 12px);
  }
  .np-head {
    display: flex;
    flex-direction: column;
    gap: 2px;
  }
  .np-title {
    font-size: 13px;
    font-weight: 600;
    color: var(--text-strong, var(--text));
  }
  .np-channel {
    display: grid;
    grid-template-columns: 90px minmax(0, 1fr) auto auto;
    align-items: center;
    gap: var(--sp-2, 8px) var(--sp-3, 12px);
    padding: var(--sp-2, 8px) 0;
    border-top: 1px solid var(--border-faint, var(--border));
  }
  .np-name {
    font-size: 13px;
    font-weight: 600;
  }
  .np-target input {
    width: 100%;
    box-sizing: border-box;
  }
  .np-result {
    grid-column: 2 / -1;
  }
  .np-matrix {
    border-collapse: collapse;
    font-size: 13px;
  }
  .np-matrix th,
  .np-matrix td {
    padding: var(--sp-1, 4px) var(--sp-2, 8px);
    border-top: 1px solid var(--border-faint, var(--border));
    text-align: center;
  }
  .np-matrix th[scope='row'],
  .np-matrix thead th:first-child {
    text-align: left;
    font-weight: 500;
  }
  .np-matrix thead th {
    font-size: 11px;
    color: var(--text-muted);
    font-weight: 500;
  }
  .np-off {
    opacity: 0.4;
  }
  .np-chips {
    display: flex;
    flex-wrap: wrap;
    gap: var(--sp-2, 8px);
  }
  .np-chip {
    height: 28px;
    padding: 0 12px;
    border-radius: 999px;
    border: 1px solid var(--border-strong, var(--border));
    background: transparent;
    color: var(--text-muted);
    font: inherit;
    font-size: 12.5px;
    cursor: pointer;
  }
  .np-chip.active {
    border-color: var(--text-strong, var(--text));
    background: var(--surface-active, var(--bg-panel));
    color: var(--text-strong, var(--text));
    font-weight: 600;
  }
  .np-rules-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
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
