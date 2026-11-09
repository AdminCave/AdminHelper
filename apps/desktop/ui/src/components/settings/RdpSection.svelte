<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import { t } from '$lib/i18n';
  import {
    RDP_WINDOW_MODES,
    RDP_PERFORMANCE_PROFILES,
    RDP_SCALING_MODES,
    runsOnLinux,
  } from '$lib/models/settings';
  import { OPENH264_LICENSE, OPENH264_NOTICE } from '$lib/models/openh264';
  import type {
    RdpClient,
    RdpWindowMode,
    RdpPerformanceProfile,
    RdpScalingMode,
  } from '$lib/bridge/types';

  interface Props {
    rdpClient: RdpClient;
    rdpScalingMode: RdpScalingMode;
    rdpWindowMode: RdpWindowMode;
    rdpCustomSize: string;
    rdpPerformanceProfile: RdpPerformanceProfile;
    rdpH264: boolean;
    /** Shows the H.264 switch; the platform the app runs on unless a test sets it. */
    linux?: boolean;
  }

  let {
    rdpClient = $bindable(),
    rdpScalingMode = $bindable(),
    rdpWindowMode = $bindable(),
    rdpCustomSize = $bindable(),
    rdpPerformanceProfile = $bindable(),
    rdpH264 = $bindable(),
    linux = runsOnLinux(),
  }: Props = $props();

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
</script>

<div class="sm-section">
  <div class="sm-section-title">{$t('settings.section.rdp')}</div>
  <label class="field">
    <span class="field-label">{$t('settings.rdp.client')}</span>
    <select data-field="rdp-client" bind:value={rdpClient}>
      <option value="os">{$t('settings.rdp.client.os')}</option>
      <option value="embedded">{$t('settings.rdp.client.embedded')}</option>
    </select>
  </label>
  <label class="field">
    <span class="field-label">{$t('settings.rdp.scaling')}</span>
    <select bind:value={rdpScalingMode}>
      {#each RDP_SCALING_MODES as m (m)}
        <option value={m}>{rdpScalingLabels[m]}</option>
      {/each}
    </select>
  </label>
  <label class="field">
    <span class="field-label">{$t('settings.rdp.windowMode')}</span>
    <select bind:value={rdpWindowMode}>
      {#each RDP_WINDOW_MODES as m (m)}
        <option value={m}>{rdpWindowLabels[m]}</option>
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
        <option value={m}>{rdpPerfLabels[m]}</option>
      {/each}
    </select>
  </label>
  {#if linux}
    <label class="field checkbox">
      <input type="checkbox" data-field="rdp-h264" bind:checked={rdpH264} />
      <span>{$t('settings.rdp.h264')}</span>
    </label>
    <p class="h264-note">{$t('settings.rdp.h264.hint')}</p>
    <!-- Cisco's condition 3: this exact text where the binary is turned on and off. -->
    <p class="h264-note" data-field="openh264-notice">{OPENH264_NOTICE}</p>
    <details class="h264-license">
      <summary>{$t('settings.rdp.h264.license')}</summary>
      <pre data-field="openh264-license">{OPENH264_LICENSE}</pre>
    </details>
  {/if}
</div>

<style>
  .h264-note {
    margin: 0.25rem 0 0.5rem;
    font-size: 0.85em;
    color: var(--text-muted);
  }
  .h264-license summary {
    cursor: pointer;
    font-size: 0.85em;
  }
  .h264-license pre {
    max-height: 16rem;
    overflow: auto;
    white-space: pre-wrap;
    font-size: 0.8em;
  }
</style>
