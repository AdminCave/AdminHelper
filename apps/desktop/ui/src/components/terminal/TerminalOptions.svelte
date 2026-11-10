<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<!--
  The options of the embedded terminal (R-1069) as a form: in the panel of a terminal, where each
  change is saved at once (onChange), and in the settings, which save them with the rest.
-->
<script lang="ts">
  import { currentLocale, t } from '$lib/i18n';
  import type { TerminalCursor, TerminalPrefs, TerminalTheme } from '$lib/bridge/types';
  import { TERMINAL_FONT_SIZE, TERMINAL_SCROLLBACKS } from '$lib/models/settings';
  import FormField from '../ui/FormField.svelte';
  import Segmented from '../ui/Segmented.svelte';
  import Select from '../ui/Select.svelte';
  import Slider from '../ui/Slider.svelte';
  import Switch from '../ui/Switch.svelte';

  interface Props {
    prefs: TerminalPrefs;
    /** Each change as it is made, with all options. */
    onChange?: (prefs: TerminalPrefs) => void;
  }

  let { prefs = $bindable(), onChange }: Props = $props();

  let themes = $derived([
    { value: 'cave', label: $t('terminal.options.theme.cave') },
    { value: 'contrast', label: $t('terminal.options.theme.contrast') },
    { value: 'light', label: $t('terminal.options.theme.light') },
  ]);
  let cursors = $derived([
    { value: 'block', label: $t('terminal.options.cursor.block') },
    { value: 'bar', label: $t('terminal.options.cursor.bar') },
    { value: 'underline', label: $t('terminal.options.cursor.underline') },
  ]);
  let scrollbacks = $derived(
    TERMINAL_SCROLLBACKS.map((n) => ({
      value: String(n),
      label: $t('terminal.options.lines', { n: n.toLocaleString(currentLocale()) }),
    })),
  );

  function set<K extends keyof TerminalPrefs>(key: K, value: TerminalPrefs[K]): void {
    prefs = { ...prefs, [key]: value };
    onChange?.(prefs);
  }
</script>

<div class="term-options">
  <span class="eyebrow">{$t('terminal.options.appearance')}</span>
  <Slider
    value={prefs.fontSize}
    min={TERMINAL_FONT_SIZE.min}
    max={TERMINAL_FONT_SIZE.max}
    label={$t('terminal.options.fontSize')}
    showValue
    suffix=" px"
    onChange={(v) => set('fontSize', v)}
  />
  <div class="term-options-group">
    <span class="term-options-label">{$t('terminal.options.theme')}</span>
    <Segmented
      options={themes}
      value={prefs.theme}
      label={$t('terminal.options.theme')}
      onChange={(v) => set('theme', v as TerminalTheme)}
    />
  </div>
  <div class="term-options-group">
    <span class="term-options-label">{$t('terminal.options.cursor')}</span>
    <Segmented
      options={cursors}
      value={prefs.cursor}
      label={$t('terminal.options.cursor')}
      onChange={(v) => set('cursor', v as TerminalCursor)}
    />
  </div>

  <span class="eyebrow">{$t('terminal.options.behaviour')}</span>
  <Switch
    size="sm"
    checked={prefs.copyOnSelect}
    label={$t('terminal.options.copyOnSelect')}
    onChange={(v) => set('copyOnSelect', v)}
  />
  <Switch
    size="sm"
    checked={prefs.rightClickPaste}
    label={$t('terminal.options.rightClickPaste')}
    onChange={(v) => set('rightClickPaste', v)}
  />
  <Switch
    size="sm"
    checked={prefs.confirmClose}
    label={$t('terminal.options.confirmClose')}
    onChange={(v) => set('confirmClose', v)}
  />
  <Switch
    size="sm"
    checked={prefs.confirmMultilinePaste}
    label={$t('terminal.options.confirmMultilinePaste')}
    onChange={(v) => set('confirmMultilinePaste', v)}
  />
  <FormField label={$t('terminal.options.scrollback')}>
    <Select
      size="sm"
      fullWidth
      value={String(prefs.scrollback)}
      options={scrollbacks}
      onChange={(v) => set('scrollback', Number(v))}
    />
  </FormField>
</div>

<style>
  .term-options {
    display: flex;
    flex-direction: column;
    gap: 14px;
  }
  .term-options .eyebrow:not(:first-child) {
    margin-top: 6px;
  }
  .term-options-group {
    display: flex;
    flex-direction: column;
    gap: 6px;
    align-items: flex-start;
  }
  .term-options-label {
    font-size: 12px;
    color: var(--text-muted);
  }
</style>
