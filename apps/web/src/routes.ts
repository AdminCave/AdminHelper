// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

import type { RouteDef } from '$lib/routeGuard';
import Placeholder from './pages/Placeholder.svelte';
import Users from './pages/Users.svelte';
import ApiKeys from './pages/ApiKeys.svelte';
import Hooks from './pages/Hooks.svelte';
import Frp from './pages/Frp.svelte';
import Audit from './pages/Audit.svelte';

export const routes: Record<string, RouteDef> = {
  '/users': { component: Users, adminOnly: true },
  '/apikeys': { component: ApiKeys, adminOnly: true },
  '/hooks': { component: Hooks, adminOnly: true },
  '/frp': { component: Frp, adminOnly: true },
  '/audit': { component: Audit, adminOnly: true },
  '*': { component: Placeholder },
};
