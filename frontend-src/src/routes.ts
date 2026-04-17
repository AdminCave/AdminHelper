import type { Component } from 'svelte';
import Placeholder from './pages/Placeholder.svelte';
import Servers from './pages/Servers.svelte';
import Connections from './pages/Connections.svelte';
import Users from './pages/Users.svelte';
import ApiKeys from './pages/ApiKeys.svelte';
import Hooks from './pages/Hooks.svelte';
import Ansible from './pages/Ansible.svelte';
import Frp from './pages/Frp.svelte';

export const routes: Record<string, Component> = {
  '/connections': Connections,
  '/servers': Servers,
  '/users': Users,
  '/apikeys': ApiKeys,
  '/hooks': Hooks,
  '/frp': Frp,
  '/ansible': Ansible,
  '/monitoring': Placeholder,
  '*': Placeholder,
};
