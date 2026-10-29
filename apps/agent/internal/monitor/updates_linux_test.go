// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build linux

package monitor

import (
	"context"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
	"time"
)

// updatesNow is the clock of the stubbed hourly count.
var updatesNow = time.Unix(1_760_940_000, 0)

// updatesCall is one count as updatesCalls.run got it.
type updatesCall struct {
	timeout time.Duration
	env     []string
	argv    []string
}

// stubUpdates sets the clock of the hourly count to now and answers every count with reply; it
// returns the recorded calls. Which tool is on the path stays with stubSystemCLI.
func stubUpdates(t *testing.T, now time.Time, reply dockerReply) *[]updatesCall {
	t.Helper()
	old := updatesCalls
	t.Cleanup(func() { updatesCalls = old })
	var calls []updatesCall
	updatesCalls.now = func() time.Time { return now }
	updatesCalls.run = func(_ context.Context, timeout time.Duration, env []string, name string, args ...string) ([]byte, error) {
		calls = append(calls, updatesCall{timeout, env, append([]string{name}, args...)})
		return []byte(reply.out), reply.err
	}
	return &calls
}

// aptDebianFixture is apt-get -s dist-upgrade in the form of Debian 12 with four security updates: a
// new kernel package, the kernel meta package, libssl3 and openssl (marked broken by the trailing
// []). tzdata comes from stable-updates; security-tools only carries the word in its name and
// version. Conf and Remv lines repeat packages and are no updates of their own. The Inst and Conf form
// matches what apt 3.0.3 on Debian 13 prints for a package from stable-security (apt-get -s install
// --reinstall).
const aptDebianFixture = `NOTE: This is only a simulation!
      apt-get needs root privileges for real execution.
      Keep also in mind that locking is deactivated,
      so don't depend on the relevance to the real current situation!
Reading package lists...
Building dependency tree...
Reading state information...
Calculating upgrade...
The following packages will be REMOVED:
  linux-image-6.1.0-37-amd64
The following NEW packages will be installed:
  linux-image-6.1.0-41-amd64
The following packages will be upgraded:
  libssl3 linux-image-amd64 openssl security-tools tzdata
5 upgraded, 1 newly installed, 1 to remove and 0 not upgraded.
Remv linux-image-6.1.0-37-amd64 [6.1.140-1]
Inst linux-image-6.1.0-41-amd64 (6.1.158-1 Debian-Security:12/stable-security [amd64])
Inst linux-image-amd64 [6.1.140-1] (6.1.158-1 Debian-Security:12/stable-security [amd64])
Inst libssl3 [3.0.17-1~deb12u2] (3.0.17-1~deb12u3 Debian-Security:12/stable-security [amd64])
Inst openssl [3.0.17-1~deb12u2] (3.0.17-1~deb12u3 Debian-Security:12/stable-security [amd64]) []
Inst tzdata [2025b-0+deb12u1] (2025b-0+deb12u2 Debian:12.12/stable-updates [all])
Inst security-tools [1.0-1] (1.0-2+security1 Debian:12.12/stable [amd64])
Conf linux-image-6.1.0-41-amd64 (6.1.158-1 Debian-Security:12/stable-security [amd64])
Conf linux-image-amd64 (6.1.158-1 Debian-Security:12/stable-security [amd64])
Conf libssl3 (3.0.17-1~deb12u3 Debian-Security:12/stable-security [amd64])
Conf openssl (3.0.17-1~deb12u3 Debian-Security:12/stable-security [amd64])
Conf tzdata (2025b-0+deb12u2 Debian:12.12/stable-updates [all])
Conf security-tools (1.0-2+security1 Debian:12.12/stable [amd64])
`

// aptUbuntuFixture is apt-get -s dist-upgrade in the form of Ubuntu 24.04: libc6 and libc-bin come
// from two origins at once, updates and security, snapd from updates alone.
const aptUbuntuFixture = `Reading package lists...
Building dependency tree...
Reading state information...
Calculating upgrade...
The following packages will be upgraded:
  libc-bin libc6 snapd
3 upgraded, 0 newly installed, 0 to remove and 0 not upgraded.
Inst libc6 [2.39-0ubuntu8.5] (2.39-0ubuntu8.6 Ubuntu:24.04/noble-updates, Ubuntu:24.04/noble-security [amd64]) []
Inst libc-bin [2.39-0ubuntu8.5] (2.39-0ubuntu8.6 Ubuntu:24.04/noble-updates, Ubuntu:24.04/noble-security [amd64])
Inst snapd [2.67.1+24.04] (2.68.5+24.04 Ubuntu:24.04/noble-updates [amd64])
Conf libc6 (2.39-0ubuntu8.6 Ubuntu:24.04/noble-updates, Ubuntu:24.04/noble-security [amd64])
Conf libc-bin (2.39-0ubuntu8.6 Ubuntu:24.04/noble-updates, Ubuntu:24.04/noble-security [amd64])
Conf snapd (2.68.5+24.04 Ubuntu:24.04/noble-updates [amd64])
`

// dnfFixture is dnf -C -q updateinfo list --security in the form of RHEL 9 (dnf 4) with three
// packages: openssl-libs in two advisories, kernel in two newer versions from two advisories.
const dnfFixture = `RHSA-2025:4051 Important/Sec. openssl-1:3.2.2-6.el9_5.1.x86_64
RHSA-2025:4051 Important/Sec. openssl-libs-1:3.2.2-6.el9_5.1.x86_64
RHSA-2025:4492 Moderate/Sec.  openssl-libs-1:3.2.2-6.el9_5.1.x86_64
RHSA-2025:7020 Important/Sec. kernel-5.14.0-503.38.1.el9_5.x86_64
RHSA-2025:7589 Important/Sec. kernel-5.14.0-503.40.1.el9_5.x86_64
`

func TestSystemStateUpdatesCountApt(t *testing.T) {
	cases := []struct {
		name string
		out  string
		want int
	}{
		{"Debian", aptDebianFixture, 4},
		{"Ubuntu, two origins in one line", aptUbuntuFixture, 2},
		{"only a capitalised label names it",
			"Inst libfoo1 [1.0-1] (1.0-1+deb10u1 Debian-Security:10/oldoldstable [amd64])\n", 1},
		{"no parenthesis", "Inst libfoo1 [1.0-1]\n", 0},
		{"nothing to upgrade", "Calculating upgrade...\n0 upgraded, 0 newly installed, 0 to remove and 0 not upgraded.\n", 0},
		{"empty", "", 0},
	}
	for _, c := range cases {
		if got := countAptSecurity([]byte(c.out)); got != c.want {
			t.Errorf("%s: countAptSecurity = %d, want %d", c.name, got, c.want)
		}
	}
}

func TestSystemStateUpdatesCountDNF(t *testing.T) {
	cases := []struct {
		name string
		out  string
		want int
		ok   bool
	}{
		{"one package in two advisories counts once", dnfFixture, 3, true},
		{"no advisory", "", 0, true},
		{"only blank lines", "\n\n", 0, true},
		// The columns of dnf5 advisory list, which this parser does not know.
		{"other columns", "Name           Type     Severity  Package                              Issued\n" +
			"FEDORA-2025-1a security Important openssl-libs-1:3.2.4-3.fc42.x86_64 2025-10-01 12:00:00\n", 0, false},
		{"a message among the advisories", dnfFixture + "Error: Cache-only enabled but no cache for 'baseos'\n", 0, false},
		{"no NEVRA", "RHSA-2025:4051 Important/Sec. openssl\n", 0, false},
		{"only a version", "RHSA-2025:4051 Important/Sec. openssl-3.2.2\n", 0, false},
	}
	for _, c := range cases {
		got, ok := countDNFSecurity([]byte(c.out))
		if got != c.want || ok != c.ok {
			t.Errorf("%s: countDNFSecurity = %d, %v; want %d, %v", c.name, got, ok, c.want, c.ok)
		}
	}
}

func TestSystemStateUpdatesTools(t *testing.T) {
	// apt-get runs under updatesTimeout with LC_ALL=C and without the network (-s), also with dnf on
	// the path; dnf runs from its cache (-C). The count is saved with the time it was taken.
	cases := []struct {
		name  string
		tools map[string]dockerReply
		reply string
		want  updatesCall
		count int
	}{
		{"apt-get", map[string]dockerReply{"apt-get": {}}, aptUbuntuFixture,
			updatesCall{30 * time.Second, []string{"LC_ALL=C"}, []string{"apt-get", "-s", "dist-upgrade"}}, 2},
		{"apt-get and dnf", map[string]dockerReply{"apt-get": {}, "dnf": {}}, aptUbuntuFixture,
			updatesCall{30 * time.Second, []string{"LC_ALL=C"}, []string{"apt-get", "-s", "dist-upgrade"}}, 2},
		{"dnf", map[string]dockerReply{"dnf": {}}, dnfFixture,
			updatesCall{30 * time.Second, nil, []string{"dnf", "-C", "-q", "updateinfo", "list", "--security"}}, 3},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			stubSystemCLI(t, c.tools)
			calls := stubUpdates(t, updatesNow, dockerReply{out: c.reply})
			logs := captureWarnings(t)
			check := securityUpdates(context.Background(), nil)
			if check == nil || check.Security == nil || *check.Security != c.count ||
				check.CheckedUnix != updatesNow.Unix() {
				t.Errorf("securityUpdates(context.Background(), nil) = %+v, want %d counted at %d", check, c.count, updatesNow.Unix())
			}
			if want := []updatesCall{c.want}; !reflect.DeepEqual(*calls, want) {
				t.Errorf("calls = %+v, want %+v", *calls, want)
			}
			assertSystemStateLog(t, logs.String(), "")
		})
	}
}

func TestSystemStateUpdatesNoTool(t *testing.T) {
	// Neither apt-get nor dnf: nothing to count, which is no failure. No check, no call, no warning.
	stubSystemCLI(t, map[string]dockerReply{"needs-restarting": {}})
	calls := stubUpdates(t, updatesNow, dockerReply{})
	logs := captureWarnings(t)
	if check := securityUpdates(context.Background(), nil); check != nil {
		t.Errorf("securityUpdates(context.Background(), nil) = %+v, want nil", check)
	}
	if len(*calls) != 0 {
		t.Errorf("calls = %+v, want none", *calls)
	}
	assertSystemStateLog(t, logs.String(), "")
}

func TestSystemStateUpdatesHourly(t *testing.T) {
	// A count younger than an hour is reported again without a call, also a failed one (no number);
	// an older one, one from the future (the clock was set back) and none at all are counted anew.
	three := 3
	cases := []struct {
		name  string
		saved *updatesCheck
		call  bool
	}{
		{"none saved", nil, true},
		{"59 min old", &updatesCheck{CheckedUnix: updatesNow.Add(-59 * time.Minute).Unix(), Security: &three}, false},
		{"failed 59 min ago", &updatesCheck{CheckedUnix: updatesNow.Add(-59 * time.Minute).Unix()}, false},
		{"just now", &updatesCheck{CheckedUnix: updatesNow.Unix(), Security: &three}, false},
		{"one hour old", &updatesCheck{CheckedUnix: updatesNow.Add(-time.Hour).Unix(), Security: &three}, true},
		{"failed 61 min ago", &updatesCheck{CheckedUnix: updatesNow.Add(-61 * time.Minute).Unix()}, true},
		{"from the future", &updatesCheck{CheckedUnix: updatesNow.Add(5 * time.Minute).Unix(), Security: &three}, true},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			stubSystemCLI(t, map[string]dockerReply{"apt-get": {}})
			calls := stubUpdates(t, updatesNow, dockerReply{out: aptDebianFixture})
			check := securityUpdates(context.Background(), c.saved)
			if !c.call {
				if check != c.saved || len(*calls) != 0 {
					t.Errorf("securityUpdates = %+v after %d call(s), want the saved %+v without one",
						check, len(*calls), c.saved)
				}
				return
			}
			if len(*calls) != 1 || check == nil || check.Security == nil || *check.Security != 4 ||
				check.CheckedUnix != updatesNow.Unix() {
				t.Errorf("securityUpdates = %+v after %d call(s), want 4 counted now in one call", check, len(*calls))
			}
		})
	}
}

func TestSystemStateUpdatesFailure(t *testing.T) {
	// A count that fails, hangs or prints what the parser does not know leaves the field out, and the
	// log says why, short and without stderr. The attempt is saved, through the state file too, so
	// the next report within the hour neither counts again nor sends a field.
	cases := []struct {
		name  string
		tools map[string]dockerReply
		reply dockerReply
		log   string
	}{
		{"apt-get fails", map[string]dockerReply{"apt-get": {}}, dockerReply{err: exitStatus(t, 100)},
			"apt-get -s dist-upgrade failed: exit status 100, " + updatesLeftOut},
		{"apt-get times out", map[string]dockerReply{"apt-get": {}}, dockerReply{err: context.DeadlineExceeded},
			"apt-get -s dist-upgrade failed: timed out after 30s, " + updatesLeftOut},
		{"dnf fails", map[string]dockerReply{"dnf": {}}, dockerReply{err: exitStatus(t, 1)},
			"dnf updateinfo list --security failed: exit status 1, " + updatesLeftOut},
		{"dnf times out", map[string]dockerReply{"dnf": {}}, dockerReply{err: context.DeadlineExceeded},
			"dnf updateinfo list --security failed: timed out after 30s, " + updatesLeftOut},
		{"dnf output unreadable", map[string]dockerReply{"dnf": {}}, dockerReply{out: "Last metadata expiration check: 0:04:12 ago\n"},
			"unexpected output of dnf updateinfo list --security, " + updatesLeftOut},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			stubSystemCLI(t, c.tools)
			stubVMStat(t, "pgmajfault 1042\n")
			calls := stubUpdates(t, updatesNow, c.reply)
			logs := captureWarnings(t)
			block, next := collectSystemState(context.Background(), reportState{})
			if _, ok := block["security_updates"]; ok {
				t.Errorf("block = %v, want no security_updates", block)
			}
			if next.Updates == nil || next.Updates.Security != nil || next.Updates.CheckedUnix != updatesNow.Unix() {
				t.Errorf("state updates = %+v, want the attempt at %d without a number", next.Updates, updatesNow.Unix())
			}
			assertSystemStateLog(t, logs.String(), c.log)

			path := filepath.Join(t.TempDir(), ".report-state.json")
			if err := saveReportState(path, next); err != nil {
				t.Fatal(err)
			}
			raw, err := os.ReadFile(path)
			if err != nil {
				t.Fatal(err)
			}
			if want := fmt.Sprintf(`"updates":{"checked_unix":%d,"security":null}`, updatesNow.Unix()); !strings.Contains(string(raw), want) {
				t.Errorf("state file = %s, want it to hold %s", raw, want)
			}
			updatesCalls.now = func() time.Time { return updatesNow.Add(55 * time.Minute) }
			block, next = collectSystemState(context.Background(), loadReportState(path))
			if _, ok := block["security_updates"]; ok || len(*calls) != 1 {
				t.Errorf("next report: block = %v after %d call(s), want no security_updates and no new call",
					block, len(*calls))
			}
			if next.Updates == nil || next.Updates.CheckedUnix != updatesNow.Unix() {
				t.Errorf("next report: state updates = %+v, want the attempt kept", next.Updates)
			}
		})
	}
}

// updatesHelperEnv tells TestHelperSystemStateUpdatesProcess, run as a child process, what to do.
const updatesHelperEnv = "AH_UPDATES_HELPER"

// TestHelperSystemStateUpdatesProcess is no test of its own: the runTimedEnv test starts the test
// binary as its child process, which prints its LC_ALL or hangs as updatesHelperEnv says. Without
// it, it returns at once.
func TestHelperSystemStateUpdatesProcess(t *testing.T) {
	switch os.Getenv(updatesHelperEnv) {
	case "env":
		fmt.Printf("LC_ALL=%s\n", os.Getenv("LC_ALL"))
		os.Exit(0)
	case "hang":
		time.Sleep(time.Minute)
	}
}

func TestSystemStateUpdatesRunTimedEnv(t *testing.T) {
	// The stubs above see what the count passes; this is the proof that the real call hands it on: the
	// child gets LC_ALL=C over the agent's own, and a hanging child is the timeout, as with runTimed.
	t.Run("environment", func(t *testing.T) {
		t.Setenv(updatesHelperEnv, "env")
		t.Setenv("LC_ALL", "de_DE.UTF-8")
		out, err := updatesCalls.run(context.Background(), time.Minute, []string{"LC_ALL=C"}, os.Args[0],
			"-test.run=^TestHelperSystemStateUpdatesProcess$")
		if err != nil || !strings.Contains(string(out), "LC_ALL=C\n") {
			t.Errorf("child = %q, %v; want it to see LC_ALL=C", out, err)
		}
	})
	t.Run("hangs", func(t *testing.T) {
		t.Setenv(updatesHelperEnv, "hang")
		start := time.Now()
		_, err := updatesCalls.run(context.Background(), 100*time.Millisecond, nil, os.Args[0],
			"-test.run=^TestHelperSystemStateUpdatesProcess$")
		if !errors.Is(err, context.DeadlineExceeded) {
			t.Fatalf("err = %v, want context.DeadlineExceeded", err)
		}
		if elapsed := time.Since(start); elapsed > 30*time.Second {
			t.Errorf("run returned after %s, the timeout did not stop the hung call", elapsed)
		}
	})
	// R-0638: the caller's context ends the call long before updatesTimeout, and the call says why.
	t.Run("ends with the context", func(t *testing.T) {
		t.Setenv(updatesHelperEnv, "hang")
		ctx, cancel := context.WithCancel(context.Background())
		defer cancel()
		time.AfterFunc(100*time.Millisecond, cancel)
		start := time.Now()
		_, err := updatesCalls.run(ctx, time.Minute, nil, os.Args[0],
			"-test.run=^TestHelperSystemStateUpdatesProcess$")
		if !errors.Is(err, context.Canceled) {
			t.Errorf("err = %v, want context.Canceled", err)
		}
		if elapsed := time.Since(start); elapsed > 5*time.Second {
			t.Errorf("run returned after %s, the context did not end the call", elapsed)
		}
	})
	// As with runTimed: the timeout kills the tool, not the grandchild that holds its stdout, and
	// WaitDelay ends the wait for the pipe. The "orphan" mode of TestHelperDockerProcess, chosen through
	// env, is that tool.
	t.Run("a grandchild holds stdout", func(t *testing.T) {
		start := time.Now()
		out, err := updatesCalls.run(context.Background(), time.Second, []string{dockerHelperEnv + "=orphan"}, os.Args[0],
			"-test.run=^TestHelperDockerProcess$")
		elapsed := time.Since(start)
		if !strings.Contains(string(out), orphanStarted) {
			t.Fatalf("output = %q, the grandchild did not start before the timeout", out)
		}
		if !errors.Is(err, context.DeadlineExceeded) {
			t.Errorf("err = %v, want context.DeadlineExceeded", err)
		}
		if elapsed > 10*time.Second {
			t.Errorf("run returned after %s, the grandchild held it past the timeout", elapsed)
		}
	})
}

// A command that exits 0 while a child it started still holds its stdout ends after
// commandWaitDelay with exec.ErrWaitDelay; its output is complete, so runTimed and runTimedEnv
// return it without an error.
func TestRunTimedTakesErrWaitDelayAsSuccess(t *testing.T) {
	const script = "sleep 5 & echo ok"
	for name, run := range map[string]func() ([]byte, error){
		"runTimed": func() ([]byte, error) {
			return runTimed(context.Background(), time.Minute, "sh", "-c", script)
		},
		"runTimedEnv": func() ([]byte, error) {
			return runTimedEnv(context.Background(), time.Minute, []string{"LC_ALL=C"}, "sh", "-c", script)
		},
	} {
		t.Run(name, func(t *testing.T) {
			t.Parallel()
			if _, err := exec.LookPath("sh"); err != nil {
				t.Fatal(err)
			}
			out, err := run()
			if err != nil || string(out) != "ok\n" {
				t.Errorf("%s = %q, %v; want \"ok\\n\", nil", name, out, err)
			}
		})
	}
}
