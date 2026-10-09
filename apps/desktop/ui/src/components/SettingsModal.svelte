<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import { settings, session } from '$lib/stores/session';
  import { reportError } from '$lib/stores/statusBar';
  import { errMsg, withoutErrorCodes } from '$lib/utils/errors';
  import {
    settingsModalOpen,
    closeSettings,
    saveSettings,
    serverLogout,
  } from '$lib/stores/settings';
  import { t } from '$lib/i18n';
  import {
    resetServerCertPin,
    resetDeviceIdentity,
    isDeviceEnrolled,
    enrollWithToken,
    exportBrowserP12,
    generateDiagnostics,
  } from '$lib/bridge';
  import { startIfServerMode, stop as stopTunnel } from '$lib/stores/tunnel';
  import { save, confirm } from '@tauri-apps/plugin-dialog';
  import {
    RDP_WINDOW_MODES,
    RDP_PERFORMANCE_PROFILES,
    RDP_SCALING_MODES,
    getSettingsDefaults,
    getIntervalMinutes,
  } from '$lib/models/settings';
  import type {
    Settings,
    SyncMode,
    RdpWindowMode,
    RdpPerformanceProfile,
    RdpScalingMode,
  } from '$lib/bridge/types';
  import { ensureNotificationPermission } from '$lib/osNotify';
  import NotificationPrefs from './NotificationPrefs.svelte';

  let mode = $state<SyncMode>('local');
  let url = $state('');
  let intervalMinutes = $state(1);
  let language = $state<'de' | 'en'>('de');
  let storePasswords = $state(false);
  let allowSelfSignedCerts = $state(false);
  let rdpScalingMode = $state<RdpScalingMode>('auto');
  let rdpWindowMode = $state<RdpWindowMode>('fit');
  let rdpCustomSize = $state('1920x1080');
  let rdpPerformanceProfile = $state<RdpPerformanceProfile>('auto');
  let serverUrl = $state('');
  let osNotifications = $state(false);
  let pinResetMsgKey = $state('');
  let deviceEnrolled = $state(false);
  let deviceResetMsgKey = $state('');
  let enrollToken = $state('');
  let enrollMsg = $state('');
  let enrollBusy = $state(false);
  let browserCertPassword = $state('');
  let browserCertMsg = $state('');
  let browserCertBusy = $state(false);
  let diagBusy = $state(false);
  let diagMsg = $state('');

  $effect(() => {
    if (!$settingsModalOpen) return;
    const s = $settings ?? getSettingsDefaults();
    mode = s.mode;
    url = s.url ?? '';
    intervalMinutes = getIntervalMinutes(s);
    language = s.language === 'en' ? 'en' : 'de';
    storePasswords = Boolean(s.storePasswords);
    allowSelfSignedCerts = Boolean(s.allowSelfSignedCerts);
    rdpScalingMode = s.rdpScalingMode ?? 'auto';
    rdpWindowMode = s.rdpWindowMode ?? 'fit';
    rdpCustomSize = s.rdpCustomSize ?? '1920x1080';
    rdpPerformanceProfile = s.rdpPerformanceProfile ?? 'auto';
    serverUrl = s.serverUrl ?? '';
    osNotifications = Boolean(s.osNotifications);
    pinResetMsgKey = '';
    deviceResetMsgKey = '';
    enrollToken = '';
    enrollMsg = '';
    enrollBusy = false;
    browserCertPassword = '';
    browserCertMsg = '';
    browserCertBusy = false;
    diagMsg = '';
    diagBusy = false;
    void refreshDeviceEnrolled();
  });

  async function refreshDeviceEnrolled(): Promise<void> {
    try {
      deviceEnrolled = await isDeviceEnrolled();
    } catch {
      deviceEnrolled = false;
    }
  }

  async function onResetPin(): Promise<void> {
    const target = (mode === 'sync' ? url : serverUrl).trim();
    if (!target) {
      pinResetMsgKey = 'settings.resetCertPin.missingUrl';
      return;
    }
    try {
      await resetServerCertPin(target);
      pinResetMsgKey = 'settings.resetCertPin.done';
    } catch (err) {
      // Surface the failure (e.g. a locked keyring) instead of silently clearing
      // the status — else the user thinks the pin reset and hits the same error.
      pinResetMsgKey = '';
      reportError(errMsg(err));
    }
  }

  async function onResetDeviceIdentity(): Promise<void> {
    const target = (mode === 'sync' ? url : serverUrl).trim();
    if (!target) {
      deviceResetMsgKey = 'settings.resetCertPin.missingUrl';
      return;
    }
    // Destructive: drops the mTLS device cert (re-enrollment required). Confirm
    // with an explicit danger warning before doing it.
    const ok = await confirm($t('settings.resetDeviceId.confirm'), {
      title: $t('settings.resetDeviceId'),
      kind: 'warning',
    });
    if (!ok) return;
    try {
      await resetDeviceIdentity(target);
      deviceEnrolled = false;
      enrollMsg = '';
      deviceResetMsgKey = 'settings.resetDeviceId.done';
    } catch (err) {
      deviceResetMsgKey = '';
      reportError(errMsg(err));
    }
  }

  async function onEnroll(): Promise<void> {
    const target = ($session?.serverUrl ?? serverUrl).trim();
    const token = enrollToken.trim();
    if (!target) {
      enrollMsg = $t('settings.resetCertPin.missingUrl');
      return;
    }
    if (!token) return;
    enrollBusy = true;
    enrollMsg = '';
    deviceResetMsgKey = '';
    try {
      await enrollWithToken(target, token, allowSelfSignedCerts);
      deviceEnrolled = true;
      enrollToken = '';
      enrollMsg = $t('settings.enroll.done');
    } catch (err) {
      enrollMsg = withoutErrorCodes(errMsg(err));
      return;
    } finally {
      enrollBusy = false;
    }
    // frpc reads the identity only when it starts (export_identity). After a reset
    // it may still run on the old identity — the reset clears the keyring, not the
    // process — and a start next to it fails ("frpc laeuft bereits"). Stopping is a
    // no-op when none runs; a frpc that cannot be stopped is reported by the start.
    try {
      await stopTunnel();
    } catch {
      // reported by startIfServerMode below
    }
    await startIfServerMode();
  }

  async function onExportBrowserCert(): Promise<void> {
    const sess = $session;
    if (!sess) return;
    // Characters as Rust counts them (chars(), code points), not UTF-16 units:
    // check_export_password rejects anything shorter than 12, and that rejection
    // would only reach the user as the generic export error below.
    if ([...browserCertPassword].length < 12) {
      browserCertMsg = $t('settings.browserCert.passwordTooShort');
      return;
    }
    const destPath = await save({
      defaultPath: 'adminhelper-browser.p12',
      filters: [{ name: 'PKCS12', extensions: ['p12', 'pfx'] }],
    });
    if (!destPath) return;
    browserCertBusy = true;
    browserCertMsg = $t('settings.browserCert.working');
    try {
      const path = await exportBrowserP12(
        sess.serverUrl,
        sess.token,
        browserCertPassword,
        destPath,
        allowSelfSignedCerts,
      );
      browserCertMsg = `${$t('settings.browserCert.done')} ${path}`;
      browserCertPassword = '';
    } catch {
      browserCertMsg = $t('settings.browserCert.error');
    } finally {
      browserCertBusy = false;
    }
  }

  async function onGenerateDiagnostics(): Promise<void> {
    diagBusy = true;
    diagMsg = $t('settings.diagnostics.working');
    try {
      const path = await generateDiagnostics();
      diagMsg = `${$t('settings.diagnostics.done')} ${path}`;
    } catch {
      diagMsg = $t('settings.diagnostics.error');
    } finally {
      diagBusy = false;
    }
  }

  async function onSave(): Promise<void> {
    const next: Settings = {
      mode,
      url: url.trim(),
      intervalMinutes,
      language,
      storePasswords,
      allowSelfSignedCerts,
      rdpScalingMode,
      rdpWindowMode,
      rdpCustomSize: rdpCustomSize.trim(),
      rdpPerformanceProfile,
      serverUrl: serverUrl.trim(),
      osNotifications,
    };
    await saveSettings(next);
  }

  async function onLogout(): Promise<void> {
    await serverLogout();
  }

  async function onToggleOsNotifications(checked: boolean): Promise<void> {
    osNotifications = checked;
    // Request OS permission on enable (a user gesture); revert if denied.
    if (checked && !(await ensureNotificationPermission())) {
      osNotifications = false;
    }
  }

  let rdpScalingLabels = $derived({
    auto: $t('settings.rdp.scaling.auto'),
    normal: $t('settings.rdp.scaling.normal'),
    hdpi: $t('settings.rdp.scaling.hdpi'),
  });
  let rdpWindowLabels = $derived({
    fit: $t('settings.rdp.window.fit'),
    fullscreen: $t('settings.rdp.window.fullscreen'),
    multimon: $t('settings.rdp.window.multimon'),
    custom: $t('settings.rdp.window.custom'),
  });
  let rdpPerfLabels = $derived({
    auto: $t('settings.rdp.perf.auto'),
    lan: $t('settings.rdp.perf.lan'),
    broadband: $t('settings.rdp.perf.broadband'),
    low: $t('settings.rdp.perf.low'),
  });
  function rdpScalingLabel(m: RdpScalingMode): string {
    return rdpScalingLabels[m];
  }
  function rdpWindowLabel(m: RdpWindowMode): string {
    return rdpWindowLabels[m];
  }
  function rdpPerfLabel(m: RdpPerformanceProfile): string {
    return rdpPerfLabels[m];
  }
</script>

{#if $settingsModalOpen}
  <div
    class="sm-overlay"
    role="dialog"
    aria-modal="true"
    onclick={(e) => {
      if (e.target === e.currentTarget) closeSettings();
    }}
    onkeydown={(e) => {
      if (e.key === 'Escape') closeSettings();
    }}
    tabindex="-1"
  >
    <div class="sm-panel">
      <div class="panel-header">
        <h2 class="panel-title">{$t('settings.title')}</h2>
        <button class="btn ghost small" onclick={closeSettings}>{$t('editor.close')}</button>
      </div>

      <div class="sm-section">
        <div class="sm-section-title">{$t('settings.section.mode')}</div>
        <div class="sm-radio-group">
          <label class="sm-radio">
            <input
              type="radio"
              name="syncMode"
              value="local"
              checked={mode === 'local'}
              onchange={() => (mode = 'local')}
            />
            <span>{$t('settings.mode.local')}</span>
          </label>
          <label class="sm-radio">
            <input
              type="radio"
              name="syncMode"
              value="sync"
              checked={mode === 'sync'}
              onchange={() => (mode = 'sync')}
            />
            <span>{$t('settings.mode.syncLabel')}</span>
          </label>
          <label class="sm-radio">
            <input
              type="radio"
              name="syncMode"
              value="server"
              checked={mode === 'server'}
              onchange={() => (mode = 'server')}
            />
            <span>{$t('settings.mode.server')}</span>
          </label>
        </div>
      </div>

      {#if mode === 'sync'}
        <label class="field">
          <span class="field-label">{$t('settings.syncUrl')}</span>
          <input type="url" bind:value={url} placeholder={$t('settings.syncUrl.placeholder')} />
        </label>
        <label class="field">
          <span class="field-label">{$t('settings.interval')}</span>
          <input type="number" min="1" max="1440" bind:value={intervalMinutes} />
        </label>
      {:else if mode === 'server'}
        <label class="field">
          <span class="field-label">{$t('settings.serverUrl')}</span>
          <input
            type="url"
            bind:value={serverUrl}
            placeholder={$t('settings.serverUrl.placeholder')}
          />
        </label>
        {#if $session}
          <div class="sm-session-row">
            <span class="field-label">{$t('settings.loggedInAs')}</span>
            <strong>{$session.username}</strong>
            <button class="btn ghost small" onclick={onLogout}>{$t('settings.logout')}</button>
          </div>
          <div class="sm-browser-cert">
            <span class="field-label">{$t('settings.browserCert.hint')}</span>
            <div class="sm-browser-cert-row">
              <input
                type="password"
                data-action="browser-cert-password"
                bind:value={browserCertPassword}
                placeholder={$t('settings.browserCert.passwordPlaceholder')}
              />
              <button
                class="btn ghost small"
                data-action="browser-cert-export"
                onclick={onExportBrowserCert}
                disabled={browserCertBusy}
              >
                {$t('settings.browserCert.export')}
              </button>
            </div>
            {#if browserCertMsg}<span class="sm-browser-cert-msg">{browserCertMsg}</span>{/if}
          </div>
        {/if}
      {/if}

      {#if mode === 'sync' || mode === 'server'}
        <!-- TLS trust applies to BOTH remote modes: server-mode login/enrollment
             reads this setting too, so it must not hide in the sync branch (the
             bootstrap against the standard own-PKI install depends on it). -->
        <label class="field checkbox">
          <input type="checkbox" bind:checked={allowSelfSignedCerts} />
          <span>{$t('settings.allowSelfSigned')}</span>
        </label>
        <div class="sm-reset-pin">
          <button class="btn ghost small" onclick={onResetPin}>{$t('settings.resetCertPin')}</button
          >
          <span class="field-label">{$t('settings.resetCertPin.hint')}</span>
          {#if pinResetMsgKey}<span class="sm-reset-msg">{$t(pinResetMsgKey)}</span>{/if}
        </div>
      {/if}

      {#if mode === 'server'}
        {#if deviceEnrolled}
          <div class="sm-reset-pin">
            <button
              class="btn ghost small danger"
              data-action="device-reset"
              onclick={onResetDeviceIdentity}>{$t('settings.resetDeviceId')}</button
            >
            <span class="field-label">{$t('settings.resetDeviceId.hint')}</span>
          </div>
        {:else}
          <div class="sm-enroll">
            <span class="field-label">{$t('settings.enroll.hint')}</span>
            <div class="sm-enroll-row">
              <input
                type="text"
                data-action="enroll-token"
                aria-label={$t('login.enroll.token')}
                bind:value={enrollToken}
                placeholder={$t('login.enroll.token.placeholder')}
                autocomplete="off"
              />
              <button
                class="btn ghost small"
                data-action="enroll-submit"
                onclick={onEnroll}
                disabled={enrollBusy}
              >
                {enrollBusy ? $t('login.enroll.working') : $t('login.enroll.submit')}
              </button>
            </div>
          </div>
        {/if}
        <!-- Outside the two branches: the reset message used to sit in the
             enrolled branch, which disappears the moment the reset succeeds. -->
        {#if deviceResetMsgKey}<span class="sm-reset-msg" data-msg="device-reset"
            >{$t(deviceResetMsgKey)}</span
          >{/if}
        {#if enrollMsg}<span class="sm-reset-msg" data-msg="enroll">{enrollMsg}</span>{/if}
      {/if}

      <div class="sm-section">
        <div class="sm-section-title">{$t('settings.section.language')}</div>
        <label class="field">
          <select bind:value={language}>
            <option value="de">Deutsch</option>
            <option value="en">English</option>
          </select>
        </label>
      </div>

      <div class="sm-section">
        <div class="sm-section-title">{$t('settings.section.passwords')}</div>
        <label class="field checkbox">
          <input type="checkbox" bind:checked={storePasswords} />
          <span>{$t('settings.storePasswords')}</span>
        </label>
      </div>

      <div class="sm-section">
        <div class="sm-section-title">{$t('settings.section.rdp')}</div>
        <label class="field">
          <span class="field-label">{$t('settings.rdp.scaling')}</span>
          <select bind:value={rdpScalingMode}>
            {#each RDP_SCALING_MODES as m (m)}
              <option value={m}>{rdpScalingLabel(m)}</option>
            {/each}
          </select>
        </label>
        <label class="field">
          <span class="field-label">{$t('settings.rdp.windowMode')}</span>
          <select bind:value={rdpWindowMode}>
            {#each RDP_WINDOW_MODES as m (m)}
              <option value={m}>{rdpWindowLabel(m)}</option>
            {/each}
          </select>
        </label>
        {#if rdpWindowMode === 'custom'}
          <label class="field">
            <span class="field-label">{$t('settings.rdp.customSize')}</span>
            <input
              type="text"
              bind:value={rdpCustomSize}
              placeholder={$t('settings.rdp.customSize.placeholder')}
            />
          </label>
        {/if}
        <label class="field">
          <span class="field-label">{$t('settings.rdp.performance')}</span>
          <select bind:value={rdpPerformanceProfile}>
            {#each RDP_PERFORMANCE_PROFILES as m (m)}
              <option value={m}>{rdpPerfLabel(m)}</option>
            {/each}
          </select>
        </label>
      </div>

      <div class="sm-section">
        <div class="sm-section-title">{$t('settings.section.notifications')}</div>
        <label class="field checkbox">
          <input
            type="checkbox"
            checked={osNotifications}
            onchange={(e) => onToggleOsNotifications(e.currentTarget.checked)}
          />
          <span>{$t('settings.osNotifications')}</span>
        </label>
        {#if $session}
          <NotificationPrefs />
        {:else}
          <span class="field-label">{$t('settings.notifications.serverOnly')}</span>
        {/if}
      </div>

      <div class="sm-section">
        <div class="sm-section-title">{$t('settings.section.diagnostics')}</div>
        <span class="field-label">{$t('settings.diagnostics.hint')}</span>
        <div>
          <button class="btn ghost small" onclick={onGenerateDiagnostics} disabled={diagBusy}>
            {$t('settings.diagnostics.create')}
          </button>
        </div>
        {#if diagMsg}<span class="sm-diag-msg">{diagMsg}</span>{/if}
      </div>

      <div class="panel-actions">
        <div style="flex: 1;"></div>
        <button class="btn" onclick={closeSettings}>{$t('action.cancel')}</button>
        <button class="btn primary" onclick={onSave}>{$t('action.save')}</button>
      </div>
    </div>
  </div>
{/if}

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
  .sm-section {
    display: flex;
    flex-direction: column;
    gap: var(--sp-2);
    margin-top: var(--sp-2);
  }
  .sm-section-title {
    font-size: 12px;
    color: var(--text-muted);
    text-transform: uppercase;
    letter-spacing: 0.5px;
  }
  .sm-radio-group {
    display: flex;
    gap: var(--sp-4);
    flex-wrap: wrap;
  }
  .sm-radio {
    display: flex;
    align-items: center;
    gap: var(--sp-2);
    cursor: pointer;
  }
  .field {
    display: flex;
    flex-direction: column;
    gap: var(--sp-2);
  }
  .field.checkbox {
    flex-direction: row;
    align-items: center;
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
  .sm-session-row {
    display: flex;
    align-items: center;
    gap: var(--sp-3);
    padding: var(--sp-2) 0;
  }
  .sm-reset-pin {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: var(--sp-2) var(--sp-3);
  }
  .sm-reset-msg {
    font-size: 12px;
    color: var(--accent);
  }
  .sm-reset-pin .btn.danger {
    color: var(--danger);
    border-color: var(--danger);
  }
  .sm-reset-pin .btn.danger:hover {
    color: var(--danger);
    border-color: var(--danger);
    background: rgba(248, 113, 113, 0.12);
  }
  .sm-browser-cert,
  .sm-enroll {
    display: flex;
    flex-direction: column;
    gap: var(--sp-2);
    padding-top: var(--sp-2);
  }
  .sm-browser-cert-row,
  .sm-enroll-row {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: var(--sp-2);
  }
  .sm-browser-cert-row input,
  .sm-enroll-row input {
    flex: 1;
    min-width: 180px;
    background: var(--bg-input, var(--bg-panel));
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    color: var(--text);
    padding: var(--sp-2) var(--sp-3);
    font-size: 13px;
    font-family: inherit;
  }
  .sm-browser-cert-row input:focus,
  .sm-enroll-row input:focus {
    outline: 1px solid var(--accent);
  }
  .sm-browser-cert-msg {
    font-size: 12px;
    color: var(--accent);
    word-break: break-all;
  }
  .sm-diag-msg {
    font-size: 12px;
    color: var(--accent);
    word-break: break-all;
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
