// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build windows

package monitor

import (
	"bytes"
	"context"
	"testing"
)

// TestServiceLogQueriesRun runs the two event queries of the error lines on this host: the allowlist
// takes them, wevtutil takes the XPath and /f:RenderedXml (the wevtutil page documents only xml and
// text; an unknown format exits non-zero) and prints events the parser reads, each with its rendered
// message. A log without a matching event in 24 hours prints nothing.
func TestServiceLogQueriesRun(t *testing.T) {
	for _, args := range [][]string{scmLogArgs, appLogArgs} {
		out, err := runWithTimeout(context.Background(), "wevtutil", args...)
		if err != nil {
			t.Fatalf("wevtutil %q: %v", args, err)
		}
		trimmed := bytes.TrimSpace(out)
		if len(trimmed) == 0 {
			continue
		}
		if !bytes.HasPrefix(trimmed, []byte("<Event")) {
			t.Fatalf("%s: output does not start with <Event: %q", args[1], trimmed[:min(len(trimmed), 80)])
		}
		lines := parseWinLogEvents(out)
		if len(lines) == 0 {
			t.Fatalf("%s: %d bytes of events, none parsed", args[1], len(out))
		}
		if !bytes.Contains(out, []byte("<RenderingInfo")) {
			t.Errorf("%s: no RenderingInfo in the output", args[1])
		}
	}
}
