// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package main

import (
	"log/slog"
	"testing"
)

func TestRunRefusesBadArguments(t *testing.T) {
	cases := map[string][2]string{
		"a listen address off loopback": {"0.0.0.0:0", "/handler"},
		"a path without a slash":        {"127.0.0.1:0", "handler"},
		"no path":                       {"127.0.0.1:0", ""},
		"the health path":               {"127.0.0.1:0", "/healthz"},
	}
	for name, args := range cases {
		if err := run(args[0], args[1], "/nonexistent/frps-policy.json", slog.New(slog.DiscardHandler)); err == nil {
			t.Errorf("%s: run = nil, want an error", name)
		}
	}
}
