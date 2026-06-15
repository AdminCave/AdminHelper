// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Package diagnostics writes a REDACTED agent-side report for a bug report:
// version, host/OS, the agent config (secret values masked) and the tail of the
// rotating log file. Secrets are masked two ways — config keys that look secret
// (API_KEY, *TOKEN, *SECRET) and generic token shapes (JWT, Bearer, ah_ keys).
// The report is best-effort redacted; the operator should still skim it.
package diagnostics

import (
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"runtime"
	"strings"
	"time"

	"adminhelper-agent/internal/config"
)

const logTailLines = 300

var (
	reJWT    = regexp.MustCompile(`eyJ[A-Za-z0-9_-]{6,}\.[A-Za-z0-9_-]{6,}\.[A-Za-z0-9_-]*`)
	reBearer = regexp.MustCompile(`(?i)bearer [A-Za-z0-9._-]{8,}`)
	reAPIKey = regexp.MustCompile(`ah_[A-Za-z0-9_-]{8,}`)
)

// Run builds the report, redacts it, writes it to a temp file and prints the path.
func Run(version string) error {
	ts := time.Now().UTC().Format("20060102T150405Z")
	host, _ := os.Hostname()

	var b strings.Builder
	b.WriteString("AdminHelper agent diagnostics — " + ts + "\n")
	b.WriteString("======================================================================\n\n")
	fmt.Fprintf(&b, "version : %s\n", version)
	fmt.Fprintf(&b, "os/arch : %s/%s\n", runtime.GOOS, runtime.GOARCH)
	fmt.Fprintf(&b, "host    : %s\n", host)

	if data, err := os.ReadFile("/etc/os-release"); err == nil {
		b.WriteString("\n## OS\n")
		for _, line := range strings.Split(string(data), "\n") {
			if strings.HasPrefix(line, "PRETTY_NAME=") || strings.HasPrefix(line, "VERSION=") {
				b.WriteString(line + "\n")
			}
		}
	}

	b.WriteString("\n## Config (secret values masked)\n")
	for _, f := range []string{config.MonitorConfFile(), config.FrpAdminHelperConf()} {
		fmt.Fprintf(&b, "\n# %s\n", f)
		if content, err := os.ReadFile(f); err == nil {
			b.WriteString(redactConfig(string(content)))
		} else {
			fmt.Fprintf(&b, "(not present: %v)\n", err)
		}
	}

	fmt.Fprintf(&b, "\n## Log (%s, last %d lines)\n", config.LogFile(), logTailLines)
	b.WriteString(tailFile(config.LogFile(), logTailLines))

	report := redactGeneric(b.String())
	out := filepath.Join(os.TempDir(), "adminhelper-agent-diagnostics-"+ts+".txt")
	if err := os.WriteFile(out, []byte(report), 0o600); err != nil {
		return fmt.Errorf("Bericht schreiben: %w", err)
	}

	fmt.Printf("Diagnose-Bericht erstellt: %s\n", out)
	fmt.Println("Bitte vor dem Senden durchsehen (Redaction ist Best-effort) und an ein")
	fmt.Println("GitHub-Issue anhaengen: https://github.com/ks98/AdminHelper/issues/new/choose")
	return nil
}

// redactConfig masks the value of any KEY=VALUE line whose key looks secret.
func redactConfig(content string) string {
	var out strings.Builder
	for _, line := range strings.Split(content, "\n") {
		out.WriteString(redactConfigLine(line) + "\n")
	}
	return out.String()
}

func redactConfigLine(line string) string {
	i := strings.Index(line, "=")
	if i < 0 {
		return line
	}
	key := strings.ToUpper(strings.TrimSpace(line[:i]))
	for _, marker := range []string{"API_KEY", "TOKEN", "SECRET", "PASSWORD"} {
		if strings.Contains(key, marker) {
			return line[:i+1] + "<redacted>"
		}
	}
	return line
}

// redactGeneric masks token shapes that may appear anywhere (e.g. in the log).
func redactGeneric(s string) string {
	s = reJWT.ReplaceAllString(s, "<redacted-jwt>")
	s = reBearer.ReplaceAllString(s, "Bearer <redacted>")
	s = reAPIKey.ReplaceAllString(s, "ah_<redacted>")
	return s
}

// tailFile returns the last n lines of a file (best-effort; reads the whole file,
// which is fine since the log is size-capped by rotation).
func tailFile(path string, n int) string {
	data, err := os.ReadFile(path)
	if err != nil {
		return fmt.Sprintf("(log not available: %v)\n", err)
	}
	lines := strings.Split(strings.TrimRight(string(data), "\n"), "\n")
	if len(lines) > n {
		lines = lines[len(lines)-n:]
	}
	return strings.Join(lines, "\n") + "\n"
}
