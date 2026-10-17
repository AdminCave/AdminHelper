// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package main

import (
	"fmt"
	"os"
	"regexp"
	"slices"
	"strings"
	"testing"
)

// The SMART check needs smartctl, but the agent runs without it and the report then
// names the reason (smart_absent). So both packages carry smartmontools as a weak
// dependency, which apt and dnf install by default, and never as a hard one.

var (
	// A control field; a line starting with a blank continues the previous field.
	debField = regexp.MustCompile(`^([A-Za-z0-9-]+):(.*)$`)
	// A spec tag, optionally qualified: Requires(post): systemd.
	specTag = regexp.MustCompile(`^([A-Za-z]+)(?:\([^)]*\))?:(.*)$`)
)

// smartmontoolsProblems lists what is wrong with how a control file (deb) or a spec
// names smartmontools: exactly one Recommends line, and no Depends/Requires line.
// Field names are case-insensitive in both formats.
func smartmontoolsProblems(content string, deb bool) []string {
	type field struct {
		name, value string
		line        int
	}
	re, hard := specTag, []string{"requires"}
	if deb {
		re, hard = debField, []string{"depends", "pre-depends"}
	}
	var fields []field
	// A Windows checkout (core.autocrlf) ends every line in \r\n.
	for i, line := range strings.Split(strings.ReplaceAll(content, "\r\n", "\n"), "\n") {
		if deb && len(fields) > 0 && (strings.HasPrefix(line, " ") || strings.HasPrefix(line, "\t")) {
			fields[len(fields)-1].value += " " + line
			continue
		}
		if m := re.FindStringSubmatch(line); m != nil {
			fields = append(fields, field{strings.ToLower(m[1]), m[2], i + 1})
		}
	}
	var problems []string
	recommends := 0
	for _, f := range fields {
		// Entries split at commas, alternatives and blanks, so "(>= 7)" stays apart.
		names := strings.FieldsFunc(f.value, func(r rune) bool { return strings.ContainsRune(", \t|", r) })
		if !slices.Contains(names, "smartmontools") {
			continue
		}
		switch {
		case f.name == "recommends":
			recommends++
		case slices.Contains(hard, f.name):
			problems = append(problems, fmt.Sprintf("line %d: smartmontools in %s, a hard dependency", f.line, f.name))
		}
	}
	if recommends != 1 {
		problems = append(problems, fmt.Sprintf("%d Recommends lines name smartmontools, want exactly 1", recommends))
	}
	return problems
}

func TestPackagesRecommendSmartmontools(t *testing.T) {
	for _, path := range []string{"../../deb/DEBIAN/control", "../../rpm/adminhelper-agent.spec"} {
		t.Run(path, func(t *testing.T) {
			data, err := os.ReadFile(path)
			if err != nil {
				t.Fatalf("read %s: %v", path, err)
			}
			for _, p := range smartmontoolsProblems(string(data), strings.HasSuffix(path, "control")) {
				t.Errorf("%s: %s", path, p)
			}
		})
	}
}

// The check itself has to be able to fail, or a green run proves nothing.
func TestPackagingCheckCatchesMisplacedSmartmontools(t *testing.T) {
	for _, tc := range []struct {
		name, content string
		deb           bool
		want          int // number of problems
	}{
		{"deb recommends", "Depends: systemd\nRecommends: smartmontools\n", true, 0},
		{"deb missing", "Depends: systemd\n", true, 1},
		{"deb hard dependency", "Depends: systemd, smartmontools (>= 7)\n", true, 2},
		{"deb continuation line", "Depends: systemd,\n smartmontools\nRecommends: smartmontools\n", true, 1},
		{"deb pre-depends", "Pre-Depends: smartmontools\nRecommends: smartmontools\n", true, 1},
		{"deb twice", "Recommends: smartmontools\nrecommends: foo, smartmontools\n", true, 1},
		{"deb other package", "Recommends: smartmontools-extra\n", true, 1},
		{"rpm recommends", "Requires:       systemd\nRecommends:     smartmontools\n", false, 0},
		{"rpm hard dependency", "Requires:       smartmontools\n", false, 2},
		{"rpm qualified requires", "Requires(post): smartmontools\nRecommends: smartmontools\n", false, 1},
		// A Windows checkout (core.autocrlf) hands the test CRLF files.
		{"deb crlf", "Depends: systemd\r\nRecommends: smartmontools\r\n", true, 0},
		{"rpm crlf", "Requires:       systemd\r\nRecommends:     smartmontools\r\n", false, 0},
	} {
		t.Run(tc.name, func(t *testing.T) {
			if got := smartmontoolsProblems(tc.content, tc.deb); len(got) != tc.want {
				t.Errorf("got %d problems %q, want %d", len(got), got, tc.want)
			}
		})
	}
}
