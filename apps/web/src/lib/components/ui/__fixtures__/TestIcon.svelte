<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  // Stands in for a Lucide icon component in tests: same size prop, visible marker.
  let { size = 24 }: { size?: number } = $props();
</script>

<svg data-testid="icon" data-size={size} width={size} height={size}></svg>
