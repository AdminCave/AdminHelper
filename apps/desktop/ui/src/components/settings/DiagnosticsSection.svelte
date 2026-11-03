<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import { t } from '$lib/i18n';
  import { generateDiagnostics } from '$lib/bridge';

  let diagBusy = $state(false);
  let diagMsg = $state('');

  async function onGenerate(): Promise<void> {
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
</script>

<div class="sm-section">
  <div class="sm-section-title">{$t('settings.section.diagnostics')}</div>
  <span class="field-label">{$t('settings.diagnostics.hint')}</span>
  <div>
    <button class="btn ghost small" onclick={onGenerate} disabled={diagBusy}>
      {$t('settings.diagnostics.create')}
    </button>
  </div>
  {#if diagMsg}<span class="sm-diag-msg">{diagMsg}</span>{/if}
</div>

<style>
  .sm-diag-msg {
    font-size: 12px;
    color: var(--accent);
    word-break: break-all;
  }
</style>
