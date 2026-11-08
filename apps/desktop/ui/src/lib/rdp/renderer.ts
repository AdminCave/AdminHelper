// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Draws the desktop of an embedded RDP session on a canvas the size of the desktop: WebGL keeps
// it in one texture and replaces only the rectangle of each frame (texSubImage2D); without a
// WebGL context, 2d with putImageData. The canvas is fitted into its box by CSS
// (`object-fit: contain`), so `fitRect` is where the picture lands on screen.

import type { Frame } from './frameSocket';

export interface Rect {
  x: number;
  y: number;
  width: number;
  height: number;
}

// The largest rectangle with the desktop's aspect ratio inside a box, centred.
export function fitRect(
  boxWidth: number,
  boxHeight: number,
  desktopWidth: number,
  desktopHeight: number,
): Rect {
  if (desktopWidth <= 0 || desktopHeight <= 0 || boxWidth <= 0 || boxHeight <= 0)
    return { x: 0, y: 0, width: 0, height: 0 };
  const scale = Math.min(boxWidth / desktopWidth, boxHeight / desktopHeight);
  const width = desktopWidth * scale;
  const height = desktopHeight * scale;
  return { x: (boxWidth - width) / 2, y: (boxHeight - height) / 2, width, height };
}

export interface Renderer {
  readonly kind: 'webgl' | '2d';
  draw(frame: Frame): void;
  destroy(): void;
}

const VERTEX = `
attribute vec2 a_position;
varying vec2 v_texcoord;
void main() {
  v_texcoord = vec2((a_position.x + 1.0) / 2.0, (1.0 - a_position.y) / 2.0);
  gl_Position = vec4(a_position, 0.0, 1.0);
}`;

const FRAGMENT = `
precision mediump float;
uniform sampler2D u_texture;
varying vec2 v_texcoord;
void main() {
  gl_FragColor = texture2D(u_texture, v_texcoord);
}`;

function shader(gl: WebGLRenderingContext, type: number, source: string): WebGLShader | null {
  const created = gl.createShader(type);
  if (!created) return null;
  gl.shaderSource(created, source);
  gl.compileShader(created);
  if (!gl.getShaderParameter(created, gl.COMPILE_STATUS)) {
    gl.deleteShader(created);
    return null;
  }
  return created;
}

// A canvas whose size is not the desktop's takes it; that clears it, so the texture or the
// picture starts over and the server's next frame of the full desktop fills it.
function resize(canvas: HTMLCanvasElement, frame: Frame): boolean {
  const { desktopWidth, desktopHeight } = frame.header;
  if (canvas.width === desktopWidth && canvas.height === desktopHeight) return false;
  canvas.width = desktopWidth;
  canvas.height = desktopHeight;
  return true;
}

function webgl(canvas: HTMLCanvasElement): Renderer | null {
  const gl = canvas.getContext('webgl', { alpha: false, antialias: false });
  if (!gl) return null;
  const vertex = shader(gl, gl.VERTEX_SHADER, VERTEX);
  const fragment = shader(gl, gl.FRAGMENT_SHADER, FRAGMENT);
  const program = gl.createProgram();
  if (!vertex || !fragment || !program) return null;
  gl.attachShader(program, vertex);
  gl.attachShader(program, fragment);
  gl.linkProgram(program);
  if (!gl.getProgramParameter(program, gl.LINK_STATUS)) return null;
  gl.useProgram(program);

  const quad = gl.createBuffer();
  gl.bindBuffer(gl.ARRAY_BUFFER, quad);
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]), gl.STATIC_DRAW);
  const position = gl.getAttribLocation(program, 'a_position');
  gl.enableVertexAttribArray(position);
  gl.vertexAttribPointer(position, 2, gl.FLOAT, false, 0, 0);

  const texture = gl.createTexture();
  gl.bindTexture(gl.TEXTURE_2D, texture);
  // Any desktop size, also one that is no power of two (WebGL 1).
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
  gl.pixelStorei(gl.UNPACK_ALIGNMENT, 1);

  return {
    kind: 'webgl',
    draw(frame) {
      const { x, y, width, height, desktopWidth, desktopHeight } = frame.header;
      if (resize(canvas, frame)) {
        gl.viewport(0, 0, desktopWidth, desktopHeight);
        gl.texImage2D(
          gl.TEXTURE_2D,
          0,
          gl.RGBA,
          desktopWidth,
          desktopHeight,
          0,
          gl.RGBA,
          gl.UNSIGNED_BYTE,
          null,
        );
      }
      if (width > 0 && height > 0)
        gl.texSubImage2D(
          gl.TEXTURE_2D,
          0,
          x,
          y,
          width,
          height,
          gl.RGBA,
          gl.UNSIGNED_BYTE,
          frame.pixels,
        );
      gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
    },
    destroy() {
      gl.deleteTexture(texture);
      gl.deleteBuffer(quad);
      gl.deleteProgram(program);
      gl.deleteShader(vertex);
      gl.deleteShader(fragment);
    },
  };
}

function canvas2d(canvas: HTMLCanvasElement): Renderer | null {
  const context = canvas.getContext('2d', { alpha: false });
  if (!context) return null;
  return {
    kind: '2d',
    draw(frame) {
      resize(canvas, frame);
      const { x, y, width, height } = frame.header;
      if (width === 0 || height === 0) return;
      const { buffer, byteOffset, byteLength } = frame.pixels;
      const pixels = new Uint8ClampedArray(buffer as ArrayBuffer, byteOffset, byteLength);
      context.putImageData(new ImageData(pixels, width, height), x, y);
    },
    destroy() {},
  };
}

// WebGL, else 2d; null when the canvas gives neither. A canvas keeps the first kind of context
// it gave: once WebGL came but its program did not build, there is no 2d one on it either.
export function createRenderer(canvas: HTMLCanvasElement): Renderer | null {
  return webgl(canvas) ?? canvas2d(canvas);
}
