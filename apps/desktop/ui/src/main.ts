// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

import { mount } from 'svelte';
import App from './App.svelte';
import { registerConnectionsSync } from '$lib/stores/session';
import { reloadForMode, clearInMemory } from '$lib/stores/connections';
import '@fontsource-variable/geist';
import '@fontsource-variable/geist-mono';
import './styles/global.css';

// Wire the session store to the connections store here (a leaf module) so the
// two stores don't import each other. Must run before the app mounts, i.e.
// before any login/logout can fire.
registerConnectionsSync({ reload: reloadForMode, clear: clearInMemory });

const target = document.getElementById('app');
if (!target) {
  throw new Error('#app element not found');
}

const app = mount(App, { target });

export default app;
