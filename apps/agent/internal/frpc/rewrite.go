// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package frpc

import (
	"bytes"
	"path/filepath"

	"adminhelper-agent/internal/config"
)

// serverIdentityDir is the fixed path the server bakes into the agent's frpc.toml
// (config_generator.py _AGENT_IDENTITY_DIR). It is a Linux path; on Windows the
// enrolled identity lives under %ProgramData%\AdminHelper\identity, so the agent
// must rewrite it to its real per-platform directory before frpc reads the file —
// mirroring the desktop's rewrite in frpc.rs. On Linux target == source, no-op.
const serverIdentityDir = `"/etc/adminhelper/identity/`

// rewriteIdentityPaths rewrites the server-baked identity dir in a frpc.toml to
// this platform's actual enrolled-identity directory.
func rewriteIdentityPaths(toml []byte) []byte {
	return rewriteIdentityPathsTo(toml, filepath.ToSlash(config.AgentPkiDir()))
}

// rewriteIdentityPathsTo takes an already forward-slashed target dir (the caller
// applies filepath.ToSlash) so the substitution is platform-independent + testable.
func rewriteIdentityPathsTo(toml []byte, slashDir string) []byte {
	return bytes.ReplaceAll(toml, []byte(serverIdentityDir), []byte(`"`+slashDir+`/`))
}
