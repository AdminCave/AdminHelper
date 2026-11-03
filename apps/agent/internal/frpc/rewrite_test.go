// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package frpc

import (
	"os"
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

// R-1112: frpc asks frps for the name only its leaf carries, in the block the server's text
// already uses for TLS.
func TestWithFrpsTLSNameSetsTheNameInTheTLSHead(t *testing.T) {
	in := "serverAddr = \"203.0.113.10\"\n\n[transport.tls]\nenable = true\ntrustedCaFile = \"/x/ca.crt\"\n\n[[proxies]]\nname = \"ssh\"\n"
	want := "serverAddr = \"203.0.113.10\"\n\n[transport.tls]\nserverName = \"frps.adminhelper.invalid\"\nenable = true\ntrustedCaFile = \"/x/ca.crt\"\n\n[[proxies]]\nname = \"ssh\"\n"
	if got := string(withFrpsTLSName([]byte(in))); got != want {
		t.Errorf("withFrpsTLSName = %q, want %q", got, want)
	}
}

func TestWithFrpsTLSNameSetsTheNameInTheRootNextToRootTLSKeys(t *testing.T) {
	in := "serverAddr = \"203.0.113.10\"\ntransport.tls.enable = true\n\n[[proxies]]\nname = \"ssh\"\n"
	want := "transport.tls.serverName = \"frps.adminhelper.invalid\"\n" + in
	if got := string(withFrpsTLSName([]byte(in))); got != want {
		t.Errorf("withFrpsTLSName = %q, want %q", got, want)
	}
}

// A text without TLS keys stays as it is; so does one whose only transport.tls. key sits in a
// proxy table, which is not frps' TLS.
func TestWithFrpsTLSNameLeavesATextWithoutTLSKeys(t *testing.T) {
	for _, in := range []string{
		"serverAddr = \"203.0.113.10\"\n\n[[proxies]]\nname = \"ssh\"\n",
		"serverAddr = \"203.0.113.10\"\n\n[[proxies]]\nname = \"ssh\"\ntransport.tls.enable = true\n",
		"",
	} {
		if got := string(withFrpsTLSName([]byte(in))); got != in {
			t.Errorf("withFrpsTLSName(%q) = %q, want it unchanged", in, got)
		}
	}
}

// The server's real text (testdata, the one checkServerConfig passes) gets the name once, inside
// its [transport.tls] block and before the first proxy.
func TestWithFrpsTLSNameOnTheServersText(t *testing.T) {
	data, err := os.ReadFile("testdata/server_frpc.toml")
	if err != nil {
		t.Fatal(err)
	}
	if err := checkServerConfig(data); err != nil {
		t.Fatalf("testdata no longer passes checkServerConfig: %v", err)
	}
	out := string(withFrpsTLSName(data))
	line := `serverName = "frps.adminhelper.invalid"`
	if strings.Count(out, line) != 1 {
		t.Fatalf("serverName %d times in %q, want once", strings.Count(out, line), out)
	}
	head, at, proxy := strings.Index(out, "[transport.tls]\n"), strings.Index(out, line), strings.Index(out, "[[proxies]]")
	if head < 0 || at != head+len("[transport.tls]\n") || at > proxy {
		t.Errorf("serverName not right after [transport.tls] (head %d, name %d, proxy %d): %q", head, at, proxy, out)
	}
	if strings.Replace(out, line+"\n", "", 1) != string(data) {
		t.Errorf("more than the serverName line changed: %q", out)
	}
}
