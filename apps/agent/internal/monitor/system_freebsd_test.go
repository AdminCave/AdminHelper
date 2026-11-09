// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build freebsd

package monitor

import (
	"context"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
)

func TestFreebsdVersionsNative(t *testing.T) {
	// The real freebsd-version prints one readable line per flag; the running version is the kernel's
	// own release.
	jailed := inContainer()
	versions, why := readFreeBSDVersions(context.Background(), jailed)
	if why != "" {
		t.Fatalf("readFreeBSDVersions: %s", why)
	}
	if jailed {
		if versions.userland == "" || versions.kernel != "" || versions.running != "" {
			t.Fatalf("versions in a jail = %+v, want the userland only", versions)
		}
		return
	}
	out, err := exec.Command("/sbin/sysctl", "-n", "kern.osrelease").Output()
	if err != nil {
		t.Fatalf("sysctl: %v", err)
	}
	if versions.kernel == "" || versions.userland == "" || versions.running != strings.TrimSpace(string(out)) {
		t.Fatalf("versions = %+v, want all three, running %q", versions, strings.TrimSpace(string(out)))
	}
}

func TestFreebsdSystemStateNative(t *testing.T) {
	// On a host the block carries reboot_required; whether the count succeeds depends on the box's
	// vuln.xml, which TestPkgAuditNative pins with its own.
	if inContainer() {
		t.Fatal("run on a host: a jail reports no reboot_required")
	}
	block, _ := collectSystemState(context.Background(), reportState{})
	if _, ok := block["reboot_required"].(bool); !ok {
		t.Fatalf("block = %v, want reboot_required", block)
	}
}

// vulnXMLFixture is a vuln.xml in the VuXML form of the ports' security/vuxml with one entry for the
// base system and the kernel of 15.0 below patch level 2.
const vulnXMLFixture = `<?xml version="1.0" encoding="utf-8"?>
<vuxml xmlns="http://www.vuxml.org/apps/vuxml-1">
  <vuln vid="00000000-0000-4000-8000-000000000001">
    <topic>FreeBSD -- agent test entry</topic>
    <affects>
      <package>
        <name>FreeBSD</name>
        <range><ge>15.0</ge><lt>15.0_2</lt></range>
      </package>
      <package>
        <name>FreeBSD-kernel</name>
        <range><ge>15.0</ge><lt>15.0_2</lt></range>
      </package>
    </affects>
    <description>
      <body xmlns="http://www.w3.org/1999/xhtml"><p>Test entry.</p></body>
    </description>
    <references>
      <url>https://www.vuxml.org/</url>
    </references>
    <dates>
      <discovery>2026-01-01</discovery>
      <entry>2026-01-01</entry>
    </dates>
  </vuln>
</vuxml>
`

func TestPkgAuditNative(t *testing.T) {
	// pkg-audit(8) documents no exit status; the count relies on exit 1 with a line for a vulnerable
	// name, exit 0 without one, and exit 1 without a line for a missing vuln.xml. The names are checked
	// against a vuln.xml of the test's own (-f), so neither the box's packages nor the network matter.
	if _, err := exec.LookPath(pkgPath); err != nil {
		t.Fatalf("pkg is not installed (%v): the box needs it", err)
	}
	dir := t.TempDir()
	vulnXML := filepath.Join(dir, "vuln.xml")
	if err := os.WriteFile(vulnXML, []byte(vulnXMLFixture), 0o644); err != nil {
		t.Fatal(err)
	}
	cases := []struct {
		names []string
		count int
	}{
		{[]string{"FreeBSD-15.0_1"}, 1},
		{[]string{"FreeBSD-15.0_2"}, 0},
		{[]string{"FreeBSD-15.0_1", "FreeBSD-kernel-15.0_1"}, 2},
		{[]string{"FreeBSD-15.0_2", "FreeBSD-kernel-15.0"}, 1},
		{[]string{"FreeBSD-14.3_5"}, 0},
	}
	for _, c := range cases {
		args := append([]string{"-f", vulnXML}, c.names...)
		if count, ok := pkgAudit(context.Background(), "pkg audit -q", args...); count != c.count || !ok {
			t.Errorf("pkgAudit(%q) = %d, %v, want %d, true", c.names, count, ok, c.count)
		}
	}
	logs := captureWarnings(t)
	missing := filepath.Join(dir, "missing.xml")
	if count, ok := pkgAudit(context.Background(), "pkg audit -q", "-f", missing, "FreeBSD-15.0_1"); count != 0 || ok {
		t.Errorf("pkgAudit without vuln.xml = %d, %v, want 0, false", count, ok)
	}
	if !strings.Contains(logs.String(), "pkg audit -q failed: exit status 1") {
		t.Errorf("log = %q, want the failure named", logs.String())
	}
}
