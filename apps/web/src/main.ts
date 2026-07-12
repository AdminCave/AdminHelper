// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

import '@fontsource-variable/geist';
import '@fontsource-variable/geist-mono';
import './styles/global.css';
import { mount } from 'svelte';
import App from './App.svelte';

const target = document.getElementById('app');
if (!target) {
  throw new Error('#app mount target missing in index.html');
}

const app = mount(App, { target });
export default app;
