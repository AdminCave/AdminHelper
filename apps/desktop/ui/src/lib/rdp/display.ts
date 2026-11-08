// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// The desktop an embedded RDP session asks for (R-1100). *Fit* follows the size of the tab,
// *Fixed* keeps `rdp_custom_size` and zooms the picture. The scaling decides the pixels and the
// scale factor: *100 %* asks for the CSS pixels of the tab at 100 %, *Auto* for its physical
// pixels at the scale factor of `devicePixelRatio`, so the picture is sharp and of the size the
// local screen would show it, and *HiDPI* for the physical pixels at least at 175 %, as the OS
// client's HiDPI asks for a large scale. Rust keeps it within the limits of MS-RDPEDISP.

import type { RdpDisplay, RdpScalingMode, RdpWindowMode } from '$lib/bridge/types';
import { RDP_CUSTOM_SIZE_PATTERN } from '$lib/models/settings';

/** How the tab lays the desktop out; fullscreen and multi-monitor come with later stages. */
export type RdpLayout = 'fit' | 'custom';

export const FIXED_DEFAULT = { width: 1280, height: 720 } as const;
export const ZOOM = { min: 25, max: 200, step: 25 } as const;
/** How long the tab has to keep its size before the session follows. */
export const RESIZE_DEBOUNCE_MS = 300;

export function layoutOf(mode: RdpWindowMode): RdpLayout {
  return mode === 'custom' ? 'custom' : 'fit';
}

// The scale factors Windows offers, in steps of 25 %.
export function scaleOf(ratio: number): number {
  const percent = Math.round((ratio * 100) / 25) * 25;
  return Math.min(Math.max(percent, 100), 500);
}

/** `devicePixelRatio` as the desktop's pixels per CSS pixel and its scale factor. */
function density(scaling: RdpScalingMode, ratio: number): { pixels: number; scale: number } {
  const dpr = ratio > 0 ? ratio : 1;
  if (scaling === 'normal') return { pixels: 1, scale: 100 };
  const scale = scaleOf(dpr);
  return { pixels: dpr, scale: scaling === 'hdpi' ? Math.max(scale, 175) : scale };
}

// The largest side MS-RDPEDISP takes; Rust clamps to it too, but reads a side as u16, so a
// larger one would fail the whole start.
const MAX_SIDE = 8192;

/** `rdp_custom_size` as width and height; a missing or malformed one is 1280×720. */
export function parseSize(size: string | null | undefined): { width: number; height: number } {
  if (!size || !RDP_CUSTOM_SIZE_PATTERN.test(size)) return { ...FIXED_DEFAULT };
  const [width, height] = size.split('x').map((side) => Math.min(Number(side), MAX_SIDE));
  return { width, height };
}

/** The desktop for a tab of `boxWidth`×`boxHeight` CSS pixels. */
export function fitDisplay(
  boxWidth: number,
  boxHeight: number,
  scaling: RdpScalingMode,
  ratio: number,
): RdpDisplay {
  const { pixels, scale } = density(scaling, ratio);
  return {
    width: Math.round(boxWidth * pixels),
    height: Math.round(boxHeight * pixels),
    scale,
  };
}

/** The fixed desktop of `size` at the scale factor of the scaling. */
export function fixedDisplay(
  size: string | null | undefined,
  scaling: RdpScalingMode,
  ratio: number,
): RdpDisplay {
  return { ...parseSize(size), scale: density(scaling, ratio).scale };
}

export function clampZoom(zoom: number): number {
  return Math.min(Math.max(Math.round(zoom), ZOOM.min), ZOOM.max);
}

/**
 * The CSS size of a zoomed desktop. 100 % is 1:1, one desktop pixel on one pixel of the screen,
 * so the CSS size is the desktop's divided by `devicePixelRatio`.
 */
export function zoomedSize(
  desktopWidth: number,
  desktopHeight: number,
  zoom: number,
  ratio: number,
): { width: number; height: number } {
  const factor = clampZoom(zoom) / 100 / (ratio > 0 ? ratio : 1);
  return { width: desktopWidth * factor, height: desktopHeight * factor };
}

/** Calls `run` once `ms` passed without another call; `cancel` drops a pending one. */
export function debounce<A extends unknown[]>(
  run: (...args: A) => void,
  ms: number,
): { (...args: A): void; cancel(): void } {
  let timer: ReturnType<typeof setTimeout> | null = null;
  const call = (...args: A): void => {
    if (timer !== null) clearTimeout(timer);
    timer = setTimeout(() => {
      timer = null;
      run(...args);
    }, ms);
  };
  call.cancel = () => {
    if (timer !== null) clearTimeout(timer);
    timer = null;
  };
  return call;
}
