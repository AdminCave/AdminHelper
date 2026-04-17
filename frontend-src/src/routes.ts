import type { Component } from 'svelte';
import Placeholder from './pages/Placeholder.svelte';
import Servers from './pages/Servers.svelte';
import Connections from './pages/Connections.svelte';

export const routes: Record<string, Component> = {
  '/connections': Connections,
  '/servers': Servers,
  '/users': Placeholder,
  '/apikeys': Placeholder,
  '/hooks': Placeholder,
  '/frp': Placeholder,
  '/ansible': Placeholder,
  '/monitoring': Placeholder,
  '*': Placeholder,
};
