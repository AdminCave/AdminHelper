// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package frpc

import (
	"fmt"
	"regexp"
	"strings"
	"unicode"
	"unicode/utf8"
)

// serverRootKeys are the keys generate_frpc_toml (apps/server/app/modules/frp/config_generator.py)
// writes before the first [[proxies]]; the transport.tls ones may also stand under a
// [transport.tls] head. The keys of the local head are not among them: the agent alone sets those.
var serverRootKeys = map[string]bool{
	"serverAddr":                  true,
	"serverPort":                  true,
	"user":                        true,
	"auth.method":                 true,
	"auth.token":                  true,
	"transport.tls.enable":        true,
	"transport.tls.trustedCaFile": true,
	"transport.tls.certFile":      true,
	"transport.tls.keyFile":       true,
}

// serverKey is a bare or dotted TOML key without quotes, as the generator writes them.
var serverKey = regexp.MustCompile(`^[A-Za-z0-9_-]+(\.[A-Za-z0-9_-]+)*$`)

// serverValue is a value as the generator writes it, on one line: a basic string without quote
// or backslash (so without escapes), an array of such strings, a bool, a decimal integer, or a
// float as Python's str(float) spells it (1.5, 1e+20, inf, -inf, nan).
var serverValue = regexp.MustCompile(`^(?:` + strings.Join([]string{
	`"[^"\\]*"`,
	`\[(?:"[^"\\]*"(?:, "[^"\\]*")*)?\]`,
	`true|false`,
	`[+-]?(?:0|[1-9][0-9]*)`,
	`-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:e[+-][0-9]+)?`,
	`-?inf|nan`,
}, "|") + `)$`)

// maxKeySegments bounds the segments of a key. No frp field lies that deep, so frpc would refuse
// a deeper key anyway; the bound keeps the work per key small however long the line is.
const maxKeySegments = 32

// serverHead is a table head whose name may stand in an error message.
var serverHead = regexp.MustCompile(`^\[\[?[A-Za-z0-9_.-]+\]\]?$`)

// checkServerConfig refuses a server text that is not in the form generate_frpc_toml writes:
// every line blank, [transport.tls], [[proxies]] or `key = value` with a value of one line; in
// the root (with [transport.tls]) only the generator's keys; no key twice in a table; no "{{".
// frp decides on the raw text whether it is legacy INI and renders it as a Go template before
// it reads the TOML; only in this form all of these read it the same. A proxy may carry any key
// (a tunnel's extra_config) but one whose first segment is plugin in any case: the server sets
// up no proxy plugin, and frp maps keys to its fields without regard to case. The error names
// line and key, never the value: a line may hold auth.token or a secretKey.
func checkServerConfig(serverToml []byte) error {
	root := keyTable{}
	table, prefix := root, ""
	tlsHead, inProxies, rootTLS := false, false, false
	for i, raw := range strings.Split(string(serverToml), "\n") {
		n := i + 1
		switch {
		case !utf8.ValidString(raw):
			return refuseLine(n, raw, "is not valid UTF-8")
		case strings.Contains(raw, "{{"):
			return refuseLine(n, raw, `contains "{{"`)
		case strings.ContainsFunc(raw, unicode.IsControl):
			return refuseLine(n, raw, "contains a control character")
		}
		line := strings.Trim(raw, " ")
		switch {
		case line == "":
			continue
		case line == "[[proxies]]":
			table, prefix, inProxies = keyTable{}, "", true
			continue
		case line == "[transport.tls]":
			switch {
			case tlsHead:
				return refuse(n, "a second [transport.tls]")
			case inProxies:
				return refuse(n, "[transport.tls] after a [[proxies]]")
			case rootTLS:
				return refuse(n, "[transport.tls] after transport.tls keys in the root")
			}
			tlsHead, prefix = true, "transport.tls."
			continue
		case strings.HasPrefix(line, "["):
			head := "a table head"
			if serverHead.MatchString(line) {
				head = "the table " + line
			}
			return refuse(n, head+"; only [transport.tls] and [[proxies]] are applied")
		}

		key, value, ok := strings.Cut(line, " = ")
		if !ok || !serverKey.MatchString(key) {
			return refuse(n, "not a line of the form key = value with a bare or dotted key")
		}
		if !serverValue.MatchString(value) {
			return refuse(n, fmt.Sprintf("the value of %s is not one the server writes", key))
		}
		path := prefix + key
		if strings.Count(path, ".") >= maxKeySegments {
			return refuse(n, fmt.Sprintf("a key with more than %d segments", maxKeySegments))
		}
		if !inProxies {
			if !serverRootKeys[path] {
				return refuse(n, fmt.Sprintf("%s is no key the server sets in the root", path))
			}
			if path == "auth.method" && value != `"token"` {
				return refuse(n, `auth.method must be "token"`)
			}
			if prefix == "" && strings.HasPrefix(path, "transport.tls.") {
				rootTLS = true
			}
		} else if first, _, _ := strings.Cut(path, "."); strings.EqualFold(first, "plugin") {
			return refuse(n, fmt.Sprintf("%s is a plugin key; a proxy from the server carries no plugin", path))
		}
		if !table.add(path) {
			return refuse(n, fmt.Sprintf("%s is set twice, or as a value and a table at once", path))
		}
	}
	return nil
}

// keyTable holds the key paths of one TOML table, lowercase: true for a key, false for a table
// a dotted key opens. frp maps keys to its fields without regard to case.
type keyTable map[string]bool

// add records path and reports whether it is new and no key of the table is a prefix of it or
// has it as a prefix.
func (t keyTable) add(path string) bool {
	path = strings.ToLower(path)
	if _, taken := t[path]; taken {
		return false
	}
	// The prefixes are slices of path, so they share its bytes.
	var prefixes []string
	for i, c := range path {
		if c == '.' {
			prefixes = append(prefixes, path[:i])
		}
	}
	for _, p := range prefixes {
		if t[p] {
			return false
		}
	}
	for _, p := range prefixes {
		t[p] = false
	}
	t[path] = true
	return true
}

// refuse is the error for line n of a server text out of the generator's form.
func refuse(n int, why string) error {
	return fmt.Errorf("the server's frpc.toml is not in the form the server writes, line %d: %s; not applied", n, why)
}

// refuseLine is refuse for a line that fails as a whole; it names the line's key when it has one.
func refuseLine(n int, line, why string) error {
	subject := "the line"
	if key, _, ok := strings.Cut(strings.Trim(line, " "), " = "); ok && serverKey.MatchString(key) {
		subject = "the line of " + key
	}
	return refuse(n, subject+" "+why)
}
