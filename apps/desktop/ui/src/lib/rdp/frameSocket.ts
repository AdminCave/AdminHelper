// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// The webview's end of an embedded RDP session's local WebSocket (rdp_embedded/frame_ws.rs):
// the token as the first message, then one picture per binary message, each acknowledged with
// `{"t":"ack"}` once it is drawn; the server sends the next one only after that receipt.

import type { RdpMonitor } from './display';

export const FRAME_VERSION = 1;
// Version, x, y, width, height, desktop width, desktop height: seven u16, little-endian.
export const HEADER_LEN = 14;

export interface FrameHeader {
  x: number;
  y: number;
  width: number;
  height: number;
  desktopWidth: number;
  desktopHeight: number;
}

export interface Frame {
  header: FrameHeader;
  // RGBA, `width * height * 4` bytes of the rectangle at x, y.
  pixels: Uint8Array;
}

// What the server measured, once a second while there is a picture.
export interface FrameStats {
  fps: number;
  width: number;
  height: number;
  mbps?: number;
  rttMs?: number;
}

export type FrameInput =
  | { t: 'key'; code: number; ext: boolean; down: boolean }
  | { t: 'mouse'; x: number; y: number; buttons: number; wheel: number }
  | { t: 'cad' }
  // The desktop to ask the server for (R-1100); Rust keeps it within MS-RDPEDISP.
  | { t: 'size'; w: number; h: number; scale: number }
  // Two monitors, where they lie and their desktop (R-1101); the server places the second one.
  | { t: 'layout'; monitors: RdpMonitor[] };

export interface FrameHandlers {
  // Draws the picture; the receipt goes out when this returns.
  frame(frame: Frame): void;
  stats(stats: FrameStats): void;
  // The socket is open and sent its token: input goes out from now on.
  opened(): void;
  // The socket closed, from either side.
  closed(): void;
}

// A frame of another version, or one shorter than its header says, is null.
export function parseFrame(data: ArrayBuffer): Frame | null {
  if (data.byteLength < HEADER_LEN) return null;
  const view = new DataView(data);
  const at = (index: number): number => view.getUint16(index * 2, true);
  if (at(0) !== FRAME_VERSION) return null;
  const header: FrameHeader = {
    x: at(1),
    y: at(2),
    width: at(3),
    height: at(4),
    desktopWidth: at(5),
    desktopHeight: at(6),
  };
  const length = header.width * header.height * 4;
  if (data.byteLength !== HEADER_LEN + length) return null;
  if (header.x + header.width > header.desktopWidth) return null;
  if (header.y + header.height > header.desktopHeight) return null;
  return { header, pixels: new Uint8Array(data, HEADER_LEN, length) };
}

function parseStats(text: string): FrameStats | null {
  let message: unknown;
  try {
    message = JSON.parse(text);
  } catch {
    return null;
  }
  if (typeof message !== 'object' || message === null) return null;
  const m = message as Record<string, unknown>;
  if (m.t !== 'stats') return null;
  if (typeof m.fps !== 'number' || typeof m.width !== 'number' || typeof m.height !== 'number')
    return null;
  const stats: FrameStats = { fps: m.fps, width: m.width, height: m.height };
  if (typeof m.mbps === 'number') stats.mbps = m.mbps;
  if (typeof m.rtt_ms === 'number') stats.rttMs = m.rtt_ms;
  return stats;
}

export type SocketFactory = (url: string) => WebSocket;

export class FrameSocket {
  private readonly socket: WebSocket;
  private open = false;
  private done = false;

  constructor(
    port: number,
    token: string,
    private readonly handlers: FrameHandlers,
    create: SocketFactory = (url) => new WebSocket(url),
  ) {
    this.socket = create(`ws://127.0.0.1:${port}`);
    this.socket.binaryType = 'arraybuffer';
    this.socket.onopen = () => {
      this.open = true;
      this.socket.send(token);
      this.handlers.opened();
    };
    this.socket.onmessage = (event: MessageEvent) => this.receive(event.data);
    this.socket.onclose = () => this.end();
    this.socket.onerror = () => this.end();
  }

  private receive(data: unknown): void {
    if (this.done) return;
    if (data instanceof ArrayBuffer) {
      const frame = parseFrame(data);
      if (frame) this.handlers.frame(frame);
      // Also a picture the webview could not read: without the receipt no picture follows.
      this.socket.send('{"t":"ack"}');
    } else if (typeof data === 'string') {
      const stats = parseStats(data);
      if (stats) this.handlers.stats(stats);
    }
  }

  private end(): void {
    if (this.done) return;
    this.done = true;
    this.open = false;
    this.handlers.closed();
  }

  // Input before the socket opened, or after it closed, is dropped: the server would not have
  // taken it either.
  send(input: FrameInput): void {
    if (this.open && !this.done) this.socket.send(JSON.stringify(input));
  }

  // Closing lets go of the picture only, without `{"t":"close"}`: a view goes whenever its tab
  // docks out or a window closes, and the session ends through `rdp_session_stop` alone.
  close(): void {
    this.socket.close();
    this.end();
  }
}
