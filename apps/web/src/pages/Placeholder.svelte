<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  interface Props {
    params?: { page?: string };
  }
  let { params }: Props = $props();
  const page = $derived(params?.page ?? 'page');
</script>

<div class="page active">
  <div class="page-header">
    <div>
      <div class="page-title">{page}</div>
      <div class="page-subtitle">Wird in einer spaeteren Phase migriert.</div>
    </div>
  </div>
  <div class="panel" style="padding:24px">
    <p>Diese Seite ist noch nicht auf Svelte portiert.</p>
  </div>
</div>
