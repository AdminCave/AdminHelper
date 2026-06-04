// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package frpc

import (
	"crypto/sha256"
	"fmt"
	"testing"
)

func TestHashConfigKnownInput(t *testing.T) {
	// SHA256("") is a known, constant value.
	const emptySHA256 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
	if got := hashConfig([]byte("")); got != emptySHA256 {
		t.Errorf("hashConfig(\"\") = %q, erwartet %q", got, emptySHA256)
	}

	// Known value for "hello".
	const helloSHA256 = "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"
	if got := hashConfig([]byte("hello")); got != helloSHA256 {
		t.Errorf("hashConfig(\"hello\") = %q, erwartet %q", got, helloSHA256)
	}
}

func TestHashConfigMatchesStdlib(t *testing.T) {
	data := []byte("bind_port = 7000\nserver_addr = \"example.com\"\n")
	want := fmt.Sprintf("%x", sha256.Sum256(data))
	if got := hashConfig(data); got != want {
		t.Errorf("hashConfig = %q, erwartet %q", got, want)
	}
}

func TestHashConfigCompare(t *testing.T) {
	// Match: identical bytes yield an identical hash.
	a := hashConfig([]byte("same-config"))
	b := hashConfig([]byte("same-config"))
	if a != b {
		t.Errorf("identischer Input erzeugte ungleiche Hashes: %q != %q", a, b)
	}

	// Mismatch: a changed line changes the hash.
	c := hashConfig([]byte("same-config\n"))
	if a == c {
		t.Errorf("unterschiedlicher Input erzeugte gleichen Hash: %q", a)
	}
}

func TestParseConfigHashValid(t *testing.T) {
	body := []byte(`{"hash": "abc123def456"}`)
	got, err := parseConfigHash(body)
	if err != nil {
		t.Fatalf("parseConfigHash gab Fehler: %v", err)
	}
	if got != "abc123def456" {
		t.Errorf("parseConfigHash = %q, erwartet %q", got, "abc123def456")
	}
}

func TestParseConfigHashMissingField(t *testing.T) {
	// Valid JSON without the "hash" field -> empty string, no error.
	got, err := parseConfigHash([]byte(`{"other": "x"}`))
	if err != nil {
		t.Fatalf("parseConfigHash gab unerwarteten Fehler: %v", err)
	}
	if got != "" {
		t.Errorf("parseConfigHash = %q, erwartet leeren String", got)
	}
}

func TestParseConfigHashInvalidJSON(t *testing.T) {
	cases := map[string][]byte{
		"truncated":   []byte(`{"hash": "abc`),
		"not json":    []byte(`<html>error</html>`),
		"empty body":  []byte(``),
		"wrong type":  []byte(`{"hash": 123}`),
		"bare string": []byte(`"hash"`),
	}
	for name, body := range cases {
		t.Run(name, func(t *testing.T) {
			if _, err := parseConfigHash(body); err == nil {
				t.Errorf("parseConfigHash(%q) erwartete Fehler, bekam keinen", body)
			}
		})
	}
}
