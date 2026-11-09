// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Settings model: pure functions + constants, no side effects.

import type { RdpClient, Settings, SshConsole, TerminalPrefs } from '$lib/bridge/types';
import { systemLanguage, tNow } from '$lib/i18n';

export const RDP_WINDOW_MODES = ['fit', 'fullscreen', 'multimon', 'custom'] as const;
export const RDP_PERFORMANCE_PROFILES = ['auto', 'lan', 'broadband', 'low'] as const;
export const RDP_SCALING_MODES = ['auto', 'normal', 'hdpi'] as const;
export const RDP_CUSTOM_SIZE_PATTERN = /^\d{3,5}x\d{3,5}$/;
export const TERMINAL_FONT_SIZE = { min: 10, max: 22 } as const;
export const TERMINAL_SCROLLBACKS = [1_000, 10_000, 100_000] as const;
/** `#[default]` of `SshConsole` in models.rs. */
export const SSH_CONSOLE_DEFAULT: SshConsole = 'embedded';
/** `#[default]` of `RdpClient` in models.rs: the OS client until R-1090. */
export const RDP_CLIENT_DEFAULT: RdpClient = 'os';

/** The H.264 switch of the RDP settings exists on Linux only (R-1102): Windows decodes through
 *  Media Foundation and needs no download. */
export function runsOnLinux(): boolean {
  return typeof navigator !== 'undefined' && navigator.userAgent.toLowerCase().includes('linux');
}

export function getSettingsDefaults(): Settings {
  return {
    mode: 'local',
    url: '',
    intervalMinutes: 1,
    language: systemLanguage(),
    storePasswords: false,
    rdpScalingMode: 'auto',
    rdpWindowMode: 'fit',
    rdpCustomSize: '1920x1080',
    rdpPerformanceProfile: 'auto',
    allowSelfSignedCerts: false,
    serverUrl: '',
    lastUsername: '',
    osNotifications: false,
    favoriteConnections: [],
    sshConsole: SSH_CONSOLE_DEFAULT,
    rdpClient: RDP_CLIENT_DEFAULT,
    rdpH264: true,
    terminal: getTerminalDefaults(),
  };
}

export function getTerminalDefaults(): TerminalPrefs {
  return {
    fontSize: 13,
    theme: 'cave',
    cursor: 'block',
    scrollback: 10_000,
    copyOnSelect: true,
    rightClickPaste: true,
    confirmClose: true,
  };
}

/** `prefs` within what the settings offer, also for a `prefs.json` edited by hand. */
export function clampTerminalPrefs(prefs: TerminalPrefs): TerminalPrefs {
  const defaults = getTerminalDefaults();
  const font = Math.round(Number(prefs.fontSize));
  const fontSize = Number.isFinite(font)
    ? Math.max(TERMINAL_FONT_SIZE.min, Math.min(TERMINAL_FONT_SIZE.max, font))
    : defaults.fontSize;
  const wanted = Number(prefs.scrollback);
  // The nearest of the steps.
  const scrollback = Number.isFinite(wanted)
    ? TERMINAL_SCROLLBACKS.reduce<number>(
        (best, step) => (Math.abs(step - wanted) < Math.abs(best - wanted) ? step : best),
        TERMINAL_SCROLLBACKS[0],
      )
    : defaults.scrollback;
  return { ...prefs, fontSize, scrollback };
}

export function getIntervalMinutes(settings: Partial<Settings> | null | undefined): number {
  const raw = Number(settings?.intervalMinutes);
  if (!Number.isFinite(raw)) return 1;
  return Math.max(1, Math.min(1440, Math.round(raw)));
}

export interface SettingsValidation {
  ok: boolean;
  error?: string;
}

/** The URL of a workspace of the kind `next.mode` and what the window of one edits. */
export function validateSettings(next: Settings): SettingsValidation {
  const url = validateUrl(next);
  return url.ok ? validateWindowSettings(next) : url;
}

/**
 * What the settings of a workspace window edit: the interval of a sync workspace and the RDP
 * size. Its kind and URL are no input there (Rust keeps them), so a URL it lacks, as after a
 * save Rust refused (a device identity, but no URL), does not block a save of the language.
 */
export function validateWindowSettings(next: Settings): SettingsValidation {
  if (next.mode === 'sync' && !Number.isFinite(Number(next.intervalMinutes))) {
    return { ok: false, error: tNow('validation.interval.invalid') };
  }
  if (next.rdpWindowMode === 'custom') {
    const size = (next.rdpCustomSize ?? '').trim();
    if (!RDP_CUSTOM_SIZE_PATTERN.test(size)) {
      return { ok: false, error: tNow('validation.rdpSize.invalid') };
    }
  }
  return { ok: true };
}

// The URL rules by kind; the workspace list checks a URL with them (validateDraft).
function validateUrl(next: Settings): SettingsValidation {
  if (next.mode === 'sync') {
    const url = (next.url ?? '').trim();
    if (!url) return { ok: false, error: tNow('validation.syncUrl.required') };
    if (!url.startsWith('https://')) return { ok: false, error: tNow('validation.syncUrl.https') };
  }
  if (next.mode === 'server') {
    const url = (next.serverUrl ?? '').trim();
    if (!url) return { ok: false, error: tNow('validation.serverUrl.required') };
    // Login credentials + JWTs cross this URL, so approximate the backend rule
    // (validation.rs): https:// required, http:// only for loopback. The backend's
    // loopback set is a superset (127.0.0.0/8, ::1, case-insensitive) and stays the
    // authority — this covers the common cases as immediate form feedback (3.68).
    const loopback = /^http:\/\/(localhost|127(\.\d{1,3}){3}|\[::1\])(:|\/|$)/i;
    if (!/^https:\/\//i.test(url) && !loopback.test(url)) {
      return { ok: false, error: tNow('validation.serverUrl.https') };
    }
  }
  return { ok: true };
}
