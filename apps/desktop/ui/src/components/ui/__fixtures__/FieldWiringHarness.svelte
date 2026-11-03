<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<!-- Controls that FormField wires by context, apart from the bound-state harness. -->
<script lang="ts">
  import Checkbox from '../Checkbox.svelte';
  import FormField from '../FormField.svelte';
  import RadioGroup from '../RadioGroup.svelte';
  import SearchField from '../SearchField.svelte';
  import Switch from '../Switch.svelte';
</script>

<FormField label="Begriff" hint="Filtert die Liste">
  <SearchField />
</FormField>
<FormField label="Bedingungen" hint="Bitte lesen">
  <Checkbox />
</FormField>
<FormField hint="Ohne Beschriftung">
  <Switch />
</FormField>
<FormField label="Art">
  <RadioGroup options={['a', 'b']} />
</FormField>
