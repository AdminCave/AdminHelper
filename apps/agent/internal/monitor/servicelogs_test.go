// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package monitor

import (
	"encoding/json"
	"os"
	"strings"
	"testing"
	"unicode/utf8"
)

// The vectors the monitoring service passes as well (tests/test_service_inventory.py): agent
// and server redact alike.
func TestCleanLogLinePassesTheSharedRedactionVectors(t *testing.T) {
	raw, err := os.ReadFile("../../../monitoring/tests/service_log_redaction.json")
	if err != nil {
		t.Fatal(err)
	}
	var vectors []struct{ Name, In, Out string }
	if err := json.Unmarshal(raw, &vectors); err != nil {
		t.Fatal(err)
	}
	if len(vectors) < 20 {
		t.Fatalf("only %d vectors", len(vectors))
	}
	for _, v := range vectors {
		if got := cleanLogLine(v.In); got != v.Out {
			t.Errorf("%s: cleanLogLine(%q) = %q, want %q", v.Name, v.In, got, v.Out)
		}
	}
}

func TestCleanLogLinePutsALineOnOneLine(t *testing.T) {
	got := cleanLogLine("a\nb\rc\td\x7fe\u0085f g")
	if got != "a b c d e f g" {
		t.Fatalf("got %q", got)
	}
}

func TestCleanLogLineCutsAfterTheRules(t *testing.T) {
	// The key runs across character 300: redacted whole first, then cut. Cut first, its head
	// before character 300 is shorter than 32 characters and no rule would catch it.
	line := strings.Repeat("é", 280) + " QWxhZGRpbjpvcGVuIHNlc2FtZTEyMzQ1Njc4OTA " + strings.Repeat("y", 30)
	got := cleanLogLine(line)
	if n := utf8.RuneCountInString(got); n != maxLogLine {
		t.Fatalf("%d characters", n)
	}
	if !strings.HasSuffix(got, "…") || strings.Contains(got, "QWxhZGRp") || !strings.Contains(got, logRedacted) {
		t.Fatalf("got %q", got)
	}
	if short := "short line"; cleanLogLine(short) != short {
		t.Fatal("a short line changed")
	}
}

func TestCleanLogLineDropsTheTokenAnOverlongLineSplits(t *testing.T) {
	// Half a key is shorter than 32 characters and no rule would catch it after the cut.
	key := "QWxhZGRpbjpvcGVuIHNlc2FtZTEyMzQ1Njc4OTA"
	line := strings.Repeat("a ", 240) + key + strings.Repeat("b", 600)
	got := cleanLogLine(line)
	if strings.Contains(got, "QWxh") {
		t.Fatalf("the split token survived: %q", got)
	}
}

func TestCleanLogLineSurvivesInvalidUTF8(t *testing.T) {
	got := cleanLogLine("bad \xff byte token=abc")
	if got != "bad � byte token=[REDACTED]" {
		t.Fatalf("got %q", got)
	}
}
