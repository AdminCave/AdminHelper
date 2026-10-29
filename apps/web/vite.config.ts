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
  // No inline scripts: neither the Vite bundle (verified) nor index.html, whose theme init
  // before the first paint is the file public/theme-init.js.
  "script-src 'self'",
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
    // Vite builds into dist/; the root Dockerfile (stage frontend-build) copies dist/ into
    // the server image, which serves it under frontend/.
    outDir: path.resolve(__dirname, './dist'),
    emptyOutDir: true,
    // No production sourcemaps: the server image serves the build publicly, so they would
    // expose internal comments / auth-flow hints and ease client-logic
    // reconnaissance (3.102). Set true locally to debug a production build.
    sourcemap: false,
    target: 'es2022',
  },
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://127.0.0.1:8080',
    },
  },
  // `vite preview` (Playwright project chromium-build) serves the build with the CSP as a
  // header, like the server (script-src 'self' there too, apps/server/app/main.py). A
  // header covers the whole document; the meta element above only covers what follows it
  // before </head> (CSP3 §3.3), so an inline script ahead of it would pass unnoticed.
  preview: {
    headers: { 'Content-Security-Policy': CSP },
  },
});
