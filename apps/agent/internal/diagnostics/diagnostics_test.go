// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package diagnostics

import (
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
