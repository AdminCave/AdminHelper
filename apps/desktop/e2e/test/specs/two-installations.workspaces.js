// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Live, two workspace processes at the same time (wdio.workspaces.conf.js, multiremote): wsA
// opens "Standard" (AH_E2E_WORKSPACE_A=standard), migrated with the URL of stack A, and wsB
// "Kunde B" (AH_E2E_WORKSPACE_B), which workspace-add-server.live.js made for stack B.
// Orchestrated by scripts/tests/desktop_e2e_workspaces.sh: two installations with two PKIs,
// seeded alike, each with the STCP tunnel TUNNEL to an SSH target of its own, linked to the
// connection CONNECTION; both gave that tunnel the same visitor port.
// A workspace runs in one process: a second start of Standard ends on its lock. wsB holds no
// device identity while wsA registers. Then each window registers this device at its stack,
// signs in and starts its tunnel: both frpc run side by side, the visitor at the same server
// port on different local ports, and each window opens its SSH connection through its own
// tunnel. That each target saw only the connection of its own window, the orchestrator checks
// at the targets.

import fs from 'node:fs';
import { spawn } from 'node:child_process';
import { application } from '../../wdio.conf.js';

// As desktop_e2e_workspaces.sh seeds them in both installations; the server names the
// visitor "<tunnel>-visitor" (generate_visitor_toml).
const TUNNEL = 'e2e-ssh-tun';
const VISITOR = `${TUNNEL}-visitor`;
const CONNECTION = 'ssh-tunnel';
// The workspace the migration made: it keeps the keyring keys without a prefix, Kunde B has
// its own prefix, and the identity of one must stay out of the other's sight.
const STANDARD = 'standard';
// As workspace-add-server.live.js names it.
const NAME_B = 'Kunde B';
// EXIT_TAKEN in workspace.rs: a start for a workspace another process holds.
const EXIT_TAKEN = 3;
// FALLBACK_PORTS in port_registry.rs.
const FALLBACK_FIRST = 23000;
const FALLBACK_LAST = 23999;

// What the orchestrator hands each window: its stack and its workspace.
const ENV = {
  A: {
    workspace: 'AH_E2E_WORKSPACE_A',
    url: 'AH_E2E_SERVER_URL_A',
    token: 'AH_ENROLL_TOKEN_A',
    pass: 'AH_ADMIN_PASS_A',
  },
  B: {
    workspace: 'AH_E2E_WORKSPACE_B',
    url: 'AH_E2E_SERVER_URL_B',
    token: 'AH_ENROLL_TOKEN_B',
    pass: 'AH_ADMIN_PASS_B',
  },
};

// One window: its session, the name it goes by in messages, and what the env gives it. Built
// in `before`: wdio puts the sessions wsA and wsB in place before the specs run.
function windowOf(label, session, key) {
  const value = (name) => {
    const v = process.env[name];
    if (!v) {
      throw new Error(
        `${name} is not set: run the live specs through scripts/tests/desktop_e2e_workspaces.sh`,
      );
    }
    return v;
  };
  const env = ENV[key];
  return {
    label,
    session,
    id: value(env.workspace),
    url: value(env.url),
    token: value(env.token),
    user: value('AH_ADMIN_USER'),
    pass: value(env.pass),
  };
}

// A Tauri command in the window `w`; a rejection fails the spec with its message. It comes
// back as { rejected }: webdriver takes a script result with an `error` key for a failed
// command (logout.live.js).
async function invoke(w, cmd, args = {}) {
  const out = await w.session.executeAsync(
    (c, a, done) => {
      window.__TAURI__.core
        .invoke(c, a)
        .then((value) => done({ value }))
        .catch((e) => done({ rejected: String((e && e.message) || e) }));
    },
    cmd,
    args,
  );
  if (out.rejected !== undefined) throw new Error(`${w.label}: ${cmd} failed: ${out.rejected}`);
  return out.value;
}

// Registers the device of the window at its stack: device setup, not the flow under test, so
// through the bridge with explicit trust in the stack's own PKI, as the tunnel specs do.
async function enroll(w) {
  await invoke(w, 'enroll_with_token', { serverUrl: w.url, token: w.token, allowSelfSigned: true });
}

// Signs in through the login card: the URL of the workspace is fixed, so only user and password.
async function signIn(w) {
  const s = w.session;
  await s.$('.login-card input[type="password"]').waitForExist({ timeout: 20000 });
  await s.$('.login-card input[type="text"]').setValue(w.user);
  await s.$('.login-card input[type="password"]').setValue(w.pass);
  // A JS click, not Enter: the keys of one window must not depend on which of the two has the
  // focus under Xvfb.
  await s.execute((node) => node.click(), await s.$('.login-card button[type="submit"]'));
  try {
    await s.$('.sidebar-nav').waitForExist({ timeout: 20000 });
  } catch (error) {
    const shown = await s.$('.login-card .login-error');
    const why = (await shown.isExisting()) ? await shown.getText() : 'no message';
    throw new Error(`${w.label}: the sign-in never reached the app shell: ${why}`, {
      cause: error,
    });
  }
}

// The tunnels start on their own after the sign-in; the indicator goes connecting → connected.
async function waitForTunnelConnected(w) {
  const indicator = await w.session.$('.tunnel-indicator');
  await indicator.waitForExist({ timeout: 15000 });
  await w.session.waitUntil(
    async () => (await indicator.getAttribute('data-status')) === 'connected',
    { timeout: 40000, timeoutMsg: `${w.label}: the tunnel indicator never reached "connected"` },
  );
}

// Where the visitor VISITOR of the window's frpc listens, once tunnel_status lists it.
async function bindingOf(w) {
  let status;
  try {
    await w.session.waitUntil(
      async () => {
        status = await invoke(w, 'tunnel_status');
        return !!status?.bindings?.some((b) => b.name === VISITOR);
      },
      { timeout: 20000, interval: 500 },
    );
  } catch (error) {
    throw new Error(
      `${w.label}: tunnel_status never listed ${VISITOR}: ${JSON.stringify(status)}`,
      { cause: error },
    );
  }
  return status.bindings.find((b) => b.name === VISITOR);
}

// Whether something listens on `port` of 127.0.0.1, as the kernel's table of IPv4 sockets has
// it: a LISTEN entry (st 0A) at 127.0.0.1, where frpc binds its visitors (remap_visitors in
// frpc.rs), or at 0.0.0.0, which holds the port as well. Read only: a connection would reach
// the SSH target through frpc, whose log the orchestrator reads for the open through the GUI
// alone, and a listen of our own could take the port from frpc before it binds. Linux only, as
// WebKitWebDriver is.
function held(port) {
  // Address and port as the table writes them: the address in hex as the kernel stores it,
  // the port in four upper-case hex digits.
  const hex = port.toString(16).toUpperCase().padStart(4, '0');
  const wanted = new Set([`0100007F:${hex}`, `00000000:${hex}`]);
  return fs
    .readFileSync('/proc/net/tcp', 'utf8')
    .split('\n')
    .slice(1) // the header
    .some((line) => {
      const [, local, , st] = line.trim().split(/\s+/);
      return st === '0A' && wanted.has(local);
    });
}

// Starts the app with `args` beside the sessions and resolves to how it ended. One still
// running after `ms` is killed: a start that does not end showed a window. The tail of its
// stderr, where it logs why it ended, goes into the result for the failure message.
function runApp(args, ms) {
  return new Promise((resolve, reject) => {
    const child = spawn(application, args, { stdio: ['ignore', 'ignore', 'pipe'] });
    let stderr = '';
    child.stderr.on('data', (chunk) => {
      stderr = (stderr + chunk).slice(-2000);
    });
    const timer = setTimeout(() => child.kill('SIGKILL'), ms);
    child.once('error', (error) => {
      clearTimeout(timer);
      reject(error);
    });
    child.once('close', (code, signal) => {
      clearTimeout(timer);
      resolve({ code, signal, stderr });
    });
  });
}

describe('Two installations side by side: Standard at stack A, Kunde B at stack B', () => {
  let A;
  let B;

  before(() => {
    A = windowOf('wsA', wsA, 'A');
    B = windowOf('wsB', wsB, 'B');
  });

  it('each window serves its own workspace at the URL of its stack', async () => {
    expect(A.id).toBe(STANDARD);
    for (const w of [A, B]) {
      await w.session.$('.login-card').waitForExist({ timeout: 20000 });
      const { launcher, workspace } = await invoke(w, 'workspace_context');
      expect(launcher).toBe(false);
      expect(workspace).toMatchObject({ id: w.id, kind: 'server' });
      expect(new URL(workspace.url).origin).toBe(new URL(w.url).origin);
      // The login shows that URL and has no field for another one.
      const shown = await w.session.$('[data-testid="workspace-url"]');
      await shown.waitForExist({ timeout: 10000 });
      expect(await shown.getText()).toBe(workspace.url);
      expect(await w.session.$('.login-card input[type="url"]').isExisting()).toBe(false);
    }
    expect((await invoke(B, 'workspace_context')).workspace.name).toBe(NAME_B);
  });

  it('a second start of Standard ends with exit 3 while wsA holds it', async () => {
    const run = await runApp(['--workspace', A.id], 30000);
    if (run.code !== EXIT_TAKEN) {
      throw new Error(
        `the second start of ${A.id} ended with ${run.code ?? run.signal}, not ${EXIT_TAKEN}: ${run.stderr}`,
      );
    }
    // wsA kept its workspace.
    expect((await invoke(A, 'workspace_context')).workspace.id).toBe(A.id);
  });

  it('wsB holds no device identity while wsA registers; then each registers at its stack', async () => {
    expect(await invoke(A, 'is_device_enrolled')).toBe(false);
    expect(await invoke(B, 'is_device_enrolled')).toBe(false);
    await enroll(A);
    expect(await invoke(A, 'is_device_enrolled')).toBe(true);
    expect(await invoke(B, 'is_device_enrolled')).toBe(false);
    await enroll(B);
    expect(await invoke(B, 'is_device_enrolled')).toBe(true);
    expect(await invoke(A, 'is_device_enrolled')).toBe(true);
  });

  // One after the other, and one window per it: wsA's visitor has its local port before wsB
  // asks for one, and the waits of one sign-in stay below Mocha's timeout.
  it('wsA signs in, and its tunnel connects', async () => {
    await signIn(A);
    await waitForTunnelConnected(A);
  });

  it('wsB signs in beside wsA, and its tunnel connects', async () => {
    await signIn(B);
    await waitForTunnelConnected(B);
  });

  it('both frpc run the visitor at the same server port, on different local ports', async () => {
    // Both installations gave the tunnel the same visitor port.
    const visitorPort = async (w) => {
      const port = (await invoke(w, 'fetch_tunnels')).find((t) => t.name === TUNNEL)?.visitorPort;
      if (!port) {
        throw new Error(`${w.label}: the server lists no tunnel ${TUNNEL} with a visitor port`);
      }
      return port;
    };
    const portA = await visitorPort(A);
    const portB = await visitorPort(B);
    expect(portB).toBe(portA);

    const bindingA = await bindingOf(A);
    const bindingB = await bindingOf(B);
    expect(bindingA.serverPort).toBe(portA);
    expect(bindingB.serverPort).toBe(portA);
    expect(bindingB.localPort).not.toBe(bindingA.localPort);
    // The port map gives wsA's local port to wsA alone: wsB's visitor went to the fallback range.
    expect(bindingB.localPort).toBeGreaterThanOrEqual(FALLBACK_FIRST);
    expect(bindingB.localPort).toBeLessThanOrEqual(FALLBACK_LAST);

    // Both frpc listen, wsA's still after wsB started its own.
    for (const [w, binding] of [
      [A, bindingA],
      [B, bindingB],
    ]) {
      expect(await invoke(w, 'tunnel_status')).toMatchObject({ running: true });
      await w.session.waitUntil(() => held(binding.localPort), {
        timeout: 30000,
        interval: 500,
        timeoutMsg: `${w.label}: nothing listens on the local port ${binding.localPort}`,
      });
    }
  });

  it('each window opens its SSH connection through its own tunnel', async () => {
    for (const w of [A, B]) {
      const binding = await bindingOf(w);
      // The connection resolves to the local port of this window's own visitor.
      const connection = (await invoke(w, 'fetch_connections_jwt')).find(
        (c) => c.name === CONNECTION,
      );
      expect(connection).toBeDefined();
      const tunnels = await invoke(w, 'fetch_tunnels');
      expect(await invoke(w, 'resolve_connection', { connection, tunnels })).toMatchObject({
        viaTunnel: true,
        connection: { host: '127.0.0.1', port: binding.localPort },
      });

      // Through the GUI: the card spawns ssh to that port (seen at the target by the orchestrator).
      const s = w.session;
      await s.$('.sidebar-nav [data-nav="connections"]').click();
      await s.$('.card').waitForExist({ timeout: 15000 });
      // Queried anew on each pass: a render between the listing and the click stales a handle.
      await s.waitUntil(
        async () => {
          try {
            for (const card of await s.$$('.card')) {
              if ((await card.$('.card-title').getText()) === CONNECTION) {
                await card.click();
                return true;
              }
            }
          } catch {
            return false;
          }
          return false;
        },
        { timeout: 15000, timeoutMsg: `${w.label}: no card "${CONNECTION}" to click` },
      );
    }
    // Let both ssh reach their targets before the sessions end.
    await A.session.pause(5000);
  });
});
