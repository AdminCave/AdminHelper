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
  } from '$lib/models/settings';
  import type { RdpWindowMode, RdpPerformanceProfile, RdpScalingMode } from '$lib/bridge/types';

  interface Props {
    rdpScalingMode: RdpScalingMode;
    rdpWindowMode: RdpWindowMode;
    rdpCustomSize: string;
    rdpPerformanceProfile: RdpPerformanceProfile;
  }

  let {
    rdpScalingMode = $bindable(),
    rdpWindowMode = $bindable(),
    rdpCustomSize = $bindable(),
    rdpPerformanceProfile = $bindable(),
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
</div>
