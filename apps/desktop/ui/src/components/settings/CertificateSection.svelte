<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import { session } from '$lib/stores/session';
  import { reportError } from '$lib/stores/statusBar';
  import { errMsg } from '$lib/utils/errors';
  import { t } from '$lib/i18n';
  import { resetServerCertPin, exportBrowserP12 } from '$lib/bridge';
  import { save } from '@tauri-apps/plugin-dialog';
  import type { SyncMode } from '$lib/bridge/types';
  import ScopePill from './ScopePill.svelte';

  interface Props {
    mode: SyncMode;
    resetTarget: string;
    ask: (message: string, confirmLabel: string) => Promise<boolean>;
  }

  let { mode, resetTarget, ask }: Props = $props();

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

{#if mode === 'sync' || mode === 'server'}
  <div class="sm-section" data-scope="workspace">
    <div class="sm-section-title">{$t('settings.section.certificates')} <ScopePill /></div>
    {#if mode === 'server' && $session}
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
    <div class="sm-reset-pin">
      <button class="btn ghost small" data-action="pin-reset" onclick={onResetPin}
        >{$t('settings.resetCertPin')}</button
      >
      <span class="field-label">{$t('settings.resetCertPin.hint')}</span>
      {#if pinResetMsgKey}<span class="sm-reset-msg" data-msg="pin-reset">{$t(pinResetMsgKey)}</span
        >{/if}
    </div>
  </div>
{/if}

<style>
  .sm-browser-cert {
    display: flex;
    flex-direction: column;
    gap: var(--sp-2);
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
