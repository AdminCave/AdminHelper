// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// The short tone of a critical toast (R-1081): an oscillator, no audio file. Without WebAudio
// nothing plays.

let ctx: AudioContext | null = null;

export function playCriticalTone(): void {
  try {
    if (typeof AudioContext === 'undefined') return;
    ctx ??= new AudioContext();
    // A context created outside a user gesture starts suspended and stays silent until resumed.
    if (ctx.state === 'suspended') void ctx.resume().catch(() => {});
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    const t = ctx.currentTime;
    osc.type = 'sine';
    osc.frequency.setValueAtTime(880, t);
    osc.frequency.setValueAtTime(660, t + 0.15);
    gain.gain.setValueAtTime(0.2, t);
    gain.gain.exponentialRampToValueAtTime(0.001, t + 0.35);
    osc.connect(gain).connect(ctx.destination);
    osc.start(t);
    osc.stop(t + 0.35);
  } catch {
    /* best-effort: a tone that cannot play must not affect the toast */
  }
}
