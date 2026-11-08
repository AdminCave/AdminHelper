// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// The frame client against a fake WebSocket: token first, the 14-byte header, one receipt per
// picture and none before it, the stats message, input only while open, close.

import { describe, it, expect, vi } from 'vitest';
import { FrameSocket, HEADER_LEN, parseFrame, type FrameHandlers } from './frameSocket';

class FakeSocket {
  binaryType = 'blob';
  sent: string[] = [];
  closed = false;
  onopen: (() => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  constructor(readonly url: string) {}
  send(data: string): void {
    this.sent.push(data);
  }
  close(): void {
    this.closed = true;
  }
  receive(data: unknown): void {
    this.onmessage?.({ data } as MessageEvent);
  }
}

function frameBytes(header: number[], pixels: number[]): ArrayBuffer {
  const buffer = new ArrayBuffer(HEADER_LEN + pixels.length);
  const view = new DataView(buffer);
  header.forEach((value, index) => view.setUint16(index * 2, value, true));
  new Uint8Array(buffer, HEADER_LEN).set(pixels);
  return buffer;
}

function connect(): { socket: FakeSocket; client: FrameSocket; handlers: FrameHandlers } {
  let socket: FakeSocket | undefined;
  const handlers: FrameHandlers = { frame: vi.fn(), stats: vi.fn(), closed: vi.fn() };
  const client = new FrameSocket(41234, 'cafe', handlers, (url) => {
    socket = new FakeSocket(url);
    return socket as unknown as WebSocket;
  });
  return { socket: socket!, client, handlers };
}

describe('parseFrame', () => {
  it('reads the seven little-endian u16 and the RGBA pixels behind them', () => {
    const pixels = [1, 2, 3, 255, 4, 5, 6, 255];
    const frame = parseFrame(frameBytes([1, 3, 4, 2, 1, 1280, 720], pixels));
    expect(frame?.header).toEqual({
      x: 3,
      y: 4,
      width: 2,
      height: 1,
      desktopWidth: 1280,
      desktopHeight: 720,
    });
    expect([...frame!.pixels]).toEqual(pixels);
  });

  it('refuses another version, a short body and a rectangle outside the desktop', () => {
    expect(parseFrame(frameBytes([2, 0, 0, 1, 1, 8, 6], [0, 0, 0, 255]))).toBeNull();
    expect(parseFrame(frameBytes([1, 0, 0, 2, 1, 8, 6], [0, 0, 0, 255]))).toBeNull();
    expect(parseFrame(frameBytes([1, 7, 0, 2, 1, 8, 6], new Array(8).fill(0)))).toBeNull();
    expect(parseFrame(frameBytes([1, 0, 6, 1, 1, 8, 6], [0, 0, 0, 255]))).toBeNull();
    expect(parseFrame(new ArrayBuffer(HEADER_LEN - 1))).toBeNull();
  });
});

describe('FrameSocket', () => {
  it('connects to loopback and sends the token as its first message', () => {
    const { socket } = connect();
    expect(socket.url).toBe('ws://127.0.0.1:41234');
    expect(socket.binaryType).toBe('arraybuffer');
    expect(socket.sent).toEqual([]);
    socket.onopen?.();
    expect(socket.sent).toEqual(['cafe']);
  });

  it('acknowledges each picture after drawing it, and only then', () => {
    const { socket, handlers } = connect();
    socket.onopen?.();
    const order: string[] = [];
    vi.mocked(handlers.frame).mockImplementation(() => {
      order.push(`draw after ${socket.sent.length - 1} receipts`);
    });
    socket.receive(frameBytes([1, 0, 0, 1, 1, 8, 6], [9, 9, 9, 255]));
    expect(order).toEqual(['draw after 0 receipts']);
    expect(socket.sent).toEqual(['cafe', '{"t":"ack"}']);
    // A stats message is no picture and gets no receipt.
    socket.receive('{"t":"stats","fps":30,"width":8,"height":6}');
    expect(socket.sent).toEqual(['cafe', '{"t":"ack"}']);
    socket.receive(frameBytes([1, 1, 1, 1, 1, 8, 6], [9, 9, 9, 255]));
    expect(socket.sent).toEqual(['cafe', '{"t":"ack"}', '{"t":"ack"}']);
  });

  it('acknowledges a picture it cannot read, so the next one still comes', () => {
    const { socket, handlers } = connect();
    socket.onopen?.();
    socket.receive(frameBytes([9, 0, 0, 1, 1, 8, 6], [0, 0, 0, 255]));
    expect(handlers.frame).not.toHaveBeenCalled();
    expect(socket.sent).toEqual(['cafe', '{"t":"ack"}']);
  });

  it('passes the stats on, with mbps and the round trip only when measured', () => {
    const { socket, handlers } = connect();
    socket.onopen?.();
    socket.receive('{"t":"stats","fps":29.5,"width":1280,"height":720,"mbps":1.2,"rtt_ms":40}');
    socket.receive('{"t":"stats","fps":0,"width":1280,"height":720}');
    socket.receive('{"t":"other"}');
    socket.receive('not json');
    expect(vi.mocked(handlers.stats).mock.calls).toEqual([
      [{ fps: 29.5, width: 1280, height: 720, mbps: 1.2, rttMs: 40 }],
      [{ fps: 0, width: 1280, height: 720 }],
    ]);
  });

  it('sends input only while open, as the JSON the server reads', () => {
    const { socket, client } = connect();
    client.send({ t: 'cad' });
    expect(socket.sent).toEqual([]);
    socket.onopen?.();
    client.send({ t: 'key', code: 0x1e, ext: false, down: true });
    client.send({ t: 'mouse', x: 10, y: 20, buttons: 1, wheel: -120 });
    expect(socket.sent.slice(1).map((m) => JSON.parse(m))).toEqual([
      { t: 'key', code: 0x1e, ext: false, down: true },
      { t: 'mouse', x: 10, y: 20, buttons: 1, wheel: -120 },
    ]);
  });

  it('says close before closing, reports the end once and then stays quiet', () => {
    const { socket, client, handlers } = connect();
    socket.onopen?.();
    client.close();
    expect(socket.sent.at(-1)).toBe('{"t":"close"}');
    expect(socket.closed).toBe(true);
    socket.onclose?.();
    expect(handlers.closed).toHaveBeenCalledTimes(1);
    client.send({ t: 'cad' });
    socket.receive(frameBytes([1, 0, 0, 1, 1, 8, 6], [0, 0, 0, 255]));
    expect(socket.sent.at(-1)).toBe('{"t":"close"}');
    expect(handlers.frame).not.toHaveBeenCalled();
  });

  it('reports the end when the server closes or the socket fails', () => {
    const first = connect();
    first.socket.onclose?.();
    expect(first.handlers.closed).toHaveBeenCalledTimes(1);
    const second = connect();
    second.socket.onerror?.();
    second.socket.onclose?.();
    expect(second.handlers.closed).toHaveBeenCalledTimes(1);
  });
});
