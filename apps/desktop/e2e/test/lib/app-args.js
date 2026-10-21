// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Start arguments of the app under test (tauri:options.args in wdio.conf.js and
// wdio.workspaces.conf.js). AH_E2E_WORKSPACE names the workspace the session opens;
// unset or empty opens the launcher, as a plain `adminhelper` does.

// The rule of WorkspaceId::parse in src-tauri/src/workspace.rs (^[a-z0-9-]{1,32}$),
// spelled out like ID_CHARS there. Checked here so a bad id fails while wdio loads the
// config, not after the build, when the app exits on the usage error.
const WORKSPACE_ID = /^[abcdefghijklmnopqrstuvwxyz0123456789-]{1,32}$/;

export function appArgs(env, variable = 'AH_E2E_WORKSPACE') {
  const id = env[variable];
  if (id === undefined || id === '') return [];
  if (!WORKSPACE_ID.test(id)) {
    throw new Error(
      `${variable}=${JSON.stringify(id)} is no workspace id: 1 to 32 characters of a-z, 0-9 and -`,
    );
  }
  return ['--workspace', id];
}

// The two multiremote sessions of wdio.workspaces.conf.js, each behind a tauri-driver of
// its own: wdio talks to --port, the driver starts WebKitWebDriver on --native-port.
// The first pair is tauri-driver's default, so the second has to differ in both.
const WORKSPACE_SESSIONS = [
  { name: 'wsA', variable: 'AH_E2E_WORKSPACE_A', port: 4444, nativePort: 4445 },
  { name: 'wsB', variable: 'AH_E2E_WORKSPACE_B', port: 4446, nativePort: 4447 },
];

export function workspaceSessions(env) {
  const sessions = WORKSPACE_SESSIONS.map((session) => {
    const args = appArgs(env, session.variable);
    // Without an id the session would open the launcher, not a workspace.
    if (args.length === 0) {
      throw new Error(`${session.variable} is not set: each session opens a workspace`);
    }
    return { ...session, args };
  });
  // The second process of a workspace exits on its lock (EXIT_TAKEN) before its session starts.
  const [a, b] = sessions;
  if (a.args[1] === b.args[1]) {
    throw new Error(`${a.variable} and ${b.variable} both name ${a.args[1]}: a workspace runs once`);
  }
  return sessions;
}
