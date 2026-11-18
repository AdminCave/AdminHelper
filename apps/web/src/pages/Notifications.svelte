<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import { onMount } from 'svelte';
  import { t } from '$lib/i18n';
  import { formatDateTime } from '$lib/utils/datetime';
  import { showToast, showError } from '$lib/stores/notifications';
  import * as notifyApi from '$lib/api/notify';
  import Button from '$lib/components/ui/Button.svelte';
  import Checkbox from '$lib/components/ui/Checkbox.svelte';
  import EmptyState from '$lib/components/ui/EmptyState.svelte';
  import FormField from '$lib/components/ui/FormField.svelte';
  import Input from '$lib/components/ui/Input.svelte';
  import Panel from '$lib/components/ui/Panel.svelte';
  import Select from '$lib/components/ui/Select.svelte';
  import { confirmDialog } from '$lib/components/ui/ConfirmDialog.svelte';
  import type {
    NotifyChannel,
    NotifyChannels,
    NotifyChannelsInput,
    NotifyTemplate,
    NotifyTemplateInput,
    NotifyTemplatePreview,
  } from '$lib/api/types';

  type PlainField = 'smtpHost' | 'smtpUser' | 'smtpFrom';

  // The server names fields in snake case in `sources` and `unreadable`.
  const SOURCE_KEY: Record<PlainField | 'smtpPort', string> = {
    smtpHost: 'smtp_host',
    smtpPort: 'smtp_port',
    smtpUser: 'smtp_user',
    smtpFrom: 'smtp_from',
  };
  const SECRET_LABEL: Record<string, string> = {
    smtp_password: 'page.notify.smtpPassword',
    telegram_token: 'page.notify.telegramToken',
  };

  let data = $state<NotifyChannels | null>(null);
  let loadFailed = $state(false);
  let saving = $state(false);
  let host = $state('');
  let port = $state('');
  let user = $state('');
  let from = $state('');
  let targets = $state('');
  // Secrets are write-only: the field starts empty, empty keeps the stored value.
  let password = $state('');
  let token = $state('');
  let clearPassword = $state(false);
  let clearToken = $state(false);

  let testChannel = $state<NotifyChannel>('email');
  let testTarget = $state('');
  let testing = $state(false);

  // Mirrors LOGO_MAX_BYTES of the server, so a large file fails before the upload.
  const LOGO_MAX_BYTES = 200 * 1024;

  let tpl = $state<NotifyTemplate | null>(null);
  let subjectPrefix = $state('');
  let fromName = $state('');
  let html = $state('');
  let text = $state('');
  let preview = $state<NotifyTemplatePreview | null>(null);
  let designSaving = $state(false);
  let previewing = $state(false);
  let logoBusy = $state(false);
  let designTarget = $state('');
  let designTesting = $state(false);

  const portError = $derived(
    port.trim() && !/^\d+$/.test(port.trim())
      ? $t('page.notify.portInvalid')
      : port.trim() && (Number(port) < 1 || Number(port) > 65535)
        ? $t('page.notify.portInvalid')
        : undefined,
  );
  const hostChanged = $derived(!!data && host.trim() !== (data.smtpHost ?? ''));

  onMount(() => {
    load();
  });

  function fill(d: NotifyChannels) {
    data = d;
    host = d.smtpHost ?? '';
    port = d.smtpPort === null ? '' : String(d.smtpPort);
    user = d.smtpUser ?? '';
    from = d.smtpFrom ?? '';
    targets = d.privateTargets ?? '';
    password = '';
    token = '';
    clearPassword = false;
    clearToken = false;
  }

  function fillTemplate(d: NotifyTemplate) {
    tpl = d;
    subjectPrefix = d.subjectPrefix;
    fromName = d.fromName;
    html = d.html;
    text = d.text;
    preview = null;
  }

  async function load() {
    try {
      const [channels, template] = await Promise.all([
        notifyApi.getChannels(),
        notifyApi.getTemplate(),
      ]);
      fillTemplate(template);
      fill(channels);
    } catch (err) {
      loadFailed = true;
      showError(err);
    }
  }

  // A hint for a field the panel leaves empty: what the .env puts in its place.
  function plainHint(d: NotifyChannels, field: PlainField | 'smtpPort'): string | undefined {
    if (d[field] !== null) return undefined;
    if (d.sources[SOURCE_KEY[field]] !== 'env') return $t('page.notify.notSet');
    return $t('page.notify.fromEnv', { value: String(d.effective[field]) });
  }

  function secretHint(d: NotifyChannels, stored: boolean, key: string): string | undefined {
    if (stored) return undefined;
    return d.sources[key] === 'env' ? $t('page.notify.fromEnvSecret') : $t('page.notify.notSet');
  }

  function targetsHint(d: NotifyChannels): string {
    const base = $t('page.notify.privateTargets.hint');
    if (d.privateTargets !== null || d.sources.private_targets !== 'env') return base;
    return `${base} ${$t('page.notify.fromEnv', { value: d.effective.privateTargets.join(', ') })}`;
  }

  function secretValue(value: string, clear: boolean): string | null {
    if (clear) return '';
    return value === '' ? null : value;
  }

  function payload(): NotifyChannelsInput {
    return {
      smtpHost: host.trim() || null,
      smtpPort: port.trim() ? Number(port) : null,
      smtpUser: user.trim() || null,
      smtpFrom: from.trim() || null,
      privateTargets: targets.trim() || null,
      smtpPassword: secretValue(password, clearPassword),
      telegramToken: secretValue(token, clearToken),
    };
  }

  async function save(e: SubmitEvent) {
    e.preventDefault();
    if (portError || saving) return;
    saving = true;
    try {
      fill(await notifyApi.saveChannels(payload()));
      showToast($t('page.notify.saved'));
    } catch (err) {
      showError(err);
    } finally {
      saving = false;
    }
  }

  function designPayload(): NotifyTemplateInput {
    return { subjectPrefix: subjectPrefix.trim(), fromName: fromName.trim(), html, text };
  }

  async function saveDesign(e: SubmitEvent) {
    e.preventDefault();
    if (designSaving) return;
    designSaving = true;
    try {
      fillTemplate(await notifyApi.saveTemplate(designPayload()));
      showToast($t('page.notify.design.saved'));
    } catch (err) {
      showError(err);
    } finally {
      designSaving = false;
    }
  }

  async function showPreview() {
    if (previewing) return;
    previewing = true;
    try {
      preview = await notifyApi.previewTemplate(designPayload());
    } catch (err) {
      showError(err);
    } finally {
      previewing = false;
    }
  }

  async function resetDesign() {
    if (!(await confirmDialog($t('page.notify.design.resetConfirm')))) return;
    try {
      fillTemplate(await notifyApi.resetTemplate());
      showToast($t('page.notify.design.resetDone'));
    } catch (err) {
      showError(err);
    }
  }

  function base64(bytes: Uint8Array): string {
    let bin = '';
    for (let i = 0; i < bytes.length; i += 0x8000) {
      bin += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
    }
    return btoa(bin);
  }

  async function uploadLogo(e: Event) {
    const input = e.currentTarget as HTMLInputElement;
    const file = input.files?.[0];
    input.value = '';
    if (!file || logoBusy) return;
    if (file.size > LOGO_MAX_BYTES) {
      showToast($t('page.notify.logo.tooLarge'), 'error');
      return;
    }
    logoBusy = true;
    try {
      const data = base64(new Uint8Array(await file.arrayBuffer()));
      tpl = await notifyApi.saveLogo({ data });
      preview = null;
      showToast($t('page.notify.logo.saved'));
    } catch (err) {
      showError(err);
    } finally {
      logoBusy = false;
    }
  }

  async function removeLogo() {
    if (logoBusy) return;
    logoBusy = true;
    try {
      tpl = await notifyApi.deleteLogo();
      preview = null;
      showToast($t('page.notify.logo.removed'));
    } catch (err) {
      showError(err);
    } finally {
      logoBusy = false;
    }
  }

  async function sendDesignTest(e: SubmitEvent) {
    e.preventDefault();
    if (!designTarget.trim() || designTesting) return;
    designTesting = true;
    try {
      await notifyApi.testTemplate({ target: designTarget.trim() });
      showToast($t('page.notify.test.sent', { channel: $t('page.notify.channel.email') }));
    } catch (err) {
      showError(err);
    } finally {
      designTesting = false;
    }
  }

  async function sendTest(e: SubmitEvent) {
    e.preventDefault();
    if (!testTarget.trim() || testing) return;
    testing = true;
    try {
      await notifyApi.testChannel({ channel: testChannel, target: testTarget.trim() });
      const label =
        testChannel === 'email'
          ? $t('page.notify.channel.email')
          : $t('page.notify.channel.telegram');
      showToast($t('page.notify.test.sent', { channel: label }));
    } catch (err) {
      showError(err);
    } finally {
      testing = false;
    }
  }
</script>

<div class="page active">
  <div class="page-header">
    <div>
      <div class="page-title">{$t('page.notify.title')}</div>
      <div class="page-subtitle">{$t('page.notify.subtitle')}</div>
    </div>
  </div>

  {#if !data || !tpl}
    <Panel pad={0}
      ><EmptyState
        framed={false}
        message={loadFailed ? $t('page.notify.loadFailed') : $t('page.notify.loading')}
      /></Panel
    >
  {:else}
    {#if data.unreadable.length}
      <div class="warn" role="alert">
        {$t('page.notify.unreadable', {
          fields: data.unreadable
            .map((f) => (SECRET_LABEL[f] ? $t(SECRET_LABEL[f]) : f))
            .join(', '),
        })}
      </div>
    {/if}

    <div class="stack">
      <Panel title={$t('page.notify.channels')}>
        <form class="form" onsubmit={save} data-section="channels">
          <div class="grid">
            <FormField label={$t('page.notify.smtpHost')} hint={plainHint(data, 'smtpHost')}>
              <Input bind:value={host} name="smtpHost" autocomplete="off" />
            </FormField>
            <FormField
              label={$t('page.notify.smtpPort')}
              hint={plainHint(data, 'smtpPort')}
              error={portError}
            >
              <Input bind:value={port} name="smtpPort" autocomplete="off" />
            </FormField>
            <FormField label={$t('page.notify.smtpUser')} hint={plainHint(data, 'smtpUser')}>
              <Input bind:value={user} name="smtpUser" autocomplete="off" />
            </FormField>
            <FormField
              label={$t('page.notify.smtpPassword')}
              hint={hostChanged && data.passwordSet && !password
                ? $t('page.notify.hostChange')
                : secretHint(data, data.passwordSet, 'smtp_password')}
            >
              <Input
                bind:value={password}
                type="password"
                name="smtpPassword"
                autocomplete="new-password"
                disabled={clearPassword}
                placeholder={data.passwordSet ? $t('page.notify.secretSet') : undefined}
              />
            </FormField>
            {#if data.passwordSet}
              <div class="clear">
                <Checkbox bind:checked={clearPassword} label={$t('page.notify.secretClear')} />
              </div>
            {/if}
            <FormField label={$t('page.notify.smtpFrom')} hint={plainHint(data, 'smtpFrom')}>
              <Input bind:value={from} name="smtpFrom" autocomplete="off" />
            </FormField>
            <FormField
              label={$t('page.notify.telegramToken')}
              hint={secretHint(data, data.tokenSet, 'telegram_token')}
            >
              <Input
                bind:value={token}
                type="password"
                name="telegramToken"
                autocomplete="new-password"
                disabled={clearToken}
                placeholder={data.tokenSet ? $t('page.notify.secretSet') : undefined}
              />
            </FormField>
            {#if data.tokenSet}
              <div class="clear">
                <Checkbox bind:checked={clearToken} label={$t('page.notify.secretClear')} />
              </div>
            {/if}
          </div>
          <FormField label={$t('page.notify.privateTargets')} hint={targetsHint(data)}>
            <Input bind:value={targets} name="privateTargets" multiline rows={2} />
          </FormField>
          <div class="foot">
            {#if data.updatedAt}
              <span class="meta">
                {$t('page.notify.updated', {
                  at: formatDateTime(data.updatedAt),
                  by: data.updatedBy ?? '–',
                })}
              </span>
            {/if}
            <Button type="submit" loading={saving} disabled={!!portError}>
              {$t('action.save')}
            </Button>
          </div>
        </form>
      </Panel>

      <Panel title={$t('page.notify.test')}>
        <form class="test" onsubmit={sendTest} data-section="channel-test">
          <FormField label={$t('page.notify.test.channel')}>
            <Select
              bind:value={testChannel}
              options={[
                { value: 'email', label: $t('page.notify.channel.email') },
                { value: 'telegram', label: $t('page.notify.channel.telegram') },
              ]}
            />
          </FormField>
          <FormField
            label={$t('page.notify.test.target')}
            hint={$t('page.notify.test.target.hint')}
          >
            <Input bind:value={testTarget} name="testTarget" autocomplete="off" />
          </FormField>
          <Button type="submit" variant="secondary" loading={testing} disabled={!testTarget.trim()}>
            {$t('page.notify.test.send')}
          </Button>
        </form>
      </Panel>

      <Panel title={$t('page.notify.design')}>
        <form class="form" onsubmit={saveDesign} data-section="design">
          <p class="meta">
            {$t('page.notify.design.hint', {
              list: tpl.placeholders.map((p) => `{{${p}}}`).join(' '),
            })}
          </p>
          <div class="grid">
            <FormField label={$t('page.notify.subjectPrefix')}>
              <Input bind:value={subjectPrefix} name="subjectPrefix" autocomplete="off" />
            </FormField>
            <FormField label={$t('page.notify.fromName')}>
              <Input bind:value={fromName} name="fromName" autocomplete="off" />
            </FormField>
          </div>
          <FormField label={$t('page.notify.html')} hint={$t('page.notify.html.hint')}>
            <Input bind:value={html} name="html" multiline rows={10} />
          </FormField>
          <FormField label={$t('page.notify.text')} hint={$t('page.notify.text.hint')}>
            <Input bind:value={text} name="text" multiline rows={5} />
          </FormField>
          <FormField label={$t('page.notify.logo')} hint={$t('page.notify.logo.hint')}>
            <div class="logo">
              <span>
                {tpl.logoSet
                  ? $t('page.notify.logo.set', { type: tpl.logoType ?? '' })
                  : $t('page.notify.logo.none')}
              </span>
              <label class="upload">
                {$t('page.notify.logo.upload')}
                <input
                  type="file"
                  accept="image/png,image/jpeg"
                  disabled={logoBusy}
                  onchange={uploadLogo}
                />
              </label>
              {#if tpl.logoSet}
                <Button variant="secondary" onclick={removeLogo} loading={logoBusy}>
                  {$t('page.notify.logo.remove')}
                </Button>
              {/if}
            </div>
          </FormField>
          <div class="foot">
            {#if tpl.updatedAt}
              <span class="meta">
                {$t('page.notify.updated', {
                  at: formatDateTime(tpl.updatedAt),
                  by: tpl.updatedBy ?? '–',
                })}
              </span>
            {/if}
            <Button variant="secondary" onclick={resetDesign}>
              {$t('page.notify.design.reset')}
            </Button>
            <Button variant="secondary" onclick={showPreview} loading={previewing}>
              {$t('page.notify.preview')}
            </Button>
            <Button type="submit" loading={designSaving}>{$t('action.save')}</Button>
          </div>
        </form>

        {#if preview}
          <div class="preview" data-section="preview">
            <dl>
              <dt>{$t('page.notify.preview.subject')}</dt>
              <dd>{preview.subject}</dd>
              <dt>{$t('page.notify.preview.from')}</dt>
              <dd>{preview.fromName || '–'}</dd>
            </dl>
            {#if preview.html !== null}
              <!-- The admin's HTML only ever renders here: an empty sandbox (no scripts, an
                   opaque origin), never {@html} in the page itself. -->
              <iframe
                class="frame"
                sandbox=""
                srcdoc={preview.html}
                title={$t('page.notify.preview.frame')}
              ></iframe>
            {:else}
              <p class="meta">{$t('page.notify.preview.noHtml')}</p>
            {/if}
            <div class="meta">{$t('page.notify.preview.text')}</div>
            <pre class="text">{preview.text}</pre>
          </div>
        {/if}

        <form class="test design-test" onsubmit={sendDesignTest} data-section="design-test">
          <FormField
            label={$t('page.notify.design.test.target')}
            hint={$t('page.notify.design.test.hint')}
          >
            <Input bind:value={designTarget} name="designTarget" autocomplete="off" />
          </FormField>
          <Button
            type="submit"
            variant="secondary"
            loading={designTesting}
            disabled={!designTarget.trim()}
          >
            {$t('page.notify.test.send')}
          </Button>
        </form>
      </Panel>
    </div>
  {/if}
</div>

<style>
  .form {
    display: flex;
    flex-direction: column;
    gap: 16px;
  }
  .grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
    gap: 16px;
  }
  .clear {
    display: flex;
    align-items: flex-end;
  }
  .foot {
    display: flex;
    align-items: center;
    justify-content: flex-end;
    gap: 16px;
  }
  .meta {
    color: var(--text-subtle);
    font-size: var(--text-sm);
  }
  .test {
    display: grid;
    grid-template-columns: minmax(140px, 200px) minmax(200px, 1fr) auto;
    align-items: end;
    gap: 16px;
  }
  .warn {
    margin-bottom: 16px;
    padding: 10px 14px;
    border: 1px solid var(--warning-border);
    border-radius: var(--radius-md);
    background: var(--warning-bg);
    color: var(--text);
    font-size: var(--text-sm);
  }
  .logo {
    display: flex;
    align-items: center;
    gap: 16px;
    flex-wrap: wrap;
  }
  .upload {
    cursor: pointer;
    color: var(--text);
    font-size: var(--text-sm);
    text-decoration: underline;
  }
  .upload input {
    display: block;
    margin-top: 4px;
  }
  .preview {
    display: flex;
    flex-direction: column;
    gap: 8px;
    margin-top: 16px;
  }
  .preview dl {
    display: grid;
    grid-template-columns: max-content 1fr;
    gap: 4px 12px;
    margin: 0;
    font-size: var(--text-sm);
  }
  .preview dd {
    margin: 0;
  }
  .frame {
    width: 100%;
    height: 360px;
    border: 1px solid var(--border);
    border-radius: var(--radius-md);
    background: #fff;
  }
  .text {
    margin: 0;
    padding: 10px 14px;
    border-radius: var(--radius-md);
    background: var(--surface-inset);
    white-space: pre-wrap;
    font-size: var(--text-sm);
  }
  .design-test {
    grid-template-columns: minmax(200px, 1fr) auto;
    margin-top: 16px;
  }
  .stack {
    display: flex;
    flex-direction: column;
    gap: 16px;
  }
</style>
