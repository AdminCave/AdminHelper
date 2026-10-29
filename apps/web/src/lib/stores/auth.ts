// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

import { writable, derived, get } from 'svelte/store';
import { ApiError, type User } from '$lib/api/types';
import { restoreSession, registerAuthFailureHandler } from '$lib/api/client';
import * as authApi from '$lib/api/auth';
import { users } from './users';
import { hooks } from './hooks';
import { apikeys } from './apikeys';
import { frpConfig } from './frp';

interface AuthState {
  user: User | null;
  ready: boolean;
}

const initial: AuthState = { user: null, ready: false };
const _auth = writable<AuthState>(initial);

// authApi.logout() clears the access token only once the server answered, and that answer's
// Set-Cookie deletes the refresh cookie. Landing after a new login, it would end the new session;
// so login() waits for the logout still in flight.
let pendingLogout: Promise<void> | null = null;

// Every way out of a session: logged out at once, the old session's data gone, the server told.
function endSession(): Promise<void> {
  _auth.set({ user: null, ready: true });
  users.reset();
  hooks.reset();
  apikeys.reset();
  frpConfig.reset();
  const earlier = pendingLogout;
  const done = (async () => {
    await authApi.logout();
    // An earlier logout may still be in flight; its answer would clear a new session just the same.
    await earlier;
  })();
  pendingLogout = done;
  return done.then(() => {
    if (pendingLogout === done) pendingLogout = null;
  });
}

export const auth = {
  subscribe: _auth.subscribe,

  async hydrate(): Promise<void> {
    // The access token lives only in memory, so a page reload starts without
    // one; restore it from the HttpOnly refresh cookie before fetching /me.
    if (!(await restoreSession())) {
      _auth.set({ user: null, ready: true });
      return;
    }
    try {
      const user = await authApi.me();
      _auth.set({ user, ready: true });
    } catch (err) {
      // Only a real auth failure (401/403) should end the session server-side. A transient /me
      // error (a 500 or a network blip right after a successful restoreSession) must NOT log out
      // and invalidate the still-valid refresh cookie — fall back to logged-out locally and let
      // the next reload retry (4.77).
      if (err instanceof ApiError && (err.status === 401 || err.status === 403)) {
        void endSession();
        return;
      }
      _auth.set({ user: null, ready: true });
    }
  },

  async login(username: string, password: string): Promise<void> {
    // A loop, not an if: a stale request of the old session can fire the auth-failure handler, and
    // so start another logout, while this login waits.
    while (pendingLogout) await pendingLogout;
    const user = await authApi.login(username, password);
    _auth.set({ user, ready: true });
  },

  logout(): Promise<void> {
    return endSession();
  },

  // The answer to an admin's PUT on a user. On the signed-in user it is the session's truth too:
  // a self-demotion hides the admin pages at once instead of ending every action in a 403.
  applySelfUpdate(updated: User): void {
    const { user } = get(_auth);
    if (!user || user.id !== updated.id) return;
    _auth.update((state) => ({
      ...state,
      user: { ...user, id: updated.id, username: updated.username, is_admin: updated.is_admin },
    }));
  },
};

export const currentUser = derived(_auth, ($a) => $a.user);
export const isAuthenticated = derived(_auth, ($a) => $a.user !== null);
export const isAdmin = derived(_auth, ($a) => $a.user?.is_admin ?? false);

registerAuthFailureHandler(() => {
  void endSession();
});
