// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Start arguments of the app under test (tauri:options.args in wdio.conf.js).
// AH_E2E_WORKSPACE names the workspace the session opens; unset or empty opens the
// launcher, as a plain `adminhelper` does.

// The rule of WorkspaceId::parse in src-tauri/src/workspace.rs (^[a-z0-9-]{1,32}$),
// spelled out like ID_CHARS there. Checked here so a bad id fails while wdio loads the
// config, not after the build, when the app exits on the usage error.
const WORKSPACE_ID = /^[abcdefghijklmnopqrstuvwxyz0123456789-]{1,32}$/;

export function appArgs(env) {
  const id = env.AH_E2E_WORKSPACE;
  if (id === undefined || id === '') return [];
  if (!WORKSPACE_ID.test(id)) {
    throw new Error(
      `AH_E2E_WORKSPACE=${JSON.stringify(id)} is no workspace id: 1 to 32 characters of a-z, 0-9 and -`,
    );
  }
  return ['--workspace', id];
}
