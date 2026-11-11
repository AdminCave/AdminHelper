// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package service

import (
	"regexp"
	"strconv"
	"strings"
	"testing"
)

// The agent's cron.d file on FreeBSD holds one system crontab job (crontab(5)): every five
// minutes, as root, the absolute agent path with run --once, at nice 19, under a timeout(1) cap
// whose SIGTERM and SIGKILL both come before the next run, output discarded. Environment lines
// are NAME=value, and every line ends in a newline.
func TestCronTableRunsTheAgentOnceEveryFiveMinutes(t *testing.T) {
	const bin = "/usr/local/bin/adminhelper-agent"
	table := cronTable(bin)
	if !strings.HasSuffix(table, "\n") {
		t.Fatalf("the table does not end in a newline:\n%s", table)
	}
	envLine := regexp.MustCompile(`^[A-Z]+=\S+$`)
	var jobs []string
	env := map[string]string{}
	for _, line := range strings.Split(strings.TrimSuffix(table, "\n"), "\n") {
		switch {
		case strings.HasPrefix(line, "#"):
		case envLine.MatchString(line):
			name, value, _ := strings.Cut(line, "=")
			env[name] = value
		default:
			jobs = append(jobs, line)
		}
	}
	if len(jobs) != 1 {
		t.Fatalf("want exactly one job line, got %d: %q", len(jobs), jobs)
	}
	if env["SHELL"] != "/bin/sh" {
		t.Errorf("SHELL = %q, want /bin/sh", env["SHELL"])
	}
	for _, dir := range []string{"/usr/sbin", "/usr/local/sbin"} {
		if !strings.Contains(":"+env["PATH"]+":", ":"+dir+":") {
			t.Errorf("PATH %q lacks %s, where service and pkg live", env["PATH"], dir)
		}
	}

	job := jobs[0]
	if strings.Contains(job, "%") {
		t.Errorf("cron turns %% into a newline, the job must not hold one: %q", job)
	}
	fields := strings.Fields(job)
	if len(fields) < 7 {
		t.Fatalf("want five time fields, the user and a command, got %q", job)
	}
	if got := strings.Join(fields[:5], " "); got != "*/5 * * * *" {
		t.Errorf("schedule = %q, want */5 * * * *", got)
	}
	if fields[5] != "root" {
		t.Errorf("user = %q, want root", fields[5])
	}
	cmd := strings.Join(fields[6:], " ")
	m := regexp.MustCompile(`^/usr/bin/nice -n 19 /usr/bin/timeout -k (\d+) (\d+) (\S+) run --once >/dev/null 2>&1$`).FindStringSubmatch(cmd)
	if m == nil {
		t.Fatalf("command = %q, want nice 19, timeout -k <s> <s>, the agent run --once, output discarded", cmd)
	}
	killAfter, _ := strconv.Atoi(m[1])
	limit, _ := strconv.Atoi(m[2])
	if limit < 1 || killAfter < 1 || limit+killAfter >= 300 {
		t.Errorf("timeout %d s plus kill-after %d s must stay below the 300 s interval", limit, killAfter)
	}
	if m[3] != bin {
		t.Errorf("agent path = %q, want %q", m[3], bin)
	}
}
