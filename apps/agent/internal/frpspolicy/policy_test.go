// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package frpspolicy

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"os"
	"path/filepath"
	"slices"
	"strings"
	"testing"
	"time"
)

// The fixtures hold the keys apps/server/app/modules/frp/proxy_key.py derives with the
// server tests' SECRET_KEY placeholder, so the server's tests can hold its policy writer
// to testdata/policy.json.
const (
	serverA  = "0f1e2d3c-4b5a-4968-8776-655443322110"
	serverB  = "7a0e4d2c-1b3f-4a5e-8c6d-9e0f1a2b3c4d"
	keyA     = "30f3d257dacd265b868a68e3c508e6a6a7b759f6152d56c09541da0feba5b77a"
	keyB     = "f1d5c31b0b14daa3a4f1eae112617d1c97c8b0853ad17a6ceee70081d36c636f"
	groupKey = "group-key-placeholder"
	sk       = "tunnel-secret-placeholder"
)

func fixturePolicy(t *testing.T) []byte {
	t.Helper()
	data, err := os.ReadFile("testdata/policy.json")
	if err != nil {
		t.Fatal(err)
	}
	return data
}

// fixtureRequest is testdata/newproxy.json: frps' NewProxy request for the stcp proxy
// t-ssh of server A.
func fixtureRequest(t *testing.T) []byte {
	t.Helper()
	data, err := os.ReadFile("testdata/newproxy.json")
	if err != nil {
		t.Fatal(err)
	}
	return data
}

func fixtureNewProxy(t *testing.T) *NewProxy {
	t.Helper()
	var req struct {
		Content NewProxy `json:"content"`
	}
	if err := json.Unmarshal(fixtureRequest(t), &req); err != nil {
		t.Fatal(err)
	}
	return &req.Content
}

func parsedFixture(t *testing.T) *Policy {
	t.Helper()
	p, err := Parse(fixturePolicy(t))
	if err != nil {
		t.Fatal(err)
	}
	return p
}

func sha256Hex(s string) string {
	sum := sha256.Sum256([]byte(s))
	return hex.EncodeToString(sum[:])
}

func TestTheFixturesBelongTogether(t *testing.T) {
	p := parsedFixture(t)
	if len(p.Servers) != 2 || len(p.Servers[serverA].Proxies) != 3 || len(p.Servers[serverB].Proxies) != 1 {
		t.Fatalf("fixture policy = %+v; want server A with 3 proxies and server B with 1", p.Servers)
	}
	if got := p.Servers[serverA].KeyHash; got != sha256Hex(keyA) {
		t.Errorf("keyHash of A = %s, want the SHA-256 of keyA", got)
	}
	if got := p.Servers[serverB].KeyHash; got != sha256Hex(keyB) {
		t.Errorf("keyHash of B = %s, want the SHA-256 of keyB", got)
	}
	if got := p.Servers[serverA].Proxies["t-lb"].GroupKeyHash; got != sha256Hex(groupKey) {
		t.Errorf("groupKeyHash of t-lb = %s, want the SHA-256 of groupKey", got)
	}
	if got := p.Servers[serverA].Proxies["t-ssh"].SkHash; got != sha256Hex(sk) {
		t.Errorf("skHash of t-ssh = %s, want the SHA-256 of sk", got)
	}
	np := fixtureNewProxy(t)
	if np.User.User != serverA || np.ProxyName != serverA+".t-ssh" || np.Metas[KeyMeta] != keyA ||
		np.Sk != sk || !slices.Equal(np.AllowUsers, []string{"ops-admin"}) {
		t.Errorf("fixture request = %+v; want the proxy t-ssh of A with keyA", np)
	}
	for _, secret := range []string{keyA, groupKey, sk} {
		if strings.Contains(string(fixturePolicy(t)), secret) {
			t.Errorf("the policy holds %q in clear", secret)
		}
	}
}

func TestParseRefuses(t *testing.T) {
	fixture := string(fixturePolicy(t))
	hashA := sha256Hex(keyA)
	cases := map[string]string{
		"no JSON":             "version = 1",
		"an array":            "[]",
		"data after the JSON": fixture + "{}",
		"version 1":           strings.Replace(fixture, `"version": 2`, `"version": 1`, 1),
		"version 3":           strings.Replace(fixture, `"version": 2`, `"version": 3`, 1),
		"no version":          `{"servers": {}}`,
		"no servers":          `{"version": 2}`,
		"servers null":        `{"version": 2, "servers": null}`,
		"an unknown field":    strings.Replace(fixture, `"version": 2`, `"version": 2, "mode": "open"`, 1),
		"an unknown proxy field": strings.Replace(fixture, `"type": "stcp"`,
			`"type": "stcp", "remotePort": 6000`, 1),
		"a server without an ID":      `{"version": 2, "servers": {"": {"keyHash": "` + hashA + `", "proxies": {}}}}`,
		"a short keyHash":             strings.Replace(fixture, hashA, hashA[:63], 1),
		"an uppercase keyHash":        strings.Replace(fixture, hashA, strings.ToUpper(hashA), 1),
		"a keyHash with no hex digit": strings.Replace(fixture, hashA, "z"+hashA[1:], 1),
		"no keyHash":                  `{"version": 2, "servers": {"` + serverA + `": {"proxies": {}}}}`,
		"a proxy without an ID": `{"version": 2, "servers": {"` + serverA + `": {"keyHash": "` + hashA +
			`", "proxies": {"": {"type": "stcp"}}}}}`,
		"type tcp":              strings.Replace(fixture, `"type": "stcp"`, `"type": "tcp"`, 1),
		"no type":               strings.Replace(fixture, `"type": "stcp"`, `"type": ""`, 1),
		"a broken groupKeyHash": strings.Replace(fixture, sha256Hex(groupKey), "group-key", 1),
		"a broken skHash":       strings.Replace(fixture, sha256Hex(sk), "secret", 1),
		"an uppercase skHash":   strings.Replace(fixture, sha256Hex(sk), strings.ToUpper(sha256Hex(sk)), 1),
	}
	for name, text := range cases {
		if p, err := Parse([]byte(text)); err == nil {
			t.Errorf("%s: Parse = %+v, want an error", name, p)
		}
	}
	if _, err := Parse([]byte(`{"version": 2, "servers": {}}`)); err != nil {
		t.Errorf("a policy without a server: Parse = %v, want nil", err)
	}
}

func TestDecide(t *testing.T) {
	p := parsedFixture(t)
	web := func(np *NewProxy) {
		np.ProxyName, np.ProxyType = serverA+".t-web", "https"
		np.CustomDomains = []string{"web.example", "www.web.example"}
		np.Sk, np.AllowUsers = "", nil
	}
	lb := func(np *NewProxy) {
		np.ProxyName, np.ProxyType = serverA+".t-lb", "https"
		np.CustomDomains, np.SubDomain = []string{"lb.example"}, "lb"
		np.Group, np.GroupKey = "web", groupKey
		np.Sk, np.AllowUsers = "", nil
	}
	hostB := func(np *NewProxy) {
		np.User.User, np.ProxyName, np.Metas = serverB, serverB+".t-db", map[string]string{KeyMeta: keyB}
	}
	then := func(fs ...func(*NewProxy)) func(*NewProxy) {
		return func(np *NewProxy) {
			for _, f := range fs {
				f(np)
			}
		}
	}
	cases := []struct {
		name   string
		change func(*NewProxy)
		want   string
	}{
		{"the own stcp proxy", func(*NewProxy) {}, ""},
		{"the own https proxy", web, ""},
		{"the own https proxy in a group", lb, ""},
		{"another host with its own key", hostB, ""},
		{"a metas field beside the key", func(np *NewProxy) { np.Metas["owner"] = "ops" }, ""},

		{"an unknown user", func(np *NewProxy) { np.User.User = "c0ffee00-0000-4000-8000-000000000000" }, "unknown user"},
		{"no user", func(np *NewProxy) { np.User.User = "" }, "unknown user"},
		{"no metas", func(np *NewProxy) { np.Metas = nil }, "no key"},
		{"an empty key", func(np *NewProxy) { np.Metas[KeyMeta] = "" }, "no key"},
		{"the key under another name", func(np *NewProxy) { np.Metas = map[string]string{"ahproxykey": keyA} }, "no key"},
		{"a wrong key", func(np *NewProxy) { np.Metas[KeyMeta] = "0" + keyA[1:] }, "wrong key"},
		{"the key of another host", func(np *NewProxy) { np.Metas[KeyMeta] = keyB }, "wrong key"},
		{"the hash of the own key", func(np *NewProxy) { np.Metas[KeyMeta] = sha256Hex(keyA) }, "wrong key"},
		{"another host's user with the own key", then(hostB, func(np *NewProxy) { np.Metas[KeyMeta] = keyA }), "wrong key"},
		{"another host's proxy under the own user", func(np *NewProxy) { np.ProxyName = serverA + ".t-db" }, "no tunnel of this user"},
		{"another host's proxy name", func(np *NewProxy) { np.ProxyName = serverB + ".t-db" }, "name without the user prefix"},
		{"a name without the user prefix", func(np *NewProxy) { np.ProxyName = "t-ssh" }, "name without the user prefix"},
		{"the prefix alone", func(np *NewProxy) { np.ProxyName = serverA + "." }, "no tunnel of this user"},
		{"a tunnel ID in another case", func(np *NewProxy) { np.ProxyName = serverA + ".T-SSH" }, "no tunnel of this user"},
		{"type tcp", func(np *NewProxy) { np.ProxyType = "tcp" }, "other type"},
		{"no type", func(np *NewProxy) { np.ProxyType = "" }, "other type"},
		{"https for an stcp tunnel", func(np *NewProxy) { np.ProxyType = "https" }, "other type"},
		{"stcp for an https tunnel", then(web, func(np *NewProxy) { np.ProxyType = "stcp" }), "other type"},
		{"a remote port", func(np *NewProxy) { np.RemotePort = 6000 }, "remote port"},
		{"a domain for an stcp tunnel", func(np *NewProxy) { np.CustomDomains = []string{"web.example"} }, "other custom domains"},
		{"no domains", then(web, func(np *NewProxy) { np.CustomDomains = nil }), "other custom domains"},
		{"one domain fewer", then(web, func(np *NewProxy) { np.CustomDomains = np.CustomDomains[:1] }), "other custom domains"},
		{"another domain more", then(web, func(np *NewProxy) { np.CustomDomains = append(np.CustomDomains, "other.example") }), "other custom domains"},
		{"the domains in another order", then(web, func(np *NewProxy) {
			np.CustomDomains = []string{"www.web.example", "web.example"}
		}), "other custom domains"},
		{"a domain in another case", then(web, func(np *NewProxy) { np.CustomDomains[0] = "Web.example" }), "other custom domains"},
		{"another host's domain", then(web, func(np *NewProxy) { np.CustomDomains = []string{"lb.example"} }), "other custom domains"},
		{"a subdomain", func(np *NewProxy) { np.SubDomain = "ssh" }, "other subdomain"},
		{"no subdomain", then(lb, func(np *NewProxy) { np.SubDomain = "" }), "other subdomain"},
		{"another subdomain", then(lb, func(np *NewProxy) { np.SubDomain = "web" }), "other subdomain"},
		{"a group", func(np *NewProxy) { np.Group = "web" }, "other group"},
		{"no group", then(lb, func(np *NewProxy) { np.Group = "" }), "other group"},
		{"another group", then(lb, func(np *NewProxy) { np.Group = "db" }), "other group"},
		{"a group key", func(np *NewProxy) { np.GroupKey = groupKey }, "other group key"},
		{"no group key", then(lb, func(np *NewProxy) { np.GroupKey = "" }), "other group key"},
		{"a wrong group key", then(lb, func(np *NewProxy) { np.GroupKey = "group-key" }), "other group key"},
		{"the hash of the group key", then(lb, func(np *NewProxy) { np.GroupKey = sha256Hex(groupKey) }), "other group key"},
		{"the allowed users repeated", func(np *NewProxy) { np.AllowUsers = []string{"ops-admin", "ops-admin"} }, ""},
		{"no allowed users", func(np *NewProxy) { np.AllowUsers = nil }, "other allowed users"},
		{"every user allowed", func(np *NewProxy) { np.AllowUsers = []string{"*"} }, "other allowed users"},
		{"another allowed user", func(np *NewProxy) { np.AllowUsers = []string{"intruder"} }, "other allowed users"},
		{"one allowed user more", func(np *NewProxy) { np.AllowUsers = append(np.AllowUsers, serverB) }, "other allowed users"},
		{"an allowed user in another case", func(np *NewProxy) { np.AllowUsers = []string{"Ops-admin"} }, "other allowed users"},
		{"allowed users for an https tunnel", then(web, func(np *NewProxy) { np.AllowUsers = []string{"ops-admin"} }), "other allowed users"},
		{"no secret key", func(np *NewProxy) { np.Sk = "" }, "other secret key"},
		{"a wrong secret key", func(np *NewProxy) { np.Sk = sk + "x" }, "other secret key"},
		{"the hash of the secret key", func(np *NewProxy) { np.Sk = sha256Hex(sk) }, "other secret key"},
		{"a secret key for an https tunnel", then(web, func(np *NewProxy) { np.Sk = sk }), "other secret key"},
	}
	for _, c := range cases {
		np := fixtureNewProxy(t)
		c.change(np)
		if got := p.Decide(np); got != c.want {
			t.Errorf("%s: Decide = %q, want %q", c.name, got, c.want)
		}
	}
}

func writeFile(t *testing.T, path string, data []byte) {
	t.Helper()
	if err := os.WriteFile(path, data, 0o644); err != nil {
		t.Fatal(err)
	}
}

func TestSourceReadsThePolicy(t *testing.T) {
	path := filepath.Join(t.TempDir(), "frps-policy.json")
	writeFile(t, path, fixturePolicy(t))
	p, err := NewSource(path).Current()
	if err != nil || len(p.Servers) != 2 {
		t.Fatalf("Current = %+v, %v; want the fixture", p, err)
	}
}

func TestSourceRefusesWithoutAUsablePolicy(t *testing.T) {
	cases := map[string]func(t *testing.T, path string){
		"a missing file": func(*testing.T, string) {},
		"a directory": func(t *testing.T, path string) {
			if err := os.Mkdir(path, 0o755); err != nil {
				t.Fatal(err)
			}
		},
		"a link to a valid policy": func(t *testing.T, path string) {
			target := filepath.Join(filepath.Dir(path), "target.json")
			writeFile(t, target, fixturePolicy(t))
			if err := os.Symlink(target, path); err != nil {
				t.Fatal(err)
			}
		},
		"a file too large": func(t *testing.T, path string) {
			// The fixture padded with spaces past the limit: valid JSON, only too large.
			data := append(fixturePolicy(t), []byte(strings.Repeat(" ", MaxPolicySize))...)
			writeFile(t, path, data)
		},
		"a broken file": func(t *testing.T, path string) { writeFile(t, path, fixturePolicy(t)[:100]) },
		"an empty file": func(t *testing.T, path string) { writeFile(t, path, nil) },
	}
	for name, setup := range cases {
		path := filepath.Join(t.TempDir(), "frps-policy.json")
		setup(t, path)
		src := NewSource(path)
		for range 2 { // and again from the cache
			if p, err := src.Current(); err == nil || p != nil {
				t.Errorf("%s: Current = %+v, %v; want no policy and an error", name, p, err)
			}
		}
	}
}

func TestSourceReadsAChangedFile(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "frps-policy.json")
	fixture := fixturePolicy(t)
	writeFile(t, path, fixture)
	src := NewSource(path)
	if _, err := src.Current(); err != nil {
		t.Fatal(err)
	}

	// Written in place with another size.
	onlyB := `{"version": 2, "servers": {"` + serverB + `": {"keyHash": "` + sha256Hex(keyB) + `", "proxies": {}}}}`
	writeFile(t, path, []byte(onlyB))
	p, err := src.Current()
	if err != nil || len(p.Servers) != 1 {
		t.Fatalf("after a rewrite: Current = %+v, %v; want server B alone", p, err)
	}

	// Replaced by another file of the same size and mtime, as the server's atomic write
	// can be within one tick of the file system's clock.
	writeFile(t, path, fixture)
	if _, err := src.Current(); err != nil {
		t.Fatal(err)
	}
	old, err := os.Stat(path)
	if err != nil {
		t.Fatal(err)
	}
	otherType := strings.Replace(string(fixture), `"type": "stcp"`, `"type": "xxxx"`, 1)
	replaceFile(t, path, []byte(otherType), old.ModTime())
	if p, err := src.Current(); err == nil {
		t.Fatalf("after an atomic replace: Current = %+v; want the error of the new file", p)
	}

	// Mended the same way, again with the same size and mtime.
	replaceFile(t, path, fixture, old.ModTime())
	if p, err := src.Current(); err != nil || len(p.Servers) != 2 {
		t.Fatalf("after the mend: Current = %+v, %v; want the fixture", p, err)
	}
}

// replaceFile replaces path with a new file of data and the given mtime, as the server's
// atomic write does: another file at the same path.
func replaceFile(t *testing.T, path string, data []byte, mtime time.Time) {
	t.Helper()
	tmp := filepath.Join(filepath.Dir(path), ".frps-policy.json.tmp")
	writeFile(t, tmp, data)
	if err := os.Chtimes(tmp, time.Time{}, mtime); err != nil {
		t.Fatal(err)
	}
	if err := os.Rename(tmp, path); err != nil {
		t.Fatal(err)
	}
}

func TestDecideLogin(t *testing.T) {
	p := parsedFixture(t)
	cases := []struct {
		name  string
		login Login
		want  string
	}{
		{"a host with its key", Login{User: serverA, Metas: map[string]string{KeyMeta: keyA, "owner": "ops"}}, ""},
		{"another host with its key", Login{User: serverB, Metas: map[string]string{KeyMeta: keyB}}, ""},
		{"a host with another host's key", Login{User: serverA, Metas: map[string]string{KeyMeta: keyB}}, "wrong key"},
		{"a host without a key", Login{User: serverA}, "no key"},
		{"an empty key", Login{User: serverA, Metas: map[string]string{KeyMeta: ""}}, "no key"},
		{"a visitor's user, no host", Login{User: "ops-admin"}, ""},
		{"no user", Login{Metas: map[string]string{KeyMeta: keyA}}, "no user"},
	}
	for _, c := range cases {
		if got := p.DecideLogin(&c.login); got != c.want {
			t.Errorf("%s: DecideLogin = %q, want %q", c.name, got, c.want)
		}
	}
}

func TestBoundRunID(t *testing.T) {
	fresh, err := BoundRunID(serverA, "")
	if err != nil {
		t.Fatal(err)
	}
	if !strings.HasPrefix(fresh, runIDPrefix(serverA)) || len(fresh) != 49 || len(fresh) > 64 {
		t.Fatalf("BoundRunID(A, \"\") = %q, want 49 bytes under A's prefix", fresh)
	}
	if again, _ := BoundRunID(serverA, ""); again == fresh {
		t.Errorf("two fresh run IDs are the same: %q", fresh)
	}
	if kept, _ := BoundRunID(serverA, fresh); kept != fresh {
		t.Errorf("BoundRunID(A, own) = %q, want %q kept", kept, fresh)
	}
	ofB, _ := BoundRunID(serverB, "")
	upper := runIDPrefix(serverA) + strings.ToUpper(fresh[len(runIDPrefix(serverA)):])
	for name, runID := range map[string]string{
		"another user's run ID":   ofB,
		"frps' own form":          "0123456789abcdef",
		"the prefix alone":        runIDPrefix(serverA),
		"a longer rest":           fresh + "0",
		"uppercase hex":           upper,
		"the user's name as text": serverA + "-0123456789abcdef0123456789abcdef",
	} {
		got, err := BoundRunID(serverA, runID)
		if err != nil {
			t.Fatal(err)
		}
		if got == runID || !strings.HasPrefix(got, runIDPrefix(serverA)) || len(got) != 49 {
			t.Errorf("%s: BoundRunID(A, %q) = %q, want a fresh one under A's prefix", name, runID, got)
		}
	}
	if runIDPrefix(serverA) == runIDPrefix(serverB) {
		t.Error("two users share a run ID prefix")
	}
}
