// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package selfupdate

import (
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"testing"
)

// The fixtures in testdata/ were made by minisign 0.12 with a throwaway key
// (only its public half, test.pub, is kept): SHA256SUMS.minisig is the
// default prehashed form, .legacy the -l form, .wrongkey signed by a second key.

func readTestdata(t *testing.T, name string) []byte {
	t.Helper()
	b, err := os.ReadFile(filepath.Join("testdata", name))
	if err != nil {
		t.Fatal(err)
	}
	return b
}

func testKey(t *testing.T) string {
	return strings.TrimSpace(string(readTestdata(t, "test.pub")))
}

func TestVerifyAcceptsRealMinisignSignature(t *testing.T) {
	trusted, err := Verify(testKey(t), readTestdata(t, "SHA256SUMS"), readTestdata(t, "SHA256SUMS.minisig"))
	if err != nil {
		t.Fatalf("Verify: %v", err)
	}
	if trusted != "adminhelper-agent windows v1.2.3" {
		t.Fatalf("trusted comment = %q", trusted)
	}
}

func TestVerifyRejects(t *testing.T) {
	data := readTestdata(t, "SHA256SUMS")
	sig := readTestdata(t, "SHA256SUMS.minisig")
	lines := strings.Split(string(sig), "\n")
	forgedComment := strings.Join([]string{lines[0], lines[1], "trusted comment: adminhelper-agent windows v9.9.9", lines[3]}, "\n")

	cases := map[string]struct {
		key  string
		data []byte
		sig  []byte
	}{
		"tampered data":    {testKey(t), append(append([]byte{}, data...), 'x'), sig},
		"wrong key":        {testKey(t), data, readTestdata(t, "SHA256SUMS.wrongkey.minisig")},
		"legacy Ed form":   {testKey(t), data, readTestdata(t, "SHA256SUMS.legacy.minisig")},
		"forged comment":   {testKey(t), data, []byte(forgedComment)},
		"release key":      {ReleasePublicKey, data, sig},
		"truncated":        {testKey(t), data, []byte(strings.Join(lines[:2], "\n"))},
		"garbage key":      {"not-a-key", data, sig},
		"garbage sig line": {testKey(t), data, []byte(strings.Join([]string{lines[0], "!!", lines[2], lines[3]}, "\n"))},
	}
	for name, c := range cases {
		t.Run(name, func(t *testing.T) {
			if _, err := Verify(c.key, c.data, c.sig); err == nil {
				t.Fatal("Verify accepted it")
			}
		})
	}
}

func TestVerifyAcceptsCRLF(t *testing.T) {
	sig := strings.ReplaceAll(string(readTestdata(t, "SHA256SUMS.minisig")), "\n", "\r\n")
	if _, err := Verify(testKey(t), readTestdata(t, "SHA256SUMS"), []byte(sig)); err != nil {
		t.Fatalf("Verify: %v", err)
	}
}

func TestReleaseKeyMatchesUpdateScript(t *testing.T) {
	script, err := os.ReadFile(filepath.Join("..", "..", "..", "..", "scripts", "update.sh"))
	if err != nil {
		t.Fatal(err)
	}
	m := regexp.MustCompile(`(?m)^MINISIGN_PUBKEY="([^"]+)"`).FindSubmatch(script)
	if m == nil {
		t.Fatal("MINISIGN_PUBKEY not found in scripts/update.sh")
	}
	if string(m[1]) != ReleasePublicKey {
		t.Fatalf("ReleasePublicKey %q != update.sh %q", ReleasePublicKey, m[1])
	}
	if _, err := parsePublicKey(ReleasePublicKey); err != nil {
		t.Fatal(err)
	}
}
