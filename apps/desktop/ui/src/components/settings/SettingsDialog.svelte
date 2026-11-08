<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import { get } from 'svelte/store';
  import { settings, session } from '$lib/stores/session';
  import { closeSettings, saveSettings } from '$lib/stores/settings';
  import { terminalPrefs } from '$lib/stores/terminalPrefs';
  import { context } from '$lib/stores/workspace';
  import { t, resolveLanguage, type Language } from '$lib/i18n';
  import { confirmDialog } from '../ui/ConfirmDialog.svelte';
  import {
    getSettingsDefaults,
    getIntervalMinutes,
    RDP_CLIENT_DEFAULT,
  } from '$lib/models/settings';
  import type {
    Settings,
    RdpWindowMode,
    RdpPerformanceProfile,
    RdpClient,
    RdpScalingMode,
    SshConsole,
    TerminalPrefs,
  } from '$lib/bridge/types';
  import NotificationPrefs from '../NotificationPrefs.svelte';
  import WorkspaceSection from './WorkspaceSection.svelte';
  import DeviceSection from './DeviceSection.svelte';
  import GeneralSection from './GeneralSection.svelte';
  import RdpSection from './RdpSection.svelte';
  import TerminalSection from './TerminalSection.svelte';
  import NotificationsSection from './NotificationsSection.svelte';
  import DiagnosticsSection from './DiagnosticsSection.svelte';
  import CertificateSection from './CertificateSection.svelte';
  import ScopePill from './ScopePill.svelte';
  import { nextIndex } from '../ui/roving';

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
  let rdpClient = $state<RdpClient>(stored.rdpClient ?? RDP_CLIENT_DEFAULT);
  let rdpScalingMode = $state<RdpScalingMode>(stored.rdpScalingMode ?? 'auto');
  let rdpWindowMode = $state<RdpWindowMode>(stored.rdpWindowMode ?? 'fit');
  let rdpCustomSize = $state(stored.rdpCustomSize ?? '1920x1080');
  let rdpPerformanceProfile = $state<RdpPerformanceProfile>(stored.rdpPerformanceProfile ?? 'auto');
  let osNotifications = $state(Boolean(stored.osNotifications));
  let sshConsole = $state<SshConsole>(stored.sshConsole ?? getSettingsDefaults().sshConsole);
  let restoreSessions = $state(Boolean(stored.restoreSessions));
  // What the terminals show, so a change made in one while its save runs is not undone here.
  let terminal = $state<TerminalPrefs>(get(terminalPrefs));

  // A reset question sits in App's layer, outside this overlay, but the focus stays on the
  // reset button in here: its Escape reaches the overlay's handler before the dialog's own and
  // would close the settings under the question. A count, not a flag: a second click replaces
  // the open question, and the first one's end must not lift the guard the second one holds.
  let asking = 0;

  const SECTIONS = ['general', 'workspace', 'rdp', 'terminal', 'notifications', 'device'] as const;
  type Section = (typeof SECTIONS)[number];
  const NAV_LABEL: Record<Section, string> = {
    general: 'settings.nav.general',
    workspace: 'settings.nav.workspace',
    rdp: 'settings.nav.rdp',
    terminal: 'settings.nav.terminal',
    notifications: 'settings.nav.notifications',
    device: 'settings.nav.device',
  };
  // Every pane stays mounted and only the active one shows: what is typed in one survives a
  // switch to the next, saving takes all of them, and the device section reads the
  // registration on opening as before.
  let active = $state<Section>('general');
  let navButtons: HTMLButtonElement[] = $state([]);

  function onNavKey(e: KeyboardEvent, i: number): void {
    const to = nextIndex(e.key, i, SECTIONS.length);
    if (to === undefined) return;
    e.preventDefault();
    active = SECTIONS[to];
    navButtons[to]?.focus();
  }

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
      rdpClient,
      rdpScalingMode,
      rdpWindowMode,
      rdpCustomSize: rdpCustomSize.trim(),
      rdpPerformanceProfile,
      osNotifications,
      sshConsole,
      terminal,
      // Unset is off, so a dialog saved without touching it writes nothing new.
      restoreSessions: restoreSessions || undefined,
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

    <div class="sm-body">
      <div
        class="sm-nav"
        role="tablist"
        aria-orientation="vertical"
        aria-label={$t('settings.title')}
      >
        {#each SECTIONS as id, i (id)}
          <button
            bind:this={navButtons[i]}
            type="button"
            role="tab"
            class="sm-nav-item"
            id="sm-tab-{id}"
            data-section={id}
            aria-selected={active === id}
            aria-controls="sm-pane-{id}"
            tabindex={active === id ? 0 : -1}
            onclick={() => (active = id)}
            onkeydown={(e) => onNavKey(e, i)}>{$t(NAV_LABEL[id])}</button
          >
        {/each}
      </div>

      <div class="sm-content">
        <div
          class="sm-pane"
          role="tabpanel"
          id="sm-pane-general"
          aria-labelledby="sm-tab-general"
          data-pane="general"
          hidden={active !== 'general'}
        >
          <GeneralSection {mode} bind:language bind:storePasswords bind:allowSelfSignedCerts />
        </div>
        <div
          class="sm-pane"
          role="tabpanel"
          id="sm-pane-workspace"
          aria-labelledby="sm-tab-workspace"
          data-pane="workspace"
          hidden={active !== 'workspace'}
        >
          <WorkspaceSection {mode} {workspace} bind:intervalMinutes />
        </div>
        <div
          class="sm-pane"
          role="tabpanel"
          id="sm-pane-rdp"
          aria-labelledby="sm-tab-rdp"
          data-pane="rdp"
          hidden={active !== 'rdp'}
        >
          <div data-scope="device">
            <RdpSection
              bind:rdpClient
              bind:rdpScalingMode
              bind:rdpWindowMode
              bind:rdpCustomSize
              bind:rdpPerformanceProfile
            />
          </div>
        </div>
        <div
          class="sm-pane"
          role="tabpanel"
          id="sm-pane-terminal"
          aria-labelledby="sm-tab-terminal"
          data-pane="terminal"
          hidden={active !== 'terminal'}
        >
          <div data-scope="device">
            <TerminalSection bind:sshConsole bind:terminal bind:restoreSessions />
          </div>
        </div>
        <div
          class="sm-pane"
          role="tabpanel"
          id="sm-pane-notifications"
          aria-labelledby="sm-tab-notifications"
          data-pane="notifications"
          hidden={active !== 'notifications'}
        >
          <div data-scope="device"><NotificationsSection bind:osNotifications /></div>
          {#if $session}
            <div class="sm-section" data-scope="workspace">
              <div class="sm-section-title">
                {$t('settings.section.notificationRules')}
                <ScopePill />
              </div>
              <NotificationPrefs />
            </div>
          {/if}
        </div>
        <div
          class="sm-pane"
          role="tabpanel"
          id="sm-pane-device"
          aria-labelledby="sm-tab-device"
          data-pane="device"
          hidden={active !== 'device'}
        >
          <DeviceSection {mode} {resetTarget} {allowSelfSignedCerts} {ask} />
          <CertificateSection {mode} {resetTarget} {ask} />
          <div data-scope="device"><DiagnosticsSection /></div>
        </div>
      </div>
    </div>

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
    max-width: 860px;
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
  .sm-body {
    display: grid;
    grid-template-columns: 180px 1fr;
    gap: var(--sp-4);
    min-height: 0;
  }
  .sm-nav {
    display: flex;
    flex-direction: column;
    gap: 2px;
    padding-right: var(--sp-3);
    border-right: 1px solid var(--border);
  }
  .sm-nav-item {
    text-align: left;
    padding: var(--sp-2) var(--sp-3);
    border: 0;
    border-radius: var(--radius-sm);
    background: transparent;
    color: var(--text-muted);
    font: inherit;
    font-size: 13px;
    cursor: pointer;
  }
  .sm-nav-item:hover {
    color: var(--text);
    background: var(--bg-subtle);
  }
  .sm-nav-item[aria-selected='true'] {
    color: var(--text-strong);
    background: var(--bg-subtle);
    font-weight: 600;
  }
  .sm-content {
    min-width: 0;
  }
  .sm-pane {
    display: flex;
    flex-direction: column;
    gap: var(--sp-3);
  }
  .sm-pane[hidden] {
    display: none;
  }
  /* The building blocks every section shares; the sections keep their own rules. */
  .sm-panel :global(.sm-section) {
    display: flex;
    flex-direction: column;
    gap: var(--sp-2);
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
