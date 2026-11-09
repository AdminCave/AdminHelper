// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

import { afterEach, describe, expect, it, vi } from 'vitest';

function stubAudioContext(state: 'suspended' | 'running') {
  const resume = vi.fn().mockResolvedValue(undefined);
  const start = vi.fn();
  const param = { setValueAtTime: vi.fn(), exponentialRampToValueAtTime: vi.fn() };
  class FakeAudioContext {
    state = state;
    currentTime = 0;
    destination = {};
    resume = resume;
    createOscillator() {
      const osc = {
        type: '',
        frequency: param,
        start,
        stop: vi.fn(),
        connect: (n: unknown) => n,
      };
      return osc;
    }
    createGain() {
      return { gain: param, connect: (n: unknown) => n };
    }
  }
  vi.stubGlobal('AudioContext', FakeAudioContext);
  return { resume, start };
}

describe('playCriticalTone (R-1183)', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.resetModules();
  });

  it('resumes a suspended context and still schedules the tone', async () => {
    const { resume, start } = stubAudioContext('suspended');
    const { playCriticalTone } = await import('./sound');
    playCriticalTone();
    expect(resume).toHaveBeenCalledTimes(1);
    expect(start).toHaveBeenCalledTimes(1);
  });

  it('leaves a running context alone', async () => {
    const { resume, start } = stubAudioContext('running');
    const { playCriticalTone } = await import('./sound');
    playCriticalTone();
    expect(resume).not.toHaveBeenCalled();
    expect(start).toHaveBeenCalledTimes(1);
  });
});
