// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Settings model: pure functions + constants, no side effects.

import type { Settings } from '$lib/bridge/types';
import { tNow } from '$lib/i18n';

export const RDP_WINDOW_MODES = ['fit', 'fullscreen', 'multimon', 'custom'] as const;
export const RDP_PERFORMANCE_PROFILES = ['auto', 'lan', 'broadband', 'low'] as const;
export const RDP_SCALING_MODES = ['auto', 'normal', 'hdpi'] as const;
export const RDP_CUSTOM_SIZE_PATTERN = /^\d{3,5}x\d{3,5}$/;

export function detectSystemLanguage(): 'de' | 'en' {
  const language = typeof navigator !== 'undefined' ? (navigator.language ?? '') : '';
  return language.toLowerCase().startsWith('de') ? 'de' : 'en';
}

export function getSettingsDefaults(): Settings {
  return {
    mode: 'local',
    url: '',
    intervalMinutes: 1,
    language: detectSystemLanguage(),
    storePasswords: false,
    rdpScalingMode: 'auto',
    rdpWindowMode: 'fit',
    rdpCustomSize: '1920x1080',
    rdpPerformanceProfile: 'auto',
    allowSelfSignedCerts: false,
    serverUrl: '',
    lastUsername: '',
    osNotifications: false,
  };
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

export function validateSettings(next: Settings): SettingsValidation {
  if (next.mode === 'sync') {
    const url = (next.url ?? '').trim();
    if (!url) return { ok: false, error: tNow('validation.syncUrl.required') };
    if (!url.startsWith('https://')) return { ok: false, error: tNow('validation.syncUrl.https') };
    if (!Number.isFinite(Number(next.intervalMinutes))) {
      return { ok: false, error: tNow('validation.interval.invalid') };
    }
  }
  if (next.mode === 'server') {
    const url = (next.serverUrl ?? '').trim();
    if (!url) return { ok: false, error: tNow('validation.serverUrl.required') };
  }
  if (next.rdpWindowMode === 'custom') {
    const size = (next.rdpCustomSize ?? '').trim();
    if (!RDP_CUSTOM_SIZE_PATTERN.test(size)) {
      return { ok: false, error: tNow('validation.rdpSize.invalid') };
    }
  }
  return { ok: true };
}

export function settingsModeLabel(mode: Settings['mode']): string {
  switch (mode) {
    case 'local':
      return 'Lokal';
    case 'sync':
      return 'Sync';
    case 'server':
      return 'Server';
  }
}
