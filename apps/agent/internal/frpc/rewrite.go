// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package frpc

import (
	"bytes"
	"path/filepath"
	"strings"

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

// frpsTLSName is the DNS name only the frps leaf carries (R-1112). As serverName it makes frpc
// take no other leaf under the enrollment root for frps. The agent sets it itself: an older agent
// refuses a key it does not know and stops frpc (checkServerConfig), and the agent comes from the
// server's repo, whose ca-issuer mints the name already. Counterpart: FRPS_TLS_NAME in
// apps/ca-issuer/app/config.py.
const frpsTLSName = "frps.adminhelper.invalid"

// withFrpsTLSName sets transport.tls.serverName in a server text that checkServerConfig passed:
// right after the [transport.tls] head, or in the root when the text sets its TLS keys there
// (checkServerConfig allows only one of the two). A text without TLS keys stays as it is. The
// server's text never sets serverName (checkServerConfig refuses it), so the key stands once.
func withFrpsTLSName(serverToml []byte) []byte {
	const value = `serverName = "` + frpsTLSName + `"`
	text, offset, rootTLS := string(serverToml), 0, false
	for rest, more := text, true; more; {
		var raw string
		raw, rest, more = strings.Cut(rest, "\n")
		end := offset + len(raw)
		offset = end + 1
		line := strings.Trim(raw, " ")
		if line == "[transport.tls]" {
			return []byte(text[:end] + "\n" + value + text[end:])
		}
		if strings.HasPrefix(line, "[") {
			break // the root ends at the first other table head
		}
		if strings.HasPrefix(line, "transport.tls.") {
			rootTLS = true
		}
	}
	if !rootTLS {
		return serverToml
	}
	return []byte("transport.tls." + value + "\n" + text)
}
