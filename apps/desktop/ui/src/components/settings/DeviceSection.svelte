<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import { onMount } from 'svelte';
  import { session } from '$lib/stores/session';
  import { reportError } from '$lib/stores/statusBar';
  import { errMsg } from '$lib/utils/errors';
  import { reloadContextForUrl } from '$lib/stores/workspace';
  import { t, currentLocale } from '$lib/i18n';
  import {
    resetDeviceIdentity,
    isDeviceEnrolled,
    deviceIdentity,
    enrollWithToken,
  } from '$lib/bridge';
  import { startIfServerMode, stop as stopTunnel } from '$lib/stores/tunnel';
  import type { DeviceIdentity, SyncMode } from '$lib/bridge/types';

  interface Props {
    mode: SyncMode;
    resetTarget: string;
    // The trust setting as the dialog holds it, unsaved: the enrollment goes out with it.
    allowSelfSignedCerts: boolean;
    ask: (message: string, confirmLabel: string) => Promise<boolean>;
  }

  let { mode, resetTarget, allowSelfSignedCerts, ask }: Props = $props();

  let deviceEnrolled = $state(false);
  // null: no identity, so no line. 'unreadable': the stored certificate does not parse.
  let deviceIdentityState = $state<DeviceIdentity | 'unreadable' | null>(null);
  let deviceResetMsgKey = $state('');
  // The last reset deleted the identity here only: the server did not revoke it.
  let deviceResetLocal = $state(false);
  let enrollToken = $state('');
  let enrollMsg = $state('');
  let enrollBusy = $state(false);

  // Read on every opening, in every mode, as the dialog did before its split.
  onMount(() => {
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

  async function onResetDeviceIdentity(): Promise<void> {
    const target = resetTarget;
    if (!target) {
      deviceResetMsgKey = 'settings.resetCertPin.missingUrl';
      return;
    }
    // Destructive: drops the mTLS device cert (re-enrollment required). Confirm
    // with an explicit danger warning before doing it.
    if (!(await ask($t('settings.resetDeviceId.confirm'), $t('settings.resetDeviceId')))) return;
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
</script>

<!-- With a session only: without one an enrollment has no session URL and no
   tunnel to start. A sync workspace has no device identity (Rust refuses its reset). -->
{#if mode === 'server' && $session}
  {#if deviceEnrolled}
    <!-- One inline sentence, not a flex row: a gap would tear the comma off the name. -->
    {#if identityLine}
      <div class="sm-identity-row" data-msg="device-identity" data-state={identityLine.status}>
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
            <span class="sm-identity-soon">{$t('settings.deviceIdentity.expiresSoon')}</span>{/if}
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

<style>
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
  .sm-reset-pin .btn.danger {
    color: var(--danger);
    border-color: var(--danger);
  }
  .sm-reset-pin .btn.danger:hover {
    color: var(--danger);
    border-color: var(--danger);
    background: rgba(248, 113, 113, 0.12);
  }
  .sm-enroll {
    display: flex;
    flex-direction: column;
    gap: var(--sp-2);
    padding-top: var(--sp-2);
  }
  .sm-enroll-row {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: var(--sp-2);
  }
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
  .sm-enroll-row input:focus {
    outline: 1px solid var(--accent);
  }
</style>
