<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel

SPDX-License-Identifier: GPL-3.0-or-later
-->

<script lang="ts">
  import { path } from '$lib/router';
  import { isAdmin } from '$lib/stores/auth';
  import { resolveRoute, type RouteDef } from '$lib/routeGuard';

  interface Props {
    routes: Record<string, RouteDef>;
  }

  let { routes }: Props = $props();

  // Enforce the route's authorization: a non-admin hitting an admin-only route
  // gets the catch-all page, not the mounted admin page.
  const matched = $derived(resolveRoute(routes, $path, $isAdmin));
</script>

{#if matched}
  {@const C = matched.component}
  <C />
{/if}
