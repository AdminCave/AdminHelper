<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import { get } from 'svelte/store';
  import { settings, session } from '$lib/stores/session';
  import { closeSettings, saveSettings } from '$lib/stores/settings';
  import { context } from '$lib/stores/workspace';
  import { t, resolveLanguage, type Language } from '$lib/i18n';
  import { confirmDialog } from '../ui/ConfirmDialog.svelte';
  import { getSettingsDefaults, getIntervalMinutes } from '$lib/models/settings';
  import type {
    Settings,
    RdpWindowMode,
    RdpPerformanceProfile,
    RdpScalingMode,
  } from '$lib/bridge/types';
  import NotificationPrefs from '../NotificationPrefs.svelte';
  import WorkspaceSection from './WorkspaceSection.svelte';
  import DeviceSection from './DeviceSection.svelte';
  import GeneralSection from './GeneralSection.svelte';
  import RdpSection from './RdpSection.svelte';
  import NotificationsSection from './NotificationsSection.svelte';
  import DiagnosticsSection from './DiagnosticsSection.svelte';

  // The kind of the workspace of this window: fixed, as are its name, colour and URL, which the
  // workspace list changes while the workspace is closed.
  let mode = $derived($settings?.mode ?? 'local');
  // Null only when the context of this window did not load.
  let workspace = $derived($context?.workspace ?? null);
  // Where a reset goes: the server signed in to, else the URL of the workspace as the window
  // shows it (Rust takes it for the one it keeps). Never the URL in the settings: after a save
  // Rust refused (a device identity, but no URL) they have none, and the reset is the way out.
  let resetTarget = $derived($session?.serverUrl ?? workspace?.url ?? '');

  // Read once: this component mounts on each opening (SettingsModal.svelte).
  const stored = get(settings) ?? getSettingsDefaults();
  let intervalMinutes = $state(getIntervalMinutes(stored));
  let language = $state<Language>(resolveLanguage(stored.language));
  let storePasswords = $state(Boolean(stored.storePasswords));
  let allowSelfSignedCerts = $state(Boolean(stored.allowSelfSignedCerts));
  let rdpScalingMode = $state<RdpScalingMode>(stored.rdpScalingMode ?? 'auto');
  let rdpWindowMode = $state<RdpWindowMode>(stored.rdpWindowMode ?? 'fit');
  let rdpCustomSize = $state(stored.rdpCustomSize ?? '1920x1080');
  let rdpPerformanceProfile = $state<RdpPerformanceProfile>(stored.rdpPerformanceProfile ?? 'auto');
  let osNotifications = $state(Boolean(stored.osNotifications));

  // A reset question sits in App's layer, outside this overlay, but the focus stays on the
  // reset button in here: its Escape reaches the overlay's handler before the dialog's own and
  // would close the settings under the question. A count, not a flag: a second click replaces
  // the open question, and the first one's end must not lift the guard the second one holds.
  let asking = 0;

  async function ask(message: string, confirmLabel: string): Promise<boolean> {
    asking += 1;
    try {
      return await confirmDialog(message, { confirmLabel });
    } finally {
      asking -= 1;
    }
  }

  async function onSave(): Promise<void> {
    // Rust writes the fields of the workspace whole: one this dialog does not edit
    // (lastUsername) has to come from the current settings, or saving drops it. The kind and
    // the URL go back as they came.
    const next: Settings = {
      ...($settings ?? getSettingsDefaults()),
      intervalMinutes,
      language,
      storePasswords,
      allowSelfSignedCerts,
      rdpScalingMode,
      rdpWindowMode,
      rdpCustomSize: rdpCustomSize.trim(),
      rdpPerformanceProfile,
      osNotifications,
    };
    await saveSettings(next);
  }
</script>

<div
  class="sm-overlay"
  role="dialog"
  aria-modal="true"
  onclick={(e) => {
    if (e.target === e.currentTarget) closeSettings();
  }}
  onkeydown={(e) => {
    if (e.key === 'Escape' && !asking) closeSettings();
  }}
  tabindex="-1"
>
  <div class="sm-panel">
    <div class="panel-header">
      <h2 class="panel-title">{$t('settings.title')}</h2>
      <button class="btn ghost small" onclick={closeSettings}>{$t('editor.close')}</button>
    </div>

    <section class="sm-group" data-group="workspace">
      <h3 class="sm-group-title">{$t('settings.group.workspace')}</h3>
      <WorkspaceSection
        {mode}
        {workspace}
        {resetTarget}
        {ask}
        bind:intervalMinutes
        bind:allowSelfSignedCerts
      />
      <DeviceSection {mode} {resetTarget} {allowSelfSignedCerts} {ask} />
      {#if $session}
        <div class="sm-section">
          <div class="sm-section-title">{$t('settings.section.notificationRules')}</div>
          <NotificationPrefs />
        </div>
      {/if}
    </section>

    <section class="sm-group" data-group="device">
      <h3 class="sm-group-title">{$t('settings.group.device')}</h3>
      <GeneralSection bind:language bind:storePasswords />
      <RdpSection
        bind:rdpScalingMode
        bind:rdpWindowMode
        bind:rdpCustomSize
        bind:rdpPerformanceProfile
      />
      <NotificationsSection bind:osNotifications />
      <DiagnosticsSection />
    </section>

    <div class="panel-actions">
      <div style="flex: 1;"></div>
      <button class="btn" onclick={closeSettings}>{$t('action.cancel')}</button>
      <button class="btn primary" data-action="settings-save" onclick={onSave}
        >{$t('action.save')}</button
      >
    </div>
  </div>
</div>

<style>
  .sm-overlay {
    position: fixed;
    inset: 0;
    background: rgba(0, 0, 0, 0.6);
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 60;
    padding: var(--sp-4);
  }
  .sm-panel {
    background: var(--bg-panel);
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    width: 100%;
    max-width: 560px;
    max-height: 90vh;
    overflow-y: auto;
    padding: var(--sp-5);
    display: flex;
    flex-direction: column;
    gap: var(--sp-3);
  }
  .panel-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: var(--sp-2);
  }
  .panel-title {
    margin: 0;
    font-size: 16px;
    font-weight: 600;
  }
  .sm-group {
    display: flex;
    flex-direction: column;
    gap: var(--sp-3);
  }
  .sm-group + .sm-group {
    padding-top: var(--sp-3);
    border-top: 1px solid var(--border);
  }
  .sm-group-title {
    margin: 0;
    font-size: 14px;
    font-weight: 600;
  }
  /* The building blocks every section shares; the sections keep their own rules. */
  .sm-panel :global(.sm-section) {
    display: flex;
    flex-direction: column;
    gap: var(--sp-2);
    margin-top: var(--sp-2);
  }
  .sm-panel :global(.sm-section-title) {
    font-size: 12px;
    color: var(--text-muted);
    text-transform: uppercase;
    letter-spacing: 0.5px;
  }
  .sm-panel :global(.field) {
    display: flex;
    flex-direction: column;
    gap: var(--sp-2);
  }
  .sm-panel :global(.field.checkbox) {
    flex-direction: row;
    align-items: center;
  }
  .sm-panel :global(.field-label) {
    font-size: 12px;
    color: var(--text-muted);
  }
  .sm-panel :global(.field input),
  .sm-panel :global(.field select) {
    background: var(--bg-input, var(--bg-panel));
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    color: var(--text);
    padding: var(--sp-2) var(--sp-3);
    font-size: 13px;
    font-family: inherit;
  }
  .sm-panel :global(.field input:focus),
  .sm-panel :global(.field select:focus) {
    outline: 1px solid var(--accent);
  }
  .sm-panel :global(.sm-reset-pin) {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: var(--sp-2) var(--sp-3);
  }
  .sm-panel :global(.sm-reset-msg) {
    font-size: 12px;
    color: var(--accent);
  }
  .panel-actions {
    display: flex;
    gap: var(--sp-2);
    padding-top: var(--sp-3);
    margin-top: var(--sp-2);
    border-top: 1px solid var(--border);
    align-items: center;
  }
</style>
