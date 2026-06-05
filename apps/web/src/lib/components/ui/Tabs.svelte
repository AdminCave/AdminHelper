<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts" generics="T extends string">
  interface TabDef {
    id: T;
    label: string;
  }

  interface Props {
    tabs: TabDef[];
    active: T;
    onChange: (id: T) => void;
  }

  let { tabs, active, onChange }: Props = $props();
</script>

<div class="tabs" role="tablist">
  {#each tabs as tab (tab.id)}
    <button
      type="button"
      class="tab"
      class:active={active === tab.id}
      role="tab"
      aria-selected={active === tab.id}
      onclick={() => onChange(tab.id)}
    >
      {tab.label}
    </button>
  {/each}
</div>
