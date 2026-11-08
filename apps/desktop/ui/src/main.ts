// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

import { mount } from 'svelte';
import App from './App.svelte';
import { registerConnectionsSync } from '$lib/stores/session';
import { reloadForMode, clearInMemory } from '$lib/stores/connections';
import { closeAllTerminals, detachedRdpRoute, detachedRoute } from '$lib/stores/terminals';
import DetachedRdp from './components/terminal/DetachedRdp.svelte';
import DetachedTerminal from './components/terminal/DetachedTerminal.svelte';
import '@fontsource-variable/geist';
import '@fontsource-variable/geist-mono';
import './styles/global.css';

const target = document.getElementById('app');
if (!target) {
  throw new Error('#app element not found');
}

// A window a session is detached into (R-1070, R-1101) shows that session only, and ends none.
const detached = detachedRoute(window.location.hash);
const detachedRdp = detachedRdpRoute(window.location.hash);

function mountApp(target: HTMLElement) {
  // Wire the session store to the connections store here (a leaf module) so the
  // two stores don't import each other. Must run before the app mounts, i.e.
  // before any login/logout can fire.
  registerConnectionsSync({ reload: reloadForMode, clear: clearInMemory });

  // A reload leaves the programs of the terminal tabs running in Rust, and the UI starts without
  // tabs: end them. Outside Tauri there are none, and the call fails.
  void closeAllTerminals().catch(() => {});

  return mount(App, { target });
}

function mountWindow(target: HTMLElement) {
  if (detached !== null) return mount(DetachedTerminal, { target, props: { id: detached } });
  if (detachedRdp !== null) return mount(DetachedRdp, { target, props: detachedRdp });
  return mountApp(target);
}

const app = mountWindow(target);

export default app;
