<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<!-- Binds every form control to local state, so tests see what bind: writes back. -->
<script lang="ts">
  import Checkbox from '../Checkbox.svelte';
  import FormField from '../FormField.svelte';
  import Input from '../Input.svelte';
  import RadioGroup from '../RadioGroup.svelte';
  import SearchField from '../SearchField.svelte';
  import Select from '../Select.svelte';
  import Slider from '../Slider.svelte';
  import Switch from '../Switch.svelte';

  let text = $state('a');
  let q = $state('');
  let sel = $state('');
  let on = $state(false);
  let ok = $state(false);
  let mode = $state('x');
  let num = $state(10);
</script>

<FormField label="Name" hint="Pflichtfeld" error={text === '' ? 'leer' : undefined} required>
  <Input bind:value={text} />
</FormField>
<SearchField bind:value={q} shortcut="⌘K" label="Suche" />
<FormField label="Farbe">
  <Select bind:value={sel} options={['rot', { value: 'b', label: 'blau' }]} />
</FormField>
<Switch bind:checked={on} label="Aktiv" />
<Checkbox bind:checked={ok} label="Zustimmen" description="Pflicht" />
<FormField label="Modus">
  <RadioGroup
    bind:value={mode}
    options={['x', { value: 'y', label: 'y', description: 'zweite' }]}
  />
</FormField>
<Slider bind:value={num} label="Wert" showValue suffix="%" />
<output data-testid="state">{JSON.stringify({ text, q, sel, on, ok, mode, num })}</output>
