// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package config

import "testing"

// baseURL reduces a configured server URL to scheme://host — the origin the
// agent opens its mTLS channel to. A malformed URL slipping through (no scheme,
// no host) would point the secure channel at the wrong place, so reject those.
func TestBaseURL(t *testing.T) {
	ok := []struct {
		raw  string
		want string
	}{
		{"https://example.com", "https://example.com"},
		{"https://example.com:8443/api/v1", "https://example.com:8443"},
		{"http://host:80/x?y=1", "http://host:80"},
		{"https://[::1]:8443/path", "https://[::1]:8443"}, // IPv6 literal
	}
	for _, c := range ok {
		got, err := baseURL(c.raw)
		if err != nil {
			t.Errorf("baseURL(%q) unexpected error: %v", c.raw, err)
			continue
		}
		if got != c.want {
			t.Errorf("baseURL(%q) = %q, want %q", c.raw, got, c.want)
		}
	}

	bad := []string{
		"",            // no scheme, no host
		"https://",    // scheme but no host
		"host:8080",   // parses as scheme "host", opaque "8080" -> no host
		"//host/path", // no scheme
		"example.com", // no scheme
	}
	for _, raw := range bad {
		if _, err := baseURL(raw); err == nil {
			t.Errorf("baseURL(%q) expected an error, got nil", raw)
		}
	}
}
