// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Live: open SSH / Web / RDP connections that each resolve THROUGH an FRP STCP
// tunnel. The app enrolls a device cert (setup), logs in, AppShell auto-starts
// the visitor tunnels, and opening each linked connection sends ssh / the browser
// / xfreerdp3 to the tunnel's local port — desktop frpc visitor → frps → agent
// frpc server → the real target container. All three paths are verified at the
// target containers by desktop_e2e_connect_tunnel.sh.
// Before the login the spec holds the web tunnel's visitor port on 127.0.0.1 (R-0430):
// the desktop has to give that visitor a local port of its fallback range, frpc has to
// listen there, and the web connection has to resolve to it.

import net from 'node:net';
import { adminTunnels, login, clickItemByName, jsClick } from '../lib/live.js';

const SERVER_URL = process.env.AH_SERVER_URL;
const ENROLL_TOKEN = process.env.AH_ENROLL_TOKEN;

// The web tunnel and its connection, as desktop_e2e_connect_tunnel.sh seeds them. Its port and
// not the SSH or RDP one: the probe below reaches the target, and sshd and xrdp log a bare TCP
// connection, which the orchestrator would count as the GUI's open; nginx logs requests only.
const HELD_TUNNEL = 'e2e-web-tun';
const HELD_CONNECTION = 'web-tunnel';
// FALLBACK_PORTS in port_registry.rs.
const FALLBACK_FIRST = 23000;
const FALLBACK_LAST = 23999;

// A Tauri command through the bridge; a rejection fails the spec with its message.
async function invoke(cmd, args = {}) {
  const out = await browser.executeAsync(
    (c, a, done) => {
      window.__TAURI__.core
        .invoke(c, a)
        .then((value) => done({ value }))
        .catch((e) => done({ error: String((e && e.message) || e) }));
    },
    cmd,
    args,
  );
  if (out.error !== undefined) throw new Error(`${cmd} failed: ${out.error}`);
  return out.value;
}

// A listener on 127.0.0.1:`port` that drops every connection it gets.
function hold(port) {
  return new Promise((resolve, reject) => {
    const server = net.createServer((socket) => socket.destroy());
    server.once('error', reject);
    server.listen({ host: '127.0.0.1', port }, () => resolve(server));
  });
}

// Whether 127.0.0.1:`port` takes a TCP connection; closes it right away.
function accepts(port) {
  return new Promise((resolve) => {
    const socket = net.connect({ host: '127.0.0.1', port });
    const done = (ok) => {
      socket.destroy();
      resolve(ok);
    };
    socket.setTimeout(3000, () => done(false));
    socket.once('connect', () => done(true));
    socket.once('error', () => done(false));
  });
}

// Where the visitor of the running frpc at `serverPort` listens, once tunnel_status lists it.
async function bindingAt(serverPort) {
  let status;
  try {
    await browser.waitUntil(
      async () => {
        status = await invoke('tunnel_status');
        return !!status?.bindings?.some((b) => b.serverPort === serverPort);
      },
      { timeout: 20000, interval: 500 },
    );
  } catch (error) {
    throw new Error(
      `tunnel_status never listed a visitor at server port ${serverPort}: ${JSON.stringify(status)}`,
      { cause: error },
    );
  }
  return status.bindings.find((b) => b.serverPort === serverPort);
}

describe('Open SSH/Web/RDP connections over FRP tunnels', () => {
  let heldPort;
  let held;

  before(async () => {
    const tunnel = adminTunnels().find((t) => t.name === HELD_TUNNEL);
    if (!tunnel?.visitorPort) {
      throw new Error(`the server lists no STCP tunnel ${HELD_TUNNEL} with a visitor port`);
    }
    heldPort = tunnel.visitorPort;
    try {
      held = await hold(heldPort);
    } catch (error) {
      throw new Error(`could not hold the visitor port ${heldPort} on 127.0.0.1`, {
        cause: error,
      });
    }
  });

  after(async () => {
    if (held) await new Promise((resolve) => held.close(() => resolve()));
  });

  it('enrolls, the tunnels connect, and opens each connection through its tunnel', async () => {
    await $('.login-card').waitForExist({ timeout: 20000 });

    // Device enrollment (setup) via the bridge with explicit self-signed trust.
    const err = await browser.executeAsync(
      (url, token, done) => {
        window.__TAURI__.core
          .invoke('enroll_with_token', { serverUrl: url, token, allowSelfSigned: true })
          .then(() => done(null))
          .catch((e) => done(String((e && e.message) || e)));
      },
      SERVER_URL,
      ENROLL_TOKEN,
    );
    expect(err).toBe(null);

    // Shared helper — the inline login was duplicated across the tunnel specs (2.16).
    await login();

    // The seeded tunnels auto-start; wait until the visitor side is connected.
    const indicator = await $('.tunnel-indicator');
    await indicator.waitForExist({ timeout: 15000 });
    await browser.waitUntil(
      async () => (await indicator.getAttribute('data-status')) === 'connected',
      { timeout: 40000, timeoutMsg: 'the tunnel indicator never reached "connected"' },
    );

    // The held port's visitor went to the fallback range. A port map entry from an earlier run
    // at the server port moves too: the first start rechecks it, and it does not bind now.
    const binding = await bindingAt(heldPort);
    expect(binding.localPort).not.toBe(heldPort);
    expect(binding.localPort).toBeGreaterThanOrEqual(FALLBACK_FIRST);
    expect(binding.localPort).toBeLessThanOrEqual(FALLBACK_LAST);
    // frpc listens there once it has logged in to frps.
    await browser.waitUntil(() => accepts(binding.localPort), {
      timeout: 30000,
      interval: 500,
      timeoutMsg: `nothing took a TCP connection on the local port ${binding.localPort}`,
    });
    // The linked connection resolves to that port, as the connect flow asks for it.
    const connection = (await invoke('fetch_connections_jwt')).find(
      (c) => c.name === HELD_CONNECTION,
    );
    expect(connection).toBeDefined();
    const tunnels = await invoke('fetch_tunnels');
    const local = `http://127.0.0.1:${binding.localPort}`;
    expect(await invoke('resolve_connection', { connection, tunnels })).toMatchObject({
      viaTunnel: true,
      connection: { host: '127.0.0.1', port: binding.localPort, url: local },
    });

    const nav = await $$('.sidebar-nav .sidebar-item');
    await nav[1].click(); // connections
    await $('.card').waitForExist({ timeout: 15000 });

    // SSH over tunnel (no prompt) and Web over tunnel (xdg-open shim).
    await clickItemByName('.card', '.card-title', 'ssh-tunnel');
    await browser.pause(2000);
    await clickItemByName('.card', '.card-title', 'web-tunnel');
    await browser.pause(2000);

    // RDP over tunnel — the desktop shows a password prompt first.
    await clickItemByName('.card', '.card-title', 'rdp-tunnel');
    await $('.pw-panel').waitForExist({ timeout: 10000 });
    await $('.pw-panel input[type="password"]').setValue('e2e');
    await jsClick(await $('.pw-panel .btn.primary'));

    // Let all three traverse their tunnels (verified at the target containers).
    await browser.pause(7000);
  });
});
