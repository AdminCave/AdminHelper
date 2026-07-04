// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package frpc

import (
	"strings"
	"testing"
)

func TestRewriteIdentityPathsTo(t *testing.T) {
	toml := `certFile = "/etc/adminhelper/identity/agent.crt"` + "\n" +
		`keyFile = "/etc/adminhelper/identity/agent.key"` + "\n" +
		`trustedCaFile = "/etc/adminhelper/identity/ca.crt"`

	// Windows layout (already forward-slashed by the caller's filepath.ToSlash):
	// the server-baked Linux dir is replaced by the platform dir.
	out := string(rewriteIdentityPathsTo([]byte(toml), "C:/ProgramData/AdminHelper/identity"))
	if !strings.Contains(out, `certFile = "C:/ProgramData/AdminHelper/identity/agent.crt"`) {
		t.Errorf("cert path not rewritten: %s", out)
	}
	if !strings.Contains(out, `keyFile = "C:/ProgramData/AdminHelper/identity/agent.key"`) {
		t.Errorf("key path not rewritten: %s", out)
	}
	if strings.Contains(out, "/etc/adminhelper/identity/") {
		t.Errorf("server path still present: %s", out)
	}

	// Linux layout: target == source, so the rewrite must be a no-op.
	if got := string(rewriteIdentityPathsTo([]byte(toml), "/etc/adminhelper/identity")); got != toml {
		t.Errorf("linux rewrite must be a no-op, got: %s", got)
	}
}
