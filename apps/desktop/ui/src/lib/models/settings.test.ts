// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

import { describe, it, expect } from 'vitest';
import {
  clampTerminalPrefs,
  getIntervalMinutes,
  getSettingsDefaults,
  getTerminalDefaults,
  validateSettings,
  validateWindowSettings,
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

  it('opens SSH in the AdminHelper terminal and has the terminal defaults of Rust', () => {
    const d = getSettingsDefaults();
    expect(d.sshConsole).toBe('embedded');
    // TerminalPrefs::default() in models.rs.
    expect(d.terminal).toEqual({
      fontSize: 13,
      theme: 'cave',
      cursor: 'block',
      scrollback: 10000,
      copyOnSelect: true,
      rightClickPaste: true,
      confirmClose: true,
      confirmMultilinePaste: false,
    });
  });
});

describe('clampTerminalPrefs', () => {
  const at = (fontSize: number, scrollback: number) =>
    clampTerminalPrefs({ ...getTerminalDefaults(), fontSize, scrollback });

  it('keeps what the settings offer', () => {
    expect(clampTerminalPrefs(getTerminalDefaults())).toEqual(getTerminalDefaults());
    expect(at(10, 1000)).toMatchObject({ fontSize: 10, scrollback: 1000 });
    expect(at(22, 100000)).toMatchObject({ fontSize: 22, scrollback: 100000 });
  });

  it('holds the font size to 10 through 22 in whole points', () => {
    expect(at(9, 10000).fontSize).toBe(10);
    expect(at(0, 10000).fontSize).toBe(10);
    expect(at(23, 10000).fontSize).toBe(22);
    expect(at(255, 10000).fontSize).toBe(22);
    expect(at(14.6, 10000).fontSize).toBe(15);
    expect(at(Number.NaN, 10000).fontSize).toBe(13);
  });

  it('takes the nearest of the three scrollback steps', () => {
    expect(at(13, 0).scrollback).toBe(1000);
    expect(at(13, 5000).scrollback).toBe(1000);
    expect(at(13, 6000).scrollback).toBe(10000);
    expect(at(13, 50000).scrollback).toBe(10000);
    expect(at(13, 60000).scrollback).toBe(100000);
    expect(at(13, 4_000_000_000).scrollback).toBe(100000);
    expect(at(13, Number.NaN).scrollback).toBe(10000);
  });

  it('leaves the other options alone', () => {
    const mine = {
      ...getTerminalDefaults(),
      theme: 'light',
      cursor: 'bar',
      copyOnSelect: false,
    } as const;
    expect(clampTerminalPrefs({ ...mine, fontSize: 99 })).toEqual({ ...mine, fontSize: 22 });
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

  it('server requires https except loopback (3.68)', () => {
    expect(validateSettings({ ...base, mode: 'server', serverUrl: 'http://evil.example' }).ok).toBe(
      false,
    );
    expect(
      validateSettings({ ...base, mode: 'server', serverUrl: 'http://localhost:8443' }).ok,
    ).toBe(true);
    expect(validateSettings({ ...base, mode: 'server', serverUrl: 'http://127.0.0.1' }).ok).toBe(
      true,
    );
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

// The settings of a workspace window edit neither its kind nor its URL (R-0431).
describe('validateWindowSettings', () => {
  const base = getSettingsDefaults();

  it('takes no URL for an input: a workspace without one, or with any, passes', () => {
    for (const serverUrl of [null, '', 'http://evil.example']) {
      expect(validateWindowSettings({ ...base, mode: 'server', serverUrl }).ok).toBe(true);
    }
    for (const url of [null, '', 'http://x']) {
      expect(validateWindowSettings({ ...base, mode: 'sync', url }).ok).toBe(true);
    }
  });

  it('checks the interval of a sync workspace and the custom RDP size', () => {
    expect(validateWindowSettings({ ...base, mode: 'sync', intervalMinutes: Number.NaN }).ok).toBe(
      false,
    );
    expect(
      validateWindowSettings({ ...base, rdpWindowMode: 'custom', rdpCustomSize: 'foo' }).ok,
    ).toBe(false);
    expect(
      validateWindowSettings({ ...base, rdpWindowMode: 'custom', rdpCustomSize: '1920x1080' }).ok,
    ).toBe(true);
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
