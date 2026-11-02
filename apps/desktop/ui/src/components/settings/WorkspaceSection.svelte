<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import { session } from '$lib/stores/session';
  import { reportError } from '$lib/stores/statusBar';
  import { errMsg } from '$lib/utils/errors';
  import { logoutAndReload } from '$lib/stores/settings';
  import { t } from '$lib/i18n';
  import { resetServerCertPin, exportBrowserP12 } from '$lib/bridge';
  import { save } from '@tauri-apps/plugin-dialog';
  import type { SyncMode, WorkspaceInfo } from '$lib/bridge/types';

  interface Props {
    mode: SyncMode;
    workspace: WorkspaceInfo | null;
    resetTarget: string;
    ask: (message: string, confirmLabel: string) => Promise<boolean>;
    intervalMinutes: number;
    allowSelfSignedCerts: boolean;
  }

  let {
    mode,
    workspace,
    resetTarget,
    ask,
    intervalMinutes = $bindable(),
    allowSelfSignedCerts = $bindable(),
  }: Props = $props();

  let pinResetMsgKey = $state('');
  let browserCertPassword = $state('');
  let browserCertMsg = $state('');
  let browserCertBusy = $state(false);

  async function onResetPin(): Promise<void> {
    const target = resetTarget;
    if (!target) {
      pinResetMsgKey = 'settings.resetCertPin.missingUrl';
      return;
    }
    // The same step as the pin reset on the login screen, so the same warning first.
    if (!(await ask($t('login.resetPin.confirmMitm'), $t('settings.resetCertPin')))) return;
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
</script>

{#if workspace}
  <div class="sm-workspace">
    <span class="workspace-dot" style:background={workspace.color} aria-hidden="true"></span>
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
    >{$t(mode === 'local' ? 'settings.workspace.fixedLocal' : 'settings.workspace.fixed')}</span
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
      <button class="btn ghost small" onclick={() => logoutAndReload()}
        >{$t('settings.logout')}</button
      >
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
    {#if pinResetMsgKey}<span class="sm-reset-msg" data-msg="pin-reset">{$t(pinResetMsgKey)}</span
      >{/if}
  </div>
{/if}

<style>
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
  .sm-session-row {
    display: flex;
    align-items: center;
    gap: var(--sp-3);
    padding: var(--sp-2) 0;
  }
  .sm-browser-cert {
    display: flex;
    flex-direction: column;
    gap: var(--sp-2);
    padding-top: var(--sp-2);
  }
  .sm-browser-cert-row {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: var(--sp-2);
  }
  .sm-browser-cert-row input {
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
  .sm-browser-cert-row input:focus {
    outline: 1px solid var(--accent);
  }
  .sm-browser-cert-msg {
    font-size: 12px;
    color: var(--accent);
    word-break: break-all;
  }
</style>
