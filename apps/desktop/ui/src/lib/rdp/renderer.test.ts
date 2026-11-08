// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// The renderer against fake contexts (jsdom has no canvas): fitting with the aspect ratio, WebGL
// replacing only the frame's rectangle of one texture, the 2d fallback and a canvas with neither.

import { describe, it, expect, vi, afterEach } from 'vitest';
import type { Frame } from './frameSocket';
import { createRenderer, fitRect } from './renderer';

// Every method a vi.fn, every constant its own name: enough of WebGL to follow the calls.
type Calls = Record<string, ReturnType<typeof vi.fn>>;
function fakeWebgl(): { gl: WebGLRenderingContext; calls: Calls } {
  const calls: Calls = {};
  const gl = new Proxy(calls, {
    get(target, property: string) {
      if (/^[A-Z_0-9]+$/.test(property)) return property;
      target[property] ??= vi.fn(() =>
        property.startsWith('get') && property.endsWith('Parameter') ? true : {},
      );
      return target[property];
    },
  }) as unknown as WebGLRenderingContext;
  return { gl, calls };
}

function fakeCanvas(contexts: { webgl?: unknown; '2d'?: unknown }): HTMLCanvasElement {
  return {
    width: 300,
    height: 150,
    getContext: vi.fn((kind: 'webgl' | '2d') => contexts[kind] ?? null),
  } as unknown as HTMLCanvasElement;
}

const frame = (x: number, y: number, width: number, height: number): Frame => ({
  header: { x, y, width, height, desktopWidth: 1280, desktopHeight: 720 },
  pixels: new Uint8Array(width * height * 4).fill(7),
});

describe('fitRect', () => {
  it('fits 1280x720 into a wider box with bars left and right', () => {
    expect(fitRect(1000, 360, 1280, 720)).toEqual({ x: 180, y: 0, width: 640, height: 360 });
  });

  it('fits into a taller box with bars above and below', () => {
    expect(fitRect(640, 600, 1280, 720)).toEqual({ x: 0, y: 120, width: 640, height: 360 });
  });

  it('is empty without a desktop or without a box', () => {
    expect(fitRect(640, 480, 0, 0)).toEqual({ x: 0, y: 0, width: 0, height: 0 });
    expect(fitRect(0, 480, 1280, 720)).toEqual({ x: 0, y: 0, width: 0, height: 0 });
  });
});

describe('createRenderer', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('takes WebGL and replaces only the rectangle of each frame in one texture', () => {
    const { gl, calls } = fakeWebgl();
    const canvas = fakeCanvas({ webgl: gl });
    const renderer = createRenderer(canvas);
    expect(renderer?.kind).toBe('webgl');

    renderer!.draw(frame(0, 0, 4, 2));
    expect([canvas.width, canvas.height]).toEqual([1280, 720]);
    expect(calls.texImage2D).toHaveBeenCalledTimes(1);
    expect(calls.texImage2D.mock.calls[0].slice(3, 5)).toEqual([1280, 720]);

    const second = frame(10, 20, 3, 5);
    renderer!.draw(second);
    // The texture is made once, for the desktop size; each frame fills its rectangle.
    expect(calls.texImage2D).toHaveBeenCalledTimes(1);
    expect(calls.texSubImage2D.mock.calls[1].slice(2, 6)).toEqual([10, 20, 3, 5]);
    expect(calls.texSubImage2D.mock.calls[1][8]).toBe(second.pixels);
    expect(calls.drawArrays).toHaveBeenCalledTimes(2);
  });

  it('makes the texture anew when the desktop size changes', () => {
    const { gl, calls } = fakeWebgl();
    const renderer = createRenderer(fakeCanvas({ webgl: gl }))!;
    renderer.draw(frame(0, 0, 1, 1));
    renderer.draw({
      ...frame(0, 0, 1, 1),
      header: { ...frame(0, 0, 1, 1).header, desktopWidth: 1920 },
    });
    expect(calls.texImage2D).toHaveBeenCalledTimes(2);
  });

  it('falls back to 2d without WebGL and puts the rectangle where the header says', () => {
    // jsdom has no ImageData.
    vi.stubGlobal(
      'ImageData',
      class {
        constructor(
          readonly data: Uint8ClampedArray,
          readonly width: number,
          readonly height: number,
        ) {}
      },
    );
    const context = { putImageData: vi.fn() };
    const canvas = fakeCanvas({ '2d': context });
    const renderer = createRenderer(canvas);
    expect(renderer?.kind).toBe('2d');
    renderer!.draw(frame(10, 20, 3, 5));
    expect([canvas.width, canvas.height]).toEqual([1280, 720]);
    const [image, x, y] = context.putImageData.mock.calls[0] as [ImageData, number, number];
    expect([image.width, image.height, x, y]).toEqual([3, 5, 10, 20]);
    expect(image.data[0]).toBe(7);
  });

  it('is null when the canvas gives no context', () => {
    expect(createRenderer(fakeCanvas({}))).toBeNull();
  });
});
