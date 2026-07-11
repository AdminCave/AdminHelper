// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

import { describe, it, expect } from 'vitest';
import { accelerateScroll, LIST_FACTOR } from './scrollAcceleration';

// jsdom does no layout, so stub the geometry and back scrollTop/scrollLeft with clamped fields
// (a real element clamps to [0, scrollHeight-clientHeight]) — that clamping is what lets us exercise
// the "preventDefault only when the scroll actually moved" branch.
function makeNode(opts: { clientHeight?: number; scrollHeight?: number; scrollTop?: number } = {}) {
  const node = document.createElement('div');
  const clientHeight = opts.clientHeight ?? 100;
  const scrollHeight = opts.scrollHeight ?? 1000;
  const maxTop = Math.max(0, scrollHeight - clientHeight);
  Object.defineProperty(node, 'clientHeight', { value: clientHeight, configurable: true });
  Object.defineProperty(node, 'scrollHeight', { value: scrollHeight, configurable: true });
  let top = opts.scrollTop ?? 0;
  Object.defineProperty(node, 'scrollTop', {
    get: () => top,
    set: (v) => {
      top = Math.max(0, Math.min(maxTop, v));
    },
    configurable: true,
  });
  return node;
}

function wheel(init: Partial<WheelEvent>): WheelEvent {
  return new WheelEvent('wheel', { cancelable: true, ...init });
}

describe('accelerateScroll', () => {
  it('scales line mode (deltaMode=1) by 16 and accelerates by the factor', () => {
    const node = makeNode();
    accelerateScroll(node, undefined); // -> LIST_FACTOR
    const ev = wheel({ deltaY: 3, deltaMode: 1 });
    node.dispatchEvent(ev);
    expect(node.scrollTop).toBeCloseTo(3 * 16 * LIST_FACTOR);
    expect(ev.defaultPrevented).toBe(true);
  });

  it('scales page mode (deltaMode=2) by clientHeight', () => {
    const node = makeNode({ clientHeight: 100, scrollHeight: 100_000 });
    accelerateScroll(node, 1); // factor 1 to isolate the mode scale
    node.dispatchEvent(wheel({ deltaY: 2, deltaMode: 2 }));
    expect(node.scrollTop).toBeCloseTo(2 * 100);
  });

  it('skips pixel mode (deltaMode=0) so native smooth scroll is untouched', () => {
    const node = makeNode();
    const ev = wheel({ deltaY: 50, deltaMode: 0 });
    accelerateScroll(node, undefined);
    node.dispatchEvent(ev);
    expect(node.scrollTop).toBe(0);
    expect(ev.defaultPrevented).toBe(false);
  });

  it('bypasses on ctrl so browser zoom is not eaten', () => {
    const node = makeNode();
    const ev = wheel({ deltaY: 3, deltaMode: 1, ctrlKey: true });
    accelerateScroll(node, undefined);
    node.dispatchEvent(ev);
    expect(node.scrollTop).toBe(0);
    expect(ev.defaultPrevented).toBe(false);
  });

  it('does nothing when the content is not scrollable', () => {
    const node = makeNode({ clientHeight: 100, scrollHeight: 100 });
    const ev = wheel({ deltaY: 3, deltaMode: 1 });
    accelerateScroll(node, undefined);
    node.dispatchEvent(ev);
    expect(ev.defaultPrevented).toBe(false);
  });

  it('does not preventDefault when scrollTop cannot move (already at the limit)', () => {
    const node = makeNode({ clientHeight: 100, scrollHeight: 200, scrollTop: 100 }); // maxTop=100, at bottom
    const ev = wheel({ deltaY: 3, deltaMode: 1 }); // scroll further down -> clamped, no change
    accelerateScroll(node, undefined);
    node.dispatchEvent(ev);
    expect(node.scrollTop).toBe(100);
    expect(ev.defaultPrevented).toBe(false);
  });

  it('destroy removes the wheel listener', () => {
    const node = makeNode();
    const handle = accelerateScroll(node, undefined);
    handle?.destroy?.();
    node.dispatchEvent(wheel({ deltaY: 3, deltaMode: 1 }));
    expect(node.scrollTop).toBe(0);
  });
});
