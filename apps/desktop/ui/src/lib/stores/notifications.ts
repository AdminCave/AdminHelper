// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Notification store: the bell feed + unread badge, polled app-wide while a
// server session is active (mirrors the monitoring store's activate/deactivate
// + setInterval pattern). New entries are surfaced to an optional handler so the
// OS-notification layer can stay decoupled from this store. The incident actions
// (R-1079) patch the rows they change and reload the feed for the badge.

import { writable, derived, get } from 'svelte/store';
import { listen, type UnlistenFn } from '@tauri-apps/api/event';
import { currentSession } from './session';
import { reportError } from './statusBar';
import { loadDesktopPrefs, setDesktopPrefs } from './notifyPrefs';
import * as bridge from '$lib/bridge';
import { notificationsApi } from '$lib/api/notifications';
import { errMsg } from '$lib/utils/errors';
import type { IncidentAckResult, IncidentDetail, NotificationItem } from '$lib/api/types';
import type { AuthSession } from '$lib/bridge/types';

const POLL_INTERVAL_MS = 30_000;
/** Page size of the center page (R-1078); "load more" asks for the next one by offset. */
export const CENTER_PAGE = 500;

interface NotifState {
  items: NotificationItem[];
  unreadCount: number;
  panelOpen: boolean;
  /** The center page's list, longer than the bell's 50; empty until it loads. */
  center: NotificationItem[];
  centerHasMore: boolean;
}

const EMPTY: NotifState = {
  items: [],
  unreadCount: 0,
  panelOpen: false,
  center: [],
  centerHasMore: false,
};

const _state = writable<NotifState>({ ...EMPTY });
export const notifications = { subscribe: _state.subscribe };
export const notificationItems = derived(_state, ($s) => $s.items);
export const unreadCount = derived(_state, ($s) => $s.unreadCount);
export const panelOpen = derived(_state, ($s) => $s.panelOpen);
export const centerItems = derived(_state, ($s) => $s.center);
export const centerHasMore = derived(_state, ($s) => $s.centerHasMore);

// What the reader has already seen: the latest ping (notifiedAt, R-1079) and the
// highest id. Guards OS notifications from firing for the whole backlog on the
// first poll: priming sets both without firing; only later polls treat a newer
// ping as new. A ping moves notifiedAt, an older row that slides into the 50 or
// that the reader marks unread keeps its own, and a team action pings nobody.
// The id only for a row without notifiedAt (a server before R-1079), and while no
// ping time was seen yet: after a server update mid-session every row has one (the
// migration fills it in), and the backlog must not fire as new.
let lastSeenAt = 0;
let lastSeenId = 0;
let primed = false;
let onNew: ((items: NotificationItem[]) => void) | null = null;

/** Register a handler called with newly-arrived unread entries (for OS notifications). */
export function setNewNotificationHandler(fn: ((items: NotificationItem[]) => void) | null): void {
  onNew = fn;
}

export async function loadFeed(): Promise<void> {
  const session = currentSession();
  if (!session) return;
  try {
    const res = await notificationsApi.fetchFeed(session, 50);
    const list = Array.isArray(res) ? res : [];
    const pingedAt = (n: NotificationItem) => (n.notifiedAt ? Date.parse(n.notifiedAt) : NaN);
    if (primed) {
      const fresh = list.filter((n) => {
        if (n.read || n.muted) return false;
        const at = pingedAt(n);
        if (Number.isNaN(at) || lastSeenAt === 0) return n.id > lastSeenId;
        return at > lastSeenAt;
      });
      if (fresh.length && onNew) onNew(fresh);
    }
    for (const n of list) {
      const at = pingedAt(n);
      if (at > lastSeenAt) lastSeenAt = at;
      if (n.id > lastSeenId) lastSeenId = n.id;
    }
    primed = true;
    // Accurate badge from the dedicated endpoint (the 50-row list would
    // undercount past 50); fall back to the list count if it fails.
    let unread = list.filter((n) => !n.read).length;
    try {
      const c = await notificationsApi.fetchUnreadCount(session);
      if (typeof c?.count === 'number') unread = c.count;
    } catch {
      /* keep the list-derived count */
    }
    _state.update((s) => ({ ...s, items: list, unreadCount: unread }));
  } catch {
    // Session expiry / transient errors: keep the current feed, retry next poll.
  }
}

export async function markAllRead(): Promise<void> {
  const session = currentSession();
  if (!session) return;
  try {
    await notificationsApi.markRead(session, null);
    _state.update((s) => ({
      ...s,
      items: s.items.map((n) => ({ ...n, read: true })),
      center: s.center.map((n) => ({ ...n, read: true })),
      unreadCount: 0,
    }));
  } catch {
    /* ignore — next poll reconciles */
  }
}

/** Marks the entries `ids` as read, in the bell feed and on the center page. */
export async function markRead(ids: number[]): Promise<void> {
  const session = currentSession();
  if (!session || !ids.length) return;
  try {
    await notificationsApi.markRead(session, ids);
    const marked = new Set(ids);
    _state.update((s) => {
      const known = new Map([...s.center, ...s.items].map((n) => [n.id, n]));
      const newlyRead = ids.filter((id) => known.get(id)?.read === false).length;
      const read = (n: NotificationItem) => (marked.has(n.id) ? { ...n, read: true } : n);
      return {
        ...s,
        items: s.items.map(read),
        center: s.center.map(read),
        unreadCount: Math.max(0, s.unreadCount - newlyRead),
      };
    });
  } catch {
    /* ignore — next poll reconciles */
  }
}

function patchRows(fn: (n: NotificationItem) => NotificationItem): void {
  _state.update((s) => ({ ...s, items: s.items.map(fn), center: s.center.map(fn) }));
}

/** Puts a row the server sent back in place of its copy, in the bell feed and on the center page. */
function replaceRow(row: NotificationItem): void {
  patchRows((n) => (n.id === row.id ? row : n));
}

// The server takes at most 500 ids per call (IdsRequest); a selection of the center can hold more.
const IDS_PER_CALL = 500;
function inParts(ids: number[]): number[][] {
  const unique = [...new Set(ids)];
  const parts: number[][] = [];
  for (let i = 0; i < unique.length; i += IDS_PER_CALL)
    parts.push(unique.slice(i, i + IDS_PER_CALL));
  return parts;
}

/**
 * Removes the rows `ids` from the bell feed and the center page; the next ping shows them again.
 * Each part the server took is applied, also when a later one fails.
 */
export async function hide(ids: number[]): Promise<boolean> {
  const session = currentSession();
  if (!session || !ids.length) return false;
  try {
    for (const part of inParts(ids)) {
      await notificationsApi.hide(session, part);
      const gone = new Set(part);
      _state.update((s) => ({
        ...s,
        items: s.items.filter((n) => !gone.has(n.id)),
        center: s.center.filter((n) => !gone.has(n.id)),
      }));
    }
    await loadFeed();
    return true;
  } catch (err) {
    reportError(errMsg(err));
    return false;
  }
}

export async function markUnread(ids: number[]): Promise<boolean> {
  const session = currentSession();
  if (!session || !ids.length) return false;
  try {
    for (const part of inParts(ids)) {
      await notificationsApi.markUnread(session, part);
      const marked = new Set(part);
      patchRows((n) => (marked.has(n.id) ? { ...n, read: false, readAt: null } : n));
    }
    await loadFeed();
    return true;
  } catch (err) {
    reportError(errMsg(err));
    return false;
  }
}

/**
 * Acknowledges the incidents `incidentIds` (not row ids). Every row of an acknowledged one turns
 * acked; one the server skipped (not open, or not the reader's to act on) stays as it is.
 */
export async function ackIncidents(incidentIds: number[]): Promise<IncidentAckResult | null> {
  const session = currentSession();
  if (!session || !incidentIds.length) return null;
  try {
    const total: IncidentAckResult = { updated: 0, skipped: [] };
    for (const part of inParts(incidentIds)) {
      const res = await notificationsApi.ackIncidents(session, part);
      total.updated += res.updated;
      total.skipped.push(...res.skipped);
      const skipped = new Set(res.skipped);
      const acked = new Set(part.filter((id) => !skipped.has(id)));
      patchRows((n) =>
        n.incidentId != null && acked.has(n.incidentId)
          ? { ...n, state: 'acked', ackedBy: session.username }
          : n,
      );
    }
    await loadFeed();
    return total;
  } catch (err) {
    reportError(errMsg(err));
    return null;
  }
}

// An action on one incident: the answer carries the reader's row, which replaces its copy. A
// failure goes to the status bar and answers null.
async function rowAction<T>(
  call: (session: AuthSession) => Promise<T>,
  rowOf: (res: T) => NotificationItem,
): Promise<T | null> {
  const session = currentSession();
  if (!session) return null;
  try {
    const res = await call(session);
    replaceRow(rowOf(res));
    await loadFeed();
    return res;
  } catch (err) {
    reportError(errMsg(err));
    return null;
  }
}

const detailRow = (d: IncidentDetail) => d.row;

export function resolveIncident(id: number): Promise<IncidentDetail | null> {
  return rowAction((s) => notificationsApi.resolveIncident(s, id), detailRow);
}

export function reopenIncident(id: number): Promise<IncidentDetail | null> {
  return rowAction((s) => notificationsApi.reopenIncident(s, id), detailRow);
}

/** Every reader of the incident sees the note in its history. */
export function addNote(id: number, text: string): Promise<IncidentDetail | null> {
  return rowAction((s) => notificationsApi.addNote(s, id, text), detailRow);
}

/** The reader's own mute; until: an ISO time with zone, later than now, at most 7 days ahead. */
export function muteIncident(id: number, until: string): Promise<NotificationItem | null> {
  return rowAction(
    (s) => notificationsApi.muteIncident(s, id, until),
    (row) => row,
  );
}

export function unmuteIncident(id: number): Promise<NotificationItem | null> {
  return rowAction(
    (s) => notificationsApi.unmuteIncident(s, id),
    (row) => row,
  );
}

// Which rows a server mute touches only the server knows: the center reloads from the start
// when it holds a list.
async function serverMute(call: (session: AuthSession) => Promise<unknown>): Promise<boolean> {
  const session = currentSession();
  if (!session) return false;
  try {
    await call(session);
    await loadFeed();
    if (get(_state).center.length) await loadCenter(true);
    return true;
  } catch (err) {
    reportError(errMsg(err));
    return false;
  }
}

export function muteServer(serverId: string, until: string): Promise<boolean> {
  return serverMute((s) => notificationsApi.muteServer(s, serverId, until));
}

export function unmuteServer(serverId: string): Promise<boolean> {
  return serverMute((s) => notificationsApi.unmuteServer(s, serverId));
}

/**
 * Loads the center page's list: from the start (`reset`), or the next page after what it holds.
 * A failed load keeps what is there.
 */
export async function loadCenter(reset = true): Promise<void> {
  const session = currentSession();
  if (!session) return;
  const offset = reset ? 0 : get(_state).center.length;
  const gen = logoutGen;
  try {
    const res = await notificationsApi.fetchFeed(session, CENTER_PAGE, offset);
    // A logout during the request emptied the list; a late page must not refill it. Not
    // activationGen: the page's onMount load starts before AppShell activates after a login.
    if (gen !== logoutGen) return;
    const page = Array.isArray(res) ? res : [];
    _state.update((s) => {
      const before = reset ? [] : s.center;
      const seen = new Set(before.map((n) => n.id));
      return {
        ...s,
        center: [...before, ...page.filter((n) => !seen.has(n.id))],
        centerHasMore: page.length === CENTER_PAGE,
      };
    });
  } catch {
    /* keep the current list */
  }
}

// Opening the panel marks nothing read any more (R-1078): the "unread" tab would be empty.
export function togglePanel(): void {
  _state.update((s) => ({ ...s, panelOpen: !s.panelOpen }));
}

export function closePanel(): void {
  _state.update((s) => ({ ...s, panelOpen: false }));
}

let pollTimer: ReturnType<typeof setInterval> | null = null;
let unlistenStream: UnlistenFn | null = null;
// Bumped by every activate/deactivate so an in-flight activation whose async awaits are
// overtaken by a logout can detect it's stale and undo itself instead of leaking (4.41).
let activationGen = 0;
// Bumped only by deactivateNotifications (loadCenter's guard).
let logoutGen = 0;

export async function activateNotifications(): Promise<void> {
  const gen = ++activationGen;
  void loadDesktopPrefs();
  void loadFeed();
  if (pollTimer) clearInterval(pollTimer);
  // Polling stays as a fallback (SSE may be unavailable: no Redis, dead stream).
  pollTimer = setInterval(() => void loadFeed(), POLL_INTERVAL_MS);

  // Live SSE push: a `notification` Tauri event (emitted by the Rust stream
  // client) means "reload the feed now". We reuse loadFeed instead of merging a
  // payload, keeping a single source of truth (priming, unread-count, OS-notify).
  if (currentSession()) {
    try {
      await bridge.startNotificationStream();
      const un = await listen('notification', () => void loadFeed());
      // A logout (deactivateNotifications) may have run during the awaits above and bumped
      // activationGen. Registering the listener now would leak it (never removed) and leave the
      // Rust SSE stream running after stopNotificationStream — on fast logout/login cycles
      // duplicate handlers accumulate. Undo this stale activation instead (4.41).
      if (gen !== activationGen) {
        un();
        void bridge.stopNotificationStream();
        return;
      }
      unlistenStream = un;
    } catch (err) {
      console.warn('Notification-Stream konnte nicht gestartet werden', err);
      // The fallback poll keeps the bell working — graceful degradation.
    }
  }
}

export function deactivateNotifications(): void {
  activationGen++; // invalidate any in-flight activateNotifications so it undoes itself (4.41)
  logoutGen++;
  if (pollTimer) {
    clearInterval(pollTimer);
    pollTimer = null;
  }
  if (unlistenStream) {
    try {
      unlistenStream();
    } catch {
      /* ignore */
    }
    unlistenStream = null;
  }
  void bridge.stopNotificationStream();
  setDesktopPrefs(null);
  // Reset priming so a different user's backlog does not trigger OS spam.
  lastSeenAt = 0;
  lastSeenId = 0;
  primed = false;
  _state.set({ ...EMPTY });
}
