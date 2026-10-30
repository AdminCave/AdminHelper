<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import { settings, session } from '$lib/stores/session';
  import { reportError } from '$lib/stores/statusBar';
  import { errMsg } from '$lib/utils/errors';
  import {
    settingsModalOpen,
    closeSettings,
    saveSettings,
    logoutAndReload,
  } from '$lib/stores/settings';
  import { context, reloadContextForUrl } from '$lib/stores/workspace';
  import { t, currentLocale, resolveLanguage, type Language } from '$lib/i18n';
  import {
    resetServerCertPin,
    resetDeviceIdentity,
    isDeviceEnrolled,
    deviceIdentity,
    enrollWithToken,
    exportBrowserP12,
    generateDiagnostics,
  } from '$lib/bridge';
  import { startIfServerMode, stop as stopTunnel } from '$lib/stores/tunnel';
  import { save } from '@tauri-apps/plugin-dialog';
  import { confirmDialog } from './ui/ConfirmDialog.svelte';
  import {
    RDP_WINDOW_MODES,
    RDP_PERFORMANCE_PROFILES,
    RDP_SCALING_MODES,
    getSettingsDefaults,
    getIntervalMinutes,
  } from '$lib/models/settings';
  import type {
    DeviceIdentity,
    Settings,
    RdpWindowMode,
    RdpPerformanceProfile,
    RdpScalingMode,
  } from '$lib/bridge/types';
  import { ensureNotificationPermission } from '$lib/osNotify';
  import NotificationPrefs from './NotificationPrefs.svelte';

  // The kind of the workspace of this window: fixed, as are its name, colour and URL, which the
  // workspace list changes while the workspace is closed.
  let mode = $derived($settings?.mode ?? 'local');
  // Null only when the context of this window did not load.
  let workspace = $derived($context?.workspace ?? null);
  // Where a reset goes: the server signed in to, else the URL of the workspace as the window
  // shows it (Rust takes it for the one it keeps). Never the URL in the settings: after a save
  // Rust refused (a device identity, but no URL) they have none, and the reset is the way out.
  let resetTarget = $derived($session?.serverUrl ?? workspace?.url ?? '');
  let intervalMinutes = $state(1);
  let language = $state<Language>('de');
  let storePasswords = $state(false);
  let allowSelfSignedCerts = $state(false);
  let rdpScalingMode = $state<RdpScalingMode>('auto');
  let rdpWindowMode = $state<RdpWindowMode>('fit');
  let rdpCustomSize = $state('1920x1080');
  let rdpPerformanceProfile = $state<RdpPerformanceProfile>('auto');
  let osNotifications = $state(false);
  let pinResetMsgKey = $state('');
  let deviceEnrolled = $state(false);
  // null: no identity, so no line. 'unreadable': the stored certificate does not parse.
  let deviceIdentityState = $state<DeviceIdentity | 'unreadable' | null>(null);
  let deviceResetMsgKey = $state('');
  // The last reset deleted the identity here only: the server did not revoke it.
  let deviceResetLocal = $state(false);
  // The reset question sits in App's layer, outside this overlay, but the focus stays
  // on the reset button in here: its Escape reaches the overlay's handler before the
  // dialog's own and would close the settings under the question. A count, not a flag:
  // a second click replaces the open question, and the first one's end must not lift
  // the guard the second one holds.
  let asking = 0;
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
    intervalMinutes = getIntervalMinutes(s);
    language = resolveLanguage(s.language);
    storePasswords = Boolean(s.storePasswords);
    allowSelfSignedCerts = Boolean(s.allowSelfSignedCerts);
    rdpScalingMode = s.rdpScalingMode ?? 'auto';
    rdpWindowMode = s.rdpWindowMode ?? 'fit';
    rdpCustomSize = s.rdpCustomSize ?? '1920x1080';
    rdpPerformanceProfile = s.rdpPerformanceProfile ?? 'auto';
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
    void refreshDeviceIdentity();
  });

  async function refreshDeviceEnrolled(): Promise<void> {
    try {
      deviceEnrolled = await isDeviceEnrolled();
    } catch {
      deviceEnrolled = false;
    }
  }

  async function refreshDeviceIdentity(): Promise<void> {
    try {
      deviceIdentityState = await deviceIdentity();
    } catch {
      // A fixed line, never the command's error: that text is for the log.
      deviceIdentityState = 'unreadable';
    }
  }

  // Renewal runs at sign-in from half the lifetime on (RENEWAL_FRACTION in
  // enrollment.rs): a leaf this close to its end has been failing to renew for weeks.
  const IDENTITY_SOON_MS = 14 * 24 * 60 * 60 * 1000;

  let identityLine = $derived.by(() => {
    if (deviceIdentityState === null) return null;
    if (deviceIdentityState === 'unreadable') return { status: 'unreadable' as const };
    const notAfter = new Date(deviceIdentityState.notAfter);
    if (Number.isNaN(notAfter.getTime())) return { status: 'unreadable' as const };
    const left = notAfter.getTime() - Date.now();
    return {
      status:
        left < 0
          ? ('expired' as const)
          : left <= IDENTITY_SOON_MS
            ? ('soon' as const)
            : ('valid' as const),
      name: deviceIdentityState.name,
      date: notAfter.toLocaleDateString(currentLocale(), {
        day: '2-digit',
        month: '2-digit',
        year: 'numeric',
      }),
    };
  });

  async function onResetPin(): Promise<void> {
    const target = resetTarget;
    if (!target) {
      pinResetMsgKey = 'settings.resetCertPin.missingUrl';
      return;
    }
    // The same step as the pin reset on the login screen, so the same warning first.
    asking += 1;
    const ok = await confirmDialog($t('login.resetPin.confirmMitm'), {
      confirmLabel: $t('settings.resetCertPin'),
    });
    asking -= 1;
    if (!ok) return;
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
    const target = resetTarget;
    if (!target) {
      deviceResetMsgKey = 'settings.resetCertPin.missingUrl';
      return;
    }
    // Destructive: drops the mTLS device cert (re-enrollment required). Confirm
    // with an explicit danger warning before doing it.
    asking += 1;
    const ok = await confirmDialog($t('settings.resetDeviceId.confirm'), {
      confirmLabel: $t('settings.resetDeviceId'),
    });
    asking -= 1;
    if (!ok) return;
    try {
      const outcome = await resetDeviceIdentity(target);
      deviceEnrolled = false;
      void refreshDeviceIdentity();
      enrollMsg = '';
      deviceResetLocal = outcome === 'localOnly';
      deviceResetMsgKey = 'settings.resetDeviceId.done';
    } catch (err) {
      deviceResetMsgKey = '';
      // A failed reset may still have deleted the identity: show what is there now.
      void refreshDeviceEnrolled();
      void refreshDeviceIdentity();
      reportError(errMsg(err));
    }
  }

  async function onEnroll(): Promise<void> {
    const sess = $session;
    const token = enrollToken.trim();
    if (!sess || !token) return;
    enrollBusy = true;
    enrollMsg = '';
    deviceResetMsgKey = '';
    try {
      await enrollWithToken(sess.serverUrl, token, allowSelfSignedCerts);
      deviceEnrolled = true;
      void refreshDeviceIdentity();
      enrollToken = '';
      enrollMsg = $t('settings.enroll.done');
    } catch (err) {
      enrollMsg = errMsg(err);
      return;
    } finally {
      enrollBusy = false;
    }
    // A workspace without a URL took the one it registered at: the settings show it from now on.
    await reloadContextForUrl();
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
    if (!$session) return;
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
      const path = await exportBrowserP12(browserCertPassword, destPath);
      browserCertMsg = `${$t('settings.browserCert.done')} ${path}`;
      browserCertPassword = '';
    } catch (err) {
      browserCertMsg = `${$t('settings.browserCert.error')} ${errMsg(err)}`;
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

  async function onLogout(): Promise<void> {
    await logoutAndReload();
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
        {#if workspace}
          <div class="sm-workspace">
            <span class="workspace-dot" style:background={workspace.color} aria-hidden="true"
            ></span>
            <strong data-testid="settings-workspace-name">{workspace.name}</strong>
          </div>
          {#if mode !== 'local'}
            <div class="field">
              <span class="field-label"
                >{$t(mode === 'sync' ? 'settings.syncUrl' : 'settings.serverUrl')}</span
              >
              <span class="sm-workspace-url" data-testid="settings-workspace-url"
                >{workspace.url ?? $t('settings.workspace.noUrl')}</span
              >
            </div>
          {/if}
          <span class="field-label"
            >{$t(
              mode === 'local' ? 'settings.workspace.fixedLocal' : 'settings.workspace.fixed',
            )}</span
          >
        {/if}

        {#if mode === 'sync'}
          <label class="field">
            <span class="field-label">{$t('settings.interval')}</span>
            <input type="number" min="1" max="1440" bind:value={intervalMinutes} />
          </label>
        {:else if mode === 'server'}
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
            <button class="btn ghost small" data-action="pin-reset" onclick={onResetPin}
              >{$t('settings.resetCertPin')}</button
            >
            <span class="field-label">{$t('settings.resetCertPin.hint')}</span>
            {#if pinResetMsgKey}<span class="sm-reset-msg" data-msg="pin-reset"
                >{$t(pinResetMsgKey)}</span
              >{/if}
          </div>
        {/if}

        <!-- With a session only: without one an enrollment has no session URL and no
           tunnel to start. A sync workspace has no device identity (Rust refuses its reset). -->
        {#if mode === 'server' && $session}
          {#if deviceEnrolled}
            <!-- One inline sentence, not a flex row: a gap would tear the comma off the name. -->
            {#if identityLine}
              <div
                class="sm-identity-row"
                data-msg="device-identity"
                data-state={identityLine.status}
              >
                {#if identityLine.status === 'unreadable'}
                  {$t('settings.deviceIdentity.unreadable')}
                {:else if identityLine.status === 'expired'}
                  {$t('settings.deviceIdentity.enrolledAs')} <strong>{identityLine.name}</strong>,
                  {$t('settings.deviceIdentity.expired', { date: identityLine.date })}
                {:else}
                  {$t('settings.deviceIdentity.enrolledAs')} <strong>{identityLine.name}</strong>
                  {$t('settings.deviceIdentity.until', {
                    date: identityLine.date,
                  })}{#if identityLine.status === 'soon'},
                    <span class="sm-identity-soon">{$t('settings.deviceIdentity.expiresSoon')}</span
                    >{/if}
                {/if}
              </div>
            {/if}
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
              >{$t(
                deviceResetMsgKey,
              )}{#if deviceResetLocal && deviceResetMsgKey === 'settings.resetDeviceId.done'}
                <span data-msg="device-reset-local">{$t('settings.resetDeviceId.localOnly')}</span
                >{/if}</span
            >{/if}
          {#if enrollMsg}<span class="sm-reset-msg" data-msg="enroll">{enrollMsg}</span>{/if}
        {/if}

        {#if $session}
          <div class="sm-section">
            <div class="sm-section-title">{$t('settings.section.notificationRules')}</div>
            <NotificationPrefs />
          </div>
        {/if}
      </section>

      <section class="sm-group" data-group="device">
        <h3 class="sm-group-title">{$t('settings.group.device')}</h3>

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
  .sm-workspace {
    display: flex;
    align-items: center;
    gap: var(--sp-2);
  }
  /* A value inside .field, whose global rule styles labels: no caps, spacing or
     muted colour — paths and queries are case-sensitive. */
  .sm-workspace-url {
    font-size: 13px;
    text-transform: none;
    letter-spacing: normal;
    color: var(--text);
    word-break: break-all;
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
  .sm-identity-row {
    font-size: 12px;
    color: var(--text-muted);
    padding-top: var(--sp-2);
  }
  .sm-identity-row strong {
    color: var(--text);
  }
  .sm-identity-row[data-state='expired'],
  .sm-identity-row[data-state='unreadable'],
  .sm-identity-soon {
    color: var(--warning);
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
