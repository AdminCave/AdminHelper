// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// The desktop a tab asks for (R-1100): pixels and scale factor per scaling, the fixed size from
// the settings, the zoom limits and its CSS size, and the debounce before a resize goes out.

import { describe, it, expect, vi, afterEach } from 'vitest';
import {
  clampZoom,
  debounce,
  fitDisplay,
  fixedDisplay,
  layoutOf,
  parseSize,
  scaleOf,
  zoomedSize,
} from './display';

afterEach(() => vi.useRealTimers());

describe('display (R-1100)', () => {
  it('rounds devicePixelRatio to the scale factors Windows offers', () => {
    expect(scaleOf(1)).toBe(100);
    expect(scaleOf(1.25)).toBe(125);
    expect(scaleOf(1.3)).toBe(125);
    expect(scaleOf(1.5)).toBe(150);
    expect(scaleOf(2)).toBe(200);
    expect(scaleOf(0.5)).toBe(100);
    expect(scaleOf(6)).toBe(500);
  });

  it('asks for the tab in CSS pixels at 100 %, in physical pixels with Auto and HiDPI', () => {
    expect(fitDisplay(1000, 600, 'normal', 2)).toEqual({ width: 1000, height: 600, scale: 100 });
    expect(fitDisplay(1000, 600, 'auto', 2)).toEqual({ width: 2000, height: 1200, scale: 200 });
    expect(fitDisplay(1000, 600, 'auto', 1)).toEqual({ width: 1000, height: 600, scale: 100 });
    expect(fitDisplay(1000, 600, 'auto', 1.25)).toEqual({ width: 1250, height: 750, scale: 125 });
    expect(fitDisplay(1000, 600, 'hdpi', 1)).toEqual({ width: 1000, height: 600, scale: 175 });
    expect(fitDisplay(1000, 600, 'hdpi', 2)).toEqual({ width: 2000, height: 1200, scale: 200 });
    // A ratio the webview does not know is 1.
    expect(fitDisplay(800, 500, 'auto', 0)).toEqual({ width: 800, height: 500, scale: 100 });
  });

  it('keeps the fixed size from the settings, 1280×720 without a valid one', () => {
    expect(parseSize('1920x1080')).toEqual({ width: 1920, height: 1080 });
    expect(parseSize(null)).toEqual({ width: 1280, height: 720 });
    expect(parseSize('big')).toEqual({ width: 1280, height: 720 });
    expect(parseSize('99999x70000')).toEqual({ width: 8192, height: 8192 });
    expect(fixedDisplay('1920x1080', 'auto', 1.5)).toEqual({
      width: 1920,
      height: 1080,
      scale: 150,
    });
    expect(fixedDisplay(undefined, 'normal', 2)).toEqual({ width: 1280, height: 720, scale: 100 });
  });

  it('lays out fixed as fixed and every other mode as fit for now', () => {
    expect(layoutOf('custom')).toBe('custom');
    expect(layoutOf('fit')).toBe('fit');
    expect(layoutOf('fullscreen')).toBe('fit');
    expect(layoutOf('multimon')).toBe('fit');
  });

  it('zooms from 25 to 200 %, 100 % being one desktop pixel per screen pixel', () => {
    expect(clampZoom(10)).toBe(25);
    expect(clampZoom(250)).toBe(200);
    expect(clampZoom(75)).toBe(75);
    expect(zoomedSize(1280, 720, 100, 1)).toEqual({ width: 1280, height: 720 });
    expect(zoomedSize(1280, 720, 100, 2)).toEqual({ width: 640, height: 360 });
    expect(zoomedSize(1280, 720, 50, 1)).toEqual({ width: 640, height: 360 });
    expect(zoomedSize(1280, 720, 400, 1)).toEqual({ width: 2560, height: 1440 });
  });

  it('calls once the calls have rested, with the last arguments, and not after a cancel', () => {
    vi.useFakeTimers();
    const run = vi.fn();
    const call = debounce(run, 300);
    call(1);
    vi.advanceTimersByTime(200);
    call(2);
    vi.advanceTimersByTime(299);
    expect(run).not.toHaveBeenCalled();
    vi.advanceTimersByTime(1);
    expect(run).toHaveBeenCalledOnce();
    expect(run).toHaveBeenCalledWith(2);

    call(3);
    call.cancel();
    vi.advanceTimersByTime(1000);
    expect(run).toHaveBeenCalledOnce();
  });
});
