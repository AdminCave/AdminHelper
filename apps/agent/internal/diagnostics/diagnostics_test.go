// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package diagnostics

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestRedactConfigLine(t *testing.T) {
	cases := map[string]bool{ // input -> should be redacted
		"API_KEY=topsecret":       true,
		"MONITOR_API_KEY=abc123":  true,
		"AUTH_TOKEN=xyz789":       true,
		"SECRET=zzz":              true,
		"MONITOR_URL=https://x.y": false,
		"SERVER_ID=srv-1":         false,
		"a line without equals":   false,
	}
	for in, shouldRedact := range cases {
		out := redactConfigLine(in)
		redacted := strings.Contains(out, "<redacted>")
		if redacted != shouldRedact {
			t.Errorf("redactConfigLine(%q) = %q; redacted=%v want %v", in, out, redacted, shouldRedact)
		}
		if !shouldRedact && out != in {
			t.Errorf("redactConfigLine(%q) altered a non-secret line: %q", in, out)
		}
	}
}

func TestRedactGeneric(t *testing.T) {
	in := "Authorization: Bearer abcdef123456 key ah_aBcDeFgH1234 jwt eyJhbGciOiJI.eyJzdWIiOiJ.sigpart"
	out := redactGeneric(in)

	for _, leak := range []string{"abcdef123456", "ah_aBcDeFgH1234"} {
		if strings.Contains(out, leak) {
			t.Errorf("token survived redaction: %q in %q", leak, out)
		}
	}
	for _, want := range []string{"Bearer <redacted>", "ah_<redacted>", "<redacted-jwt>"} {
		if !strings.Contains(out, want) {
			t.Errorf("missing %q in %q", want, out)
		}
	}
}

func TestTailFile(t *testing.T) {
	dir := t.TempDir()

	// Missing file: a "(log not available…)" note, not a crash (6.97).
	if got := tailFile(filepath.Join(dir, "nope.log"), 5); !strings.Contains(got, "log not available") {
		t.Errorf("missing file: got %q", got)
	}

	path := filepath.Join(dir, "log")
	write := func(s string) {
		if err := os.WriteFile(path, []byte(s), 0o644); err != nil {
			t.Fatal(err)
		}
	}

	// Fewer lines than n: all lines, exactly one trailing newline.
	write("a\nb\nc\n")
	if got := tailFile(path, 5); got != "a\nb\nc\n" {
		t.Errorf("fewer than n: got %q", got)
	}
	// Exactly n lines: unchanged.
	if got := tailFile(path, 3); got != "a\nb\nc\n" {
		t.Errorf("exactly n: got %q", got)
	}
	// More lines than n: only the last n (off-by-one guard).
	write("a\nb\nc\nd\ne\n")
	if got := tailFile(path, 2); got != "d\ne\n" {
		t.Errorf("more than n: got %q, want %q", got, "d\ne\n")
	}
	// No trailing newline in the source: still one trailing newline out.
	write("x\ny")
	if got := tailFile(path, 5); got != "x\ny\n" {
		t.Errorf("no trailing newline: got %q, want %q", got, "x\ny\n")
	}
}
