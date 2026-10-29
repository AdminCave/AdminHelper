// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package frpc

import (
	"context"
	"maps"
	"os"
	"strings"
	"testing"

	"adminhelper-agent/internal/config"
)

// serverFixture is an output of generate_frpc_toml byte for byte: an stcp tunnel with
// extra_config and an https tunnel with custom domains. The server's
// test_config_generator.py compares it with the generator, so a change of the generator's
// output shows there until fixture and checkServerConfig follow.
func serverFixture(t *testing.T) []byte {
	t.Helper()
	data, err := os.ReadFile("testdata/server_frpc.toml")
	if err != nil {
		t.Fatal(err)
	}
	return data
}

// The generator's output passes, and so do the server texts the sync and apply tests use and a
// proxy with each float form Python's str(float) writes.
func TestServerConfigAcceptsTheGeneratorForm(t *testing.T) {
	texts := map[string][]byte{
		"fixture":        serverFixture(t),
		"tunnelToml":     tunnelToml,
		"twoTunnelsToml": twoTunnelsToml,
		"bundleToml":     bundleToml,
		"withToken":      withToken("rotated-token"),
		"without a tunnel": []byte("serverAddr = \"203.0.113.10\"\nserverPort = 7000\n\n" +
			"auth.method = \"token\"\nauth.token = \"frps-token\"\n"),
		"floats": []byte("serverAddr = \"203.0.113.10\"\n\n[[proxies]]\nname = \"ssh\"\n" +
			"a = 1.5\nb = 1e+20\nc = inf\nd = -inf\ne = nan\nf = 1e-05\ng = -0.5\nh = 1.5e+20\n" +
			"i = -7\nj = []\n"),
	}
	for name, toml := range texts {
		if err := checkServerConfig(toml); err != nil {
			t.Errorf("%s: checkServerConfig = %v, want nil", name, err)
		}
	}
}

// Each line out of the generator's form is refused, and the error names its line and, where the
// line has one, its key. common and proxy frame a line in the root and in a proxy.
func TestServerConfigRefusesOtherForms(t *testing.T) {
	const common = "serverAddr = \"203.0.113.10\"\nserverPort = 7000\n"
	const proxy = "\n[[proxies]]\nname = \"ssh\"\n"
	cases := map[string]struct{ toml, want string }{
		"[common]":                {common + "\n[common]\nserver_port = 7000\n" + proxy, "line 4: the table [common]"},
		"multi-line literal":      {common + "user = '''\n[common]\nend = 1'''\n" + proxy, "line 3: the value of user "},
		"multi-line basic string": {common + "user = \"\"\"x\"\"\"\n" + proxy, "line 3: the value of user "},
		"literal string":          {common + "user = 'x'\n" + proxy, "line 3: the value of user "},
		"inline table":            {common + "auth = { method = \"token\" }\n" + proxy, "line 3: the value of auth "},
		"comment line":            {common + "# a comment\n" + proxy, "line 3: not a line of the form key = value"},
		"comment after a value":   {common + proxy + "localPort = 22 # ssh\n", "line 6: the value of localPort "},
		"escape":                  {common + "user = \"a\\\"b\"\n" + proxy, "line 3: the value of user "},
		"{{ in a value":           {common + proxy + "localIP = \"{{ .Envs.IP }}\"\n", "line 6: the line of localIP contains"},
		"carriage return":         {common + "user = \"host-01\"\r\n" + proxy, "line 3: the line of user contains a control"},
		"tab":                     {common + "user\t= \"host-01\"\n" + proxy, "line 3: the line contains a control"},
		"quoted key":              {common + "\"user\" = \"host-01\"\n" + proxy, "line 3: not a line of the form key = value"},
		"includes":                {common + "includes = [\"/tmp/x.toml\"]\n" + proxy, "line 3: includes is no key"},
		"log.to":                  {common + "log.to = \"/tmp/frpc.log\"\n" + proxy, "line 3: log.to is no key"},
		"auth.tokenSource.type":   {common + "auth.tokenSource.type = \"file\"\n" + proxy, "line 3: auth.tokenSource.type is no key"},
		"store.path":              {common + "store.path = \"/tmp/store.json\"\n" + proxy, "line 3: store.path is no key"},
		"webServer.port":          {common + "webServer.port = 7400\n" + proxy, "line 3: webServer.port is no key"},
		"loginFailExit":           {common + "loginFailExit = true\n" + proxy, "line 3: loginFailExit is no key"},
		"LOGINFAILEXIT":           {common + "LOGINFAILEXIT = true\n" + proxy, "line 3: LOGINFAILEXIT is no key"},
		"start":                   {common + "start = [\"ssh\"]\n" + proxy, "line 3: start is no key"},
		"virtualNet.address":      {common + "virtualNet.address = \"198.51.100.1/24\"\n" + proxy, "line 3: virtualNet.address is no key"},
		"transport.tls.serverName": {common + "\n[transport.tls]\nenable = true\nserverName = \"frps\"\n" + proxy,
			"line 6: transport.tls.serverName is no key"},
		"auth.method oidc":                {common + "auth.method = \"oidc\"\n" + proxy, `line 3: auth.method must be "token"`},
		"[[visitors]]":                    {common + proxy + "\n[[visitors]]\nname = \"v\"\n", "line 7: the table [[visitors]]"},
		"[proxies.plugin]":                {common + proxy + "\n[proxies.plugin]\ntype = \"static_file\"\n", "line 7: the table [proxies.plugin]"},
		"[log]":                           {common + "\n[log]\nto = \"/tmp/frpc.log\"\n" + proxy, "line 4: the table [log]"},
		"second [transport.tls]":          {common + "\n[transport.tls]\nenable = true\n\n[transport.tls]\n" + proxy, "line 7: a second [transport.tls]"},
		"[transport.tls] after a proxy":   {common + proxy + "\n[transport.tls]\nenable = true\n", "line 7: [transport.tls] after a [[proxies]]"},
		"[transport.tls] after root keys": {common + "transport.tls.enable = true\n\n[transport.tls]\n" + proxy, "line 5: [transport.tls] after transport.tls keys"},
		"duplicate root key":              {common + "serverPort = 7001\n" + proxy, "line 3: serverPort is set twice"},
		"duplicate under [transport.tls]": {common + "\n[transport.tls]\nenable = true\nenable = false\n" + proxy, "line 6: transport.tls.enable is set twice"},
		"duplicate proxy key":             {common + proxy + "name = \"rdp\"\n", "line 6: name is set twice"},
		"duplicate proxy key, other case": {common + proxy + "Name = \"rdp\"\n", "line 6: Name is set twice"},
		"prefix conflict":                 {common + proxy + "transport = 1\ntransport.x = 2\n", "line 7: transport.x is set twice, or as a value and a table"},
		"prefix conflict, table first":    {common + proxy + "transport.x = 2\ntransport = 1\n", "line 7: transport is set twice, or as a value and a table"},
		"empty key segment":               {common + proxy + "transport..x = 2\n", "line 6: not a line of the form key = value"},
		"no spaces around =":              {common + "user=\"host-01\"\n" + proxy, "line 3: not a line of the form key = value"},
		"leading zero":                    {common + proxy + "localPort = 022\n", "line 6: the value of localPort "},
		"integer with _":                  {common + proxy + "localPort = 2_2\n", "line 6: the value of localPort "},
		"date":                            {common + proxy + "since = 2026-10-22\n", "line 6: the value of since "},
		"invalid UTF-8":                   {common + "user = \"\xff\"\n" + proxy, "line 3: the line of user is not valid UTF-8"},
	}
	for name, tc := range cases {
		t.Run(name, func(t *testing.T) {
			err := checkServerConfig([]byte(tc.toml))
			if err == nil {
				t.Fatal("checkServerConfig = nil, want the text refused")
			}
			if !strings.Contains(err.Error(), tc.want) {
				t.Errorf("checkServerConfig = %q, want it to contain %q", err, tc.want)
			}
		})
	}
}

// A proxy carries no key of the plugin family in any case, as frp maps keys without regard to
// case; other extra_config keys, such as transport.useCompression, still pass.
func TestServerConfigRefusesProxyPlugins(t *testing.T) {
	const head = "serverAddr = \"203.0.113.10\"\nserverPort = 7000\n\n[[proxies]]\nname = \"ssh\"\n"
	for line, want := range map[string]string{
		"plugin.type = \"static_file\"": "line 6: plugin.type is a plugin key",
		"PLUGIN.type = \"x\"":           "line 6: PLUGIN.type is a plugin key",
		"Plugin.localPath = \"/x\"":     "line 6: Plugin.localPath is a plugin key",
		"plugin = \"x\"":                "line 6: plugin is a plugin key",
	} {
		t.Run(line, func(t *testing.T) {
			err := checkServerConfig([]byte(head + line + "\n"))
			if err == nil {
				t.Fatal("checkServerConfig = nil, want the plugin key refused")
			}
			if !strings.Contains(err.Error(), want) {
				t.Errorf("checkServerConfig = %q, want it to contain %q", err, want)
			}
		})
	}
	for name, toml := range map[string][]byte{
		"fixture":                  serverFixture(t),
		"transport.useCompression": []byte(head + "transport.useCompression = true\n"),
	} {
		if err := checkServerConfig(toml); err != nil {
			t.Errorf("%s: checkServerConfig = %v, want nil", name, err)
		}
	}
}

// A key with more segments than any frp field has is refused, without its text in the error;
// a key of maxKeySegments segments still passes.
func TestServerConfigRefusesKeysWithTooManySegments(t *testing.T) {
	const head = "serverAddr = \"203.0.113.10\"\nserverPort = 7000\n\n[[proxies]]\nname = \"ssh\"\n"
	long := strings.Repeat("a.", 5000) + "a"
	err := checkServerConfig([]byte(head + long + " = 1\n"))
	if err == nil {
		t.Fatal("checkServerConfig = nil, want the key refused")
	}
	if want := "line 6: a key with more than"; !strings.Contains(err.Error(), want) {
		t.Errorf("checkServerConfig = %q, want it to contain %q", err, want)
	}
	if strings.Contains(err.Error(), "a.a.a.a") {
		t.Errorf("checkServerConfig = %q, want the key left out", err)
	}
	limit := strings.Repeat("b.", maxKeySegments-1) + "b"
	if err := checkServerConfig([]byte(head + limit + " = 1\n")); err != nil {
		t.Errorf("checkServerConfig(%d segments) = %v, want nil", maxKeySegments, err)
	}
}

// The error names line and key, never the value: a refused line may hold auth.token or a
// secretKey.
func TestServerConfigErrorHidesTheValue(t *testing.T) {
	const marker = "MARKER-7f3a"
	const proxy = "\n[[proxies]]\nname = \"ssh\"\n"
	for _, line := range []string{
		"auth.token = '" + marker + "'",
		"auth.token = \"" + marker + "\\\"\"",
		"auth.token = \"" + marker + "{{\"",
		"auth.token = \"" + marker + "\"\r",
		"auth.token = { v = \"" + marker + "\" }",
		"\"" + marker + "\" = 1",
		marker,
		"[\"" + marker + "\"]",
	} {
		err := checkServerConfig([]byte("serverAddr = \"203.0.113.10\"\n" + line + "\n" + proxy))
		if err == nil {
			t.Errorf("line %q: checkServerConfig = nil, want it refused", line)
			continue
		}
		if !strings.Contains(err.Error(), "line 2") {
			t.Errorf("line %q: checkServerConfig = %q, want it to name line 2", line, err)
		}
		if strings.Contains(err.Error(), marker) {
			t.Errorf("line %q: checkServerConfig = %q, want it without the value %q", line, err, marker)
		}
	}
}

// refusedOverTheFlows are server texts out of the generator's form that frp would read
// otherwise than as the generator's text: as legacy INI (a [common] section, also inside a
// multi-line string), or with keys the generator never writes in the root.
var refusedOverTheFlows = map[string]string{
	"[common] table":                  "serverAddr = \"203.0.113.10\"\n\n[common]\nserver_port = 7000\n\n[[proxies]]\nname = \"ssh\"\n",
	"[common] in a multi-line string": "serverAddr = \"203.0.113.10\"\nuser = '''\n[common]\nend = 1'''\n\n[[proxies]]\nname = \"ssh\"\n",
	"log.to":                          "serverAddr = \"203.0.113.10\"\nlog.to = \"/tmp/frpc.log\"\n\n[[proxies]]\nname = \"ssh\"\n",
	"includes":                        "serverAddr = \"203.0.113.10\"\nincludes = [\"/tmp/*.toml\"]\n\n[[proxies]]\nname = \"ssh\"\n",
	"proxy plugin":                    "serverAddr = \"203.0.113.10\"\n\n[[proxies]]\nname = \"ssh\"\nplugin.type = \"http_proxy\"\n",
}

// A sync refuses a server text out of the generator's form, and frpc does not run on the old
// frpc.toml meanwhile: it is stopped and disabled, frpc.toml and the hash go (the next run fetches
// and checks again), admin.conf stays. The text is checked under the frpc lock, so the empty lock
// file is new. A second refused run finds nothing left and does not touch the service again.
func TestServerConfigRefusedBySync(t *testing.T) {
	for name, toml := range refusedOverTheFlows {
		t.Run(name, func(t *testing.T) {
			calls := setupSyncTest(t, "https://unused.example")
			writeFrpcState(t)
			calls.active = true
			fetches := serveToml(t, []byte(toml))
			want := maps.Clone(frpFiles(t))
			delete(want, "frpc.toml")
			delete(want, ".config-hash")
			want["frpc.lock"] = ""

			if err := Sync(context.Background()); err == nil {
				t.Fatal("Sync must refuse the server's text")
			}
			if got := frpFiles(t); !maps.Equal(got, want) {
				t.Errorf("the FRP directory holds %q, want %q (frpc.toml and hash removed)", got, want)
			}
			if calls.disables != 1 || calls.active || calls.enables+calls.restarts+calls.reloads != 0 {
				t.Errorf("frpc service state %+v, want it stopped and disabled once, nothing started", *calls)
			}

			if err := Sync(context.Background()); err == nil {
				t.Fatal("the second Sync must refuse the server's text again")
			}
			if calls.disables != 1 || *fetches != 2 {
				t.Errorf("after the second run disables = %d, config fetches = %d, want 1 and 2", calls.disables, *fetches)
			}
		})
	}
}

// Once the server sends a text that passes again, the next sync starts frpc on it like on a
// first tunnel.
func TestServerConfigAcceptedAfterARefusalStartsFrpc(t *testing.T) {
	calls := setupSyncTest(t, "https://unused.example")
	writeFrpcState(t)
	calls.active = true
	serveToml(t, []byte(refusedOverTheFlows["proxy plugin"]))
	if err := Sync(context.Background()); err == nil {
		t.Fatal("Sync must refuse the server's text")
	}

	serveToml(t, tunnelToml)
	if err := Sync(context.Background()); err != nil {
		t.Fatalf("Sync with a text that passes: %v", err)
	}
	if got, want := readFile(t, config.FrpConfigFile()), localHead(t)+string(tunnelToml); got != want {
		t.Errorf("frpc.toml = %q, want %q", got, want)
	}
	if got := readFile(t, config.FrpHashFile()); got != hashConfig(tunnelToml) {
		t.Errorf("hash file = %q, want %q", got, hashConfig(tunnelToml))
	}
	if calls.enables != 1 || !calls.active {
		t.Errorf("frpc service state %+v, want it enabled and running", *calls)
	}
}

// The generator's output goes through a sync as before: written behind the local head, with the
// identity paths rewritten, and frpc enabled.
func TestServerConfigFixtureAppliedBySync(t *testing.T) {
	calls := setupSyncTest(t, "https://unused.example")
	fixture := serverFixture(t)
	serveToml(t, fixture)

	if err := Sync(context.Background()); err != nil {
		t.Fatalf("Sync with the generator's output: %v", err)
	}
	if got, want := readFile(t, config.FrpConfigFile()), localHead(t)+string(rewriteIdentityPaths(fixture)); got != want {
		t.Errorf("frpc.toml = %q, want %q", got, want)
	}
	if got := readFile(t, config.FrpHashFile()); got != hashConfig(fixture) {
		t.Errorf("hash file = %q, want the hash of the server's text %q", got, hashConfig(fixture))
	}
	if calls.enables != 1 {
		t.Errorf("enables = %d, want 1", calls.enables)
	}
}

// The provisioning refuses such a text too: an error, and no frpc.toml. On a first provisioning
// nothing of frpc is there, so the service is not touched; a re-provisioning stops the frpc
// that ran on the former config, like a sync.
func TestServerConfigRefusedByApply(t *testing.T) {
	for name, toml := range refusedOverTheFlows {
		t.Run(name, func(t *testing.T) {
			calls := setupSyncTest(t, "https://srv.example")

			if err := applyBundle([]byte(toml)); err == nil {
				t.Fatal("Apply must refuse the server's text")
			}
			if _, err := os.Stat(config.FrpConfigFile()); !os.IsNotExist(err) {
				t.Errorf("frpc.toml stat = %v, want no frpc.toml", err)
			}
			if calls.restarts+calls.enables+calls.disables+calls.reloads != 0 {
				t.Errorf("frpc service calls %+v, want none", *calls)
			}
		})
		t.Run(name+", re-provisioning", func(t *testing.T) {
			calls := setupSyncTest(t, "https://srv.example")
			writeFrpcState(t)
			calls.active = true

			if err := applyBundle([]byte(toml)); err == nil {
				t.Fatal("Apply must refuse the server's text")
			}
			if !frpcGone() {
				t.Errorf("frpc.toml or the hash is still there, want both removed")
			}
			if calls.disables != 1 || calls.active || calls.enables+calls.restarts+calls.reloads != 0 {
				t.Errorf("frpc service state %+v, want it stopped and disabled once, nothing started", *calls)
			}
		})
	}
}
