// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

import { describe, it, expect } from 'vitest';
import {
  getIntervalMinutes,
  getSettingsDefaults,
  validateSettings,
  settingsModeLabel,
  RDP_CUSTOM_SIZE_PATTERN,
} from './settings';

describe('getIntervalMinutes', () => {
  it('clamps below 1 to 1', () => {
    expect(getIntervalMinutes({ intervalMinutes: 0 })).toBe(1);
    expect(getIntervalMinutes({ intervalMinutes: -7 })).toBe(1);
  });
  it('clamps above 1440 to 1440', () => {
    expect(getIntervalMinutes({ intervalMinutes: 99999 })).toBe(1440);
  });
  it('rounds floats', () => {
    expect(getIntervalMinutes({ intervalMinutes: 5.7 })).toBe(6);
  });
  it('falls back to 1 for non-finite', () => {
    expect(getIntervalMinutes({ intervalMinutes: Number.NaN })).toBe(1);
    expect(getIntervalMinutes(null)).toBe(1);
  });
});

describe('getSettingsDefaults', () => {
  it('defaults to local mode, 1 minute', () => {
    const d = getSettingsDefaults();
    expect(d.mode).toBe('local');
    expect(d.intervalMinutes).toBe(1);
    expect(d.rdpWindowMode).toBe('fit');
    expect(d.rdpPerformanceProfile).toBe('auto');
  });
});

describe('validateSettings', () => {
  const base = getSettingsDefaults();

  it('sync requires https url', () => {
    expect(validateSettings({ ...base, mode: 'sync', url: '' }).ok).toBe(false);
    expect(validateSettings({ ...base, mode: 'sync', url: 'http://x' }).ok).toBe(false);
    expect(validateSettings({ ...base, mode: 'sync', url: 'https://x' }).ok).toBe(true);
  });

  it('server requires serverUrl', () => {
    expect(validateSettings({ ...base, mode: 'server', serverUrl: '' }).ok).toBe(false);
    expect(validateSettings({ ...base, mode: 'server', serverUrl: 'https://x' }).ok).toBe(true);
  });

  it('custom rdp size must match pattern', () => {
    expect(validateSettings({ ...base, rdpWindowMode: 'custom', rdpCustomSize: 'foo' }).ok).toBe(
      false,
    );
    expect(
      validateSettings({ ...base, rdpWindowMode: 'custom', rdpCustomSize: '1920x1080' }).ok,
    ).toBe(true);
  });
});

describe('settingsModeLabel', () => {
  it('maps all modes to German labels', () => {
    expect(settingsModeLabel('local')).toBe('Lokal');
    expect(settingsModeLabel('sync')).toBe('Sync');
    expect(settingsModeLabel('server')).toBe('Server');
  });
});

describe('RDP_CUSTOM_SIZE_PATTERN', () => {
  it('matches WxH formats', () => {
    expect(RDP_CUSTOM_SIZE_PATTERN.test('1920x1080')).toBe(true);
    expect(RDP_CUSTOM_SIZE_PATTERN.test('800x600')).toBe(true);
    expect(RDP_CUSTOM_SIZE_PATTERN.test('12x34')).toBe(false);
    expect(RDP_CUSTOM_SIZE_PATTERN.test('1920X1080')).toBe(false);
  });
});
