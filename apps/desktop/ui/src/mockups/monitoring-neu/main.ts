// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Entry of mockup.html (dev server only, never part of `vite build`).
import { mount } from 'svelte';
import '@fontsource-variable/geist';
import '@fontsource-variable/geist-mono';
import '../../styles/global.css';
import MockupApp from './MockupApp.svelte';

const target = document.getElementById('app');
if (!target) throw new Error('#app element not found');

export default mount(MockupApp, { target });
