<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import type { Snippet } from 'svelte';
  import { setField } from './field';

  interface Props {
    label?: string;
    // Id of the control; generated when the page does not need to know it.
    id?: string;
    required?: boolean;
    hint?: string;
    // Replaces the hint and marks the control invalid.
    error?: string;
    children: Snippet;
  }

  const uid = $props.id();
  let { label, id = `${uid}-control`, required = false, hint, error, children }: Props = $props();

  const labelId = `${uid}-label`;
  const msgId = `${uid}-msg`;

  setField({
    get id() {
      return id;
    },
    labelId,
    get describedBy() {
      return error || hint ? msgId : undefined;
    },
    get invalid() {
      return !!error;
    },
  });
</script>

<div class="field">
  {#if label}
    <label class="label" id={labelId} for={id}>
      {label}
      {#if required}<span class="req" aria-hidden="true">*</span>{/if}
    </label>
  {/if}
  {@render children()}
  {#if error}
    <span class="msg error" id={msgId}>{error}</span>
  {:else if hint}
    <span class="msg" id={msgId}>{hint}</span>
  {/if}
</div>

<style>
  .field {
    display: flex;
    flex-direction: column;
    gap: 7px;
    min-width: 0;
  }
  .label {
    display: flex;
    align-items: center;
    gap: 4px;
    color: var(--text);
    font-size: var(--text-sm);
    font-weight: 500;
  }
  .req {
    color: var(--accent);
  }
  .msg {
    color: var(--text-subtle);
    font-size: var(--text-sm);
  }
  .error {
    color: var(--danger);
  }
</style>
