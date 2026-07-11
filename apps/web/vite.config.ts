// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

import { defineConfig } from 'vite';
import { svelte } from '@sveltejs/vite-plugin-svelte';
import path from 'node:path';

// Baseline Content-Security-Policy injected into the production index.html as a second
// line of defence: even a future XSS can't run inline scripts or exfiltrate the API keys
// / FRP tokens / webhook secrets the panel renders (3.97). Only in the build — the dev
// server needs HMR (inline scripts + ws), which a strict CSP would break. frame-ancestors
// is deliberately absent: it's ignored in a meta CSP and belongs in the gateway header.
const CSP = [
  "default-src 'self'",
  "script-src 'self'", // the Vite build emits no inline scripts (verified)
  "style-src 'self' 'unsafe-inline'", // components use inline style= attributes
  "img-src 'self' data:",
  "font-src 'self'",
  "connect-src 'self'",
  "object-src 'none'",
  "base-uri 'self'",
  "form-action 'self'",
].join('; ');

const cspMetaPlugin = {
  name: 'inject-csp-meta',
  transformIndexHtml(html: string, ctx: { server?: unknown }) {
    if (ctx.server) return html; // dev server → no CSP (HMR)
    return html.replace(
      '</head>',
      `  <meta http-equiv="Content-Security-Policy" content="${CSP}" />\n  </head>`,
    );
  },
};

export default defineConfig({
  plugins: [svelte(), cspMetaPlugin],
  resolve: {
    alias: {
      $lib: path.resolve(__dirname, './src/lib'),
      $modals: path.resolve(__dirname, './src/modals'),
    },
  },
  build: {
    // Waehrend der Migration lokal nach dist/ bauen.
    // Erst in Phase 11 auf '../server/frontend' umstellen (Dockerfile-Cutover).
    outDir: path.resolve(__dirname, './dist'),
    emptyOutDir: true,
    // No production sourcemaps: after the cutover to ../server/frontend they'd be served
    // publicly, exposing internal comments / auth-flow hints and easing client-logic
    // reconnaissance (3.102). Set true locally to debug a production build.
    sourcemap: false,
    target: 'es2022',
  },
  server: {
    port: 5173,
    proxy: {
      '/auth': 'http://localhost:8000',
      '/api': 'http://localhost:8000',
      '/health': 'http://localhost:8000',
    },
  },
});
