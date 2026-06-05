// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Accelerates mouse-wheel scrolling in long lists/panels. Implemented as a
// Svelte action so bindings disappear automatically with the component lifecycle.

import type { Action } from 'svelte/action';

export const LIST_FACTOR = 1.55;
export const PANEL_FACTOR = 1.35;

export const accelerateScroll: Action<HTMLElement, number | undefined> = (node, factorParam) => {
  let factor = factorParam ?? LIST_FACTOR;

  function onWheel(event: WheelEvent): void {
    if (event.ctrlKey) return;
    if (node.scrollHeight <= node.clientHeight) return;
    if (event.deltaMode === 0) return;

    let modeScale = 1;
    if (event.deltaMode === 1) modeScale = 16;
    else if (event.deltaMode === 2) modeScale = node.clientHeight;

    const deltaY = event.deltaY * modeScale;
    const deltaX = event.deltaX * modeScale;
    if (Math.abs(deltaY) < 0.5 && Math.abs(deltaX) < 0.5) return;

    const beforeTop = node.scrollTop;
    const beforeLeft = node.scrollLeft;
    node.scrollTop += deltaY * factor;
    node.scrollLeft += deltaX * factor;
    const changed =
      Math.abs(node.scrollTop - beforeTop) > 0.1 || Math.abs(node.scrollLeft - beforeLeft) > 0.1;
    if (changed) event.preventDefault();
  }

  node.addEventListener('wheel', onWheel, { passive: false });

  return {
    update(next: number | undefined): void {
      factor = next ?? LIST_FACTOR;
    },
    destroy(): void {
      node.removeEventListener('wheel', onWheel);
    },
  };
};
