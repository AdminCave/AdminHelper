// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

import { writable, derived, get } from 'svelte/store';
import type { User } from '$lib/api/types';
import { getAccessToken, registerAuthFailureHandler } from '$lib/api/client';
import * as authApi from '$lib/api/auth';

interface AuthState {
  user: User | null;
  ready: boolean;
}

const initial: AuthState = { user: null, ready: false };
const _auth = writable<AuthState>(initial);

export const auth = {
  subscribe: _auth.subscribe,

  async hydrate(): Promise<void> {
    if (!getAccessToken()) {
      _auth.set({ user: null, ready: true });
      return;
    }
    try {
      const user = await authApi.me();
      _auth.set({ user, ready: true });
    } catch {
      authApi.logout();
      _auth.set({ user: null, ready: true });
    }
  },

  async login(username: string, password: string): Promise<void> {
    const user = await authApi.login(username, password);
    _auth.set({ user, ready: true });
  },

  logout(): void {
    authApi.logout();
    _auth.set({ user: null, ready: true });
  },
};

export const currentUser = derived(_auth, ($a) => $a.user);
export const isAuthenticated = derived(_auth, ($a) => $a.user !== null);
export const isAdmin = derived(_auth, ($a) => $a.user?.is_admin ?? false);

registerAuthFailureHandler(() => {
  authApi.logout();
  _auth.set({ user: null, ready: true });
});

export function requireUser(): User {
  const state = get(_auth);
  if (!state.user) throw new Error('Not authenticated');
  return state.user;
}
