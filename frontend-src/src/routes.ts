import type { Component } from 'svelte';
import Placeholder from './pages/Placeholder.svelte';

export const routes: Record<string, Component> = {
  '/connections': Placeholder,
  '/servers': Placeholder,
  '/users': Placeholder,
  '/apikeys': Placeholder,
  '/hooks': Placeholder,
  '/frp': Placeholder,
  '/ansible': Placeholder,
  '/monitoring': Placeholder,
  '*': Placeholder,
};
