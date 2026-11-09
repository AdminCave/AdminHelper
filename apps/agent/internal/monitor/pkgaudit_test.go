// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package monitor

import (
	"context"
	"errors"
	"os/exec"
	"reflect"
	"strings"
	"testing"
	"time"
)

// pkgAuditNow is the clock of the stubbed hourly count on FreeBSD.
var pkgAuditNow = time.Unix(1_760_940_000, 0)

// The command lines of the FreeBSD system state tools as freebsdCalls.run gets them, with the full
// paths spelled out, so a changed path turns the tests red.
const (
	fbsdVersionHost = "/bin/freebsd-version -kru"
	fbsdVersionJail = "/bin/freebsd-version -u"
	fbsdAudit       = "/usr/local/sbin/pkg audit -q"
)

// freebsdCall is one call as freebsdCalls.run got it.
type freebsdCall struct {
	timeout time.Duration
	argv    string
}

// stubFreeBSDCalls sets the clock of the hourly count to pkgAuditNow, finds pkg if hasPkg, and answers
// each call by its command line from replies; a call without a reply fails the test. It returns the
// recorded calls. The Linux count (updatesCalls.run) must not run.
func stubFreeBSDCalls(t *testing.T, hasPkg bool, replies map[string]dockerReply) *[]freebsdCall {
	t.Helper()
	oldCalls, oldUpdates := freebsdCalls, updatesCalls
	t.Cleanup(func() { freebsdCalls, updatesCalls = oldCalls, oldUpdates })
	updatesCalls.now = func() time.Time { return pkgAuditNow }
	updatesCalls.run = func(_ context.Context, _ time.Duration, _ []string, name string, _ ...string) ([]byte, error) {
		t.Errorf("Linux count %s called on FreeBSD", name)
		return nil, errors.New("not stubbed")
	}
	freebsdCalls.lookPath = func(file string) (string, error) {
		if hasPkg && file == "/usr/local/sbin/pkg" {
			return file, nil
		}
		return "", exec.ErrNotFound
	}
	var calls []freebsdCall
	freebsdCalls.run = func(_ context.Context, timeout time.Duration, name string, args ...string) ([]byte, error) {
		argv := strings.Join(append([]string{name}, args...), " ")
		calls = append(calls, freebsdCall{timeout, argv})
		reply, ok := replies[argv]
		if !ok {
			t.Errorf("unexpected call %q", argv)
			return nil, errors.New("not stubbed")
		}
		return []byte(reply.out), reply.err
	}
	return &calls
}

// assertFreeBSDLog checks that logs holds exactly the warnings want, in order, and neither a tool's
// path nor what the tools printed (leak).
func assertFreeBSDLog(t *testing.T, logs string, leak string, want ...string) {
	t.Helper()
	lines := strings.Split(strings.TrimSuffix(logs, "\n"), "\n")
	if logs == "" {
		lines = nil
	}
	if len(lines) != len(want) {
		t.Errorf("log = %q, want %d warning(s) %q", logs, len(want), want)
		return
	}
	for i, w := range want {
		if !strings.Contains(lines[i], w) {
			t.Errorf("warning %d = %q, want it to name %q", i, lines[i], w)
		}
	}
	if strings.Contains(logs, "/usr/local") || strings.Contains(logs, "/bin/freebsd-version") ||
		(leak != "" && strings.Contains(logs, leak)) {
		t.Errorf("log = %q, want it without paths and tool output", logs)
	}
}

func TestFreebsdPkgName(t *testing.T) {
	// 405.pkg-base-audit: sed 's,^,FreeBSD-,;s,-RELEASE-p,_,;s,-RELEASE$,,'.
	cases := []struct{ prefix, release, want string }{
		{"FreeBSD-", "15.0-RELEASE-p3", "FreeBSD-15.0_3"},
		{"FreeBSD-", "15.0-RELEASE", "FreeBSD-15.0"},
		{"FreeBSD-kernel-", "14.3-RELEASE-p12", "FreeBSD-kernel-14.3_12"},
	}
	for _, c := range cases {
		if got := freebsdPkgName(c.prefix, c.release); got != c.want {
			t.Errorf("freebsdPkgName(%q, %q) = %q, want %q", c.prefix, c.release, got, c.want)
		}
	}
}

func TestFreebsdBaseNames(t *testing.T) {
	// Only a release has VuXML entries for the base system; the kernel is the installed one (-k), as
	// 405.pkg-base-audit checks it, and a jail reads none.
	cases := []struct {
		name     string
		versions freebsdVersions
		want     []string
	}{
		{"host, userland patched later than the kernel",
			freebsdVersions{kernel: "15.0-RELEASE-p2", running: "15.0-RELEASE-p1", userland: "15.0-RELEASE-p3"},
			[]string{"FreeBSD-15.0_3", "FreeBSD-kernel-15.0_2"}},
		{"host without patch level",
			freebsdVersions{kernel: "15.0-RELEASE", running: "15.0-RELEASE", userland: "15.0-RELEASE"},
			[]string{"FreeBSD-15.0", "FreeBSD-kernel-15.0"}},
		{"jail", freebsdVersions{userland: "14.3-RELEASE-p5"}, []string{"FreeBSD-14.3_5"}},
		{"stable kernel, release userland",
			freebsdVersions{kernel: "15.0-STABLE", running: "15.0-STABLE", userland: "15.0-RELEASE-p1"},
			[]string{"FreeBSD-15.0_1"}},
		{"release kernel, stable userland",
			freebsdVersions{kernel: "15.0-RELEASE-p1", running: "15.0-RELEASE-p1", userland: "15.0-STABLE"},
			[]string{"FreeBSD-kernel-15.0_1"}},
		{"stable", freebsdVersions{kernel: "15.0-STABLE", running: "15.0-STABLE", userland: "15.0-STABLE"}, nil},
		{"current", freebsdVersions{kernel: "16.0-CURRENT", running: "16.0-CURRENT", userland: "16.0-CURRENT"}, nil},
		{"release candidate", freebsdVersions{kernel: "15.0-RC1-p1", running: "15.0-RC1-p1", userland: "15.0-RC1-p1"}, nil},
		{"beta", freebsdVersions{kernel: "15.0-BETA3", running: "15.0-BETA3", userland: "15.0-BETA3"}, nil},
		{"patch level without number", freebsdVersions{userland: "15.0-RELEASE-p"}, nil},
		{"text before the release", freebsdVersions{userland: "x15.0-RELEASE-p1"}, nil},
		{"text after the patch level", freebsdVersions{userland: "15.0-RELEASE-p1x"}, nil},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			if got := freebsdBaseNames(c.versions); !reflect.DeepEqual(got, c.want) {
				t.Errorf("freebsdBaseNames(%+v) = %q, want %q", c.versions, got, c.want)
			}
		})
	}
}

func TestCountPkgAudit(t *testing.T) {
	// pkg audit -q prints "<name>-<version>" per vulnerable package and nothing else (pkg src/audit.c);
	// any other line makes the output unreadable.
	cases := []struct {
		name  string
		out   string
		count int
		ok    bool
	}{
		{"nothing vulnerable", "", 0, true},
		{"two packages", "curl-8.11.0\nopenssl-3.0.15_1,1\n", 2, true},
		{"name with dashes", "py311-cryptography-43.0.0_1\n", 1, true},
		{"base system", "FreeBSD-15.0_1\nFreeBSD-kernel-15.0_1\n", 2, true},
		{"without final newline", "curl-8.11.0", 1, true},
		{"long form", "curl-8.11.0 is vulnerable:\n", 0, false},
		{"summary line", "0 problem(s) in 0 installed package(s) found.\n", 0, false},
		{"no version", "curl\n", 0, false},
		{"empty version", "curl-\n", 0, false},
		{"empty version after the last dash", "curl-8.11.0-\n", 0, false},
		{"empty name", "-8.11.0\n", 0, false},
		{"leading blank", " curl-8.11.0\n", 0, false},
		{"carriage return", "curl-8.11.0\r\n", 0, false},
		{"one good, one bad", "curl-8.11.0\nvulnxml file vuln.xml does not exist\n", 0, false},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			if count, ok := countPkgAudit([]byte(c.out)); count != c.count || ok != c.ok {
				t.Errorf("countPkgAudit(%q) = %d, %v, want %d, %v", c.out, count, ok, c.count, c.ok)
			}
		})
	}
}

func TestReadFreeBSDVersions(t *testing.T) {
	// One call of freebsd-version under the plugin timeout: -kru on a host, -u in a jail, one line per
	// flag. Any other count or form is unreadable, never shifted into the wrong field.
	host := freebsdVersions{kernel: "15.0-RELEASE-p2", running: "15.0-RELEASE-p1", userland: "15.0-RELEASE-p3"}
	cases := []struct {
		name   string
		jailed bool
		reply  dockerReply
		want   freebsdVersions
		why    string
	}{
		{"host", false, dockerReply{out: "15.0-RELEASE-p2\n15.0-RELEASE-p1\n15.0-RELEASE-p3\n"}, host, ""},
		{"host without final newline", false, dockerReply{out: "15.0-RELEASE-p2\n15.0-RELEASE-p1\n15.0-RELEASE-p3"}, host, ""},
		{"jail", true, dockerReply{out: "14.3-RELEASE-p5\n"}, freebsdVersions{userland: "14.3-RELEASE-p5"}, ""},
		{"kernel not found (a line too few)", false, dockerReply{out: "15.0-RELEASE-p1\n15.0-RELEASE-p3\n"}, freebsdVersions{},
			"unexpected output of freebsd-version -kru"},
		{"a line too many", false, dockerReply{out: "15.0-RELEASE-p2\n15.0-RELEASE-p1\n15.0-RELEASE-p3\n15.0-RELEASE-p3\n"},
			freebsdVersions{}, "unexpected output of freebsd-version -kru"},
		{"empty line", false, dockerReply{out: "15.0-RELEASE-p2\n\n15.0-RELEASE-p3\n"}, freebsdVersions{},
			"unexpected output of freebsd-version -kru"},
		{"jail, three lines", true, dockerReply{out: "15.0-RELEASE-p2\n15.0-RELEASE-p1\n15.0-RELEASE-p3\n"}, freebsdVersions{},
			"unexpected output of freebsd-version -u"},
		{"jail, nothing", true, dockerReply{}, freebsdVersions{}, "unexpected output of freebsd-version -u"},
		{"blank inside a line", true, dockerReply{out: "14.3-RELEASE p5\n"}, freebsdVersions{},
			"unexpected output of freebsd-version -u"},
		{"fails", false, dockerReply{err: smartctlExit(t, 1)}, freebsdVersions{},
			"freebsd-version -kru failed: exit status 1"},
		{"times out", false, dockerReply{err: context.DeadlineExceeded}, freebsdVersions{},
			"freebsd-version -kru failed: timed out after 15s"},
		{"does not start", true, dockerReply{err: &exec.Error{Name: "/bin/freebsd-version", Err: exec.ErrNotFound}},
			freebsdVersions{}, "freebsd-version -u failed: freebsd-version did not start"},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			argv := fbsdVersionHost
			if c.jailed {
				argv = fbsdVersionJail
			}
			calls := stubFreeBSDCalls(t, true, map[string]dockerReply{argv: c.reply})
			got, why := readFreeBSDVersions(context.Background(), c.jailed)
			if got != c.want || why != c.why {
				t.Errorf("readFreeBSDVersions = %+v, %q, want %+v, %q", got, why, c.want, c.why)
			}
			if want := []freebsdCall{{pluginTimeout, argv}}; !reflect.DeepEqual(*calls, want) {
				t.Errorf("calls = %+v, want %+v", *calls, want)
			}
		})
	}
}

func TestFreebsdSystemState(t *testing.T) {
	// reboot_required compares the installed kernel with the running one, outside a jail; the count
	// adds the vulnerable packages and the vulnerable parts of a release's base system. pkg audit exits
	// 1 when it finds one.
	const (
		patched   = "15.0-RELEASE-p3\n15.0-RELEASE-p3\n15.0-RELEASE-p3\n"
		notBooted = "15.0-RELEASE-p3\n15.0-RELEASE-p1\n15.0-RELEASE-p3\n"
		stable    = "15.0-STABLE\n15.0-STABLE\n15.0-STABLE\n"
	)
	baseAudit := fbsdAudit + " FreeBSD-15.0_3 FreeBSD-kernel-15.0_3"
	found := smartctlExit(t, 1)
	cases := []struct {
		name    string
		system  string
		hasPkg  bool
		replies map[string]dockerReply
		calls   []string
		want    map[string]any
	}{
		{"bare metal, booted the installed kernel", "", true,
			map[string]dockerReply{fbsdVersionHost: {out: patched}, fbsdAudit: {}, baseAudit: {}},
			[]string{fbsdVersionHost, fbsdAudit, baseAudit},
			map[string]any{"reboot_required": false, "security_updates": 0}},
		{"VM, kernel installed but not booted, vulnerable packages and base", "bhyve", true,
			map[string]dockerReply{
				fbsdVersionHost: {out: notBooted},
				fbsdAudit:       {out: "curl-8.11.0\nopenssl-3.0.15_1,1\n", err: found},
				baseAudit:       {out: "FreeBSD-15.0_3\n", err: found},
			},
			[]string{fbsdVersionHost, fbsdAudit, baseAudit},
			map[string]any{"reboot_required": true, "security_updates": 3}},
		{"jail", "jail", true,
			map[string]dockerReply{
				fbsdVersionJail:               {out: "14.3-RELEASE-p5\n"},
				fbsdAudit:                     {},
				fbsdAudit + " FreeBSD-14.3_5": {out: "FreeBSD-14.3_5\n", err: found},
			},
			[]string{fbsdVersionJail, fbsdAudit, fbsdAudit + " FreeBSD-14.3_5"},
			map[string]any{"security_updates": 1}},
		{"stable: packages only", "", true,
			map[string]dockerReply{fbsdVersionHost: {out: stable}, fbsdAudit: {out: "curl-8.11.0\n", err: found}},
			[]string{fbsdVersionHost, fbsdAudit},
			map[string]any{"reboot_required": false, "security_updates": 1}},
		{"without pkg", "", false,
			map[string]dockerReply{fbsdVersionHost: {out: notBooted}},
			[]string{fbsdVersionHost},
			map[string]any{"reboot_required": true}},
		{"jail without pkg", "jail", false,
			map[string]dockerReply{fbsdVersionJail: {out: "14.3-RELEASE-p5\n"}},
			[]string{fbsdVersionJail},
			map[string]any{}},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			role := "guest"
			if c.system == "" {
				role = ""
			}
			stubVirtualization(t, c.system, role)
			calls := stubFreeBSDCalls(t, c.hasPkg, c.replies)
			logs := captureWarnings(t)
			block, next := freebsdSystemState(context.Background(), reportState{})
			if !reflect.DeepEqual(block, c.want) {
				t.Errorf("block = %v, want %v", block, c.want)
			}
			var argv []string
			for _, call := range *calls {
				argv = append(argv, call.argv)
				want := updatesTimeout
				if strings.HasPrefix(call.argv, "/bin/freebsd-version") {
					want = pluginTimeout
				}
				if call.timeout != want {
					t.Errorf("call %q under %s, want %s", call.argv, call.timeout, want)
				}
			}
			if !reflect.DeepEqual(argv, c.calls) {
				t.Errorf("calls = %q, want %q", argv, c.calls)
			}
			if !c.hasPkg {
				if next.Updates != nil {
					t.Errorf("state updates = %+v, want none without pkg", next.Updates)
				}
			} else if next.Updates == nil || next.Updates.CheckedUnix != pkgAuditNow.Unix() ||
				next.Updates.Security == nil || *next.Updates.Security != c.want["security_updates"] {
				t.Errorf("state updates = %+v, want %v counted at %d", next.Updates, c.want["security_updates"], pkgAuditNow.Unix())
			}
			assertFreeBSDLog(t, logs.String(), "")
		})
	}
}

func TestFreebsdSystemStateFailure(t *testing.T) {
	// A part that fails, hangs or prints what the parser does not know leaves its field out, and the
	// log says why, short and without paths or output. The failed count is saved as an attempt, so the
	// next report within the hour neither counts again nor sends the field.
	const (
		booted    = "15.0-RELEASE-p3\n15.0-RELEASE-p3\n15.0-RELEASE-p3\n"
		vulnLines = "curl-8.11.0\n"
	)
	baseAudit := fbsdAudit + " FreeBSD-15.0_3 FreeBSD-kernel-15.0_3"
	auditFailed := func(what, why string) string {
		return "system state: " + what + " failed: " + why + ", " + updatesLeftOut
	}
	cases := []struct {
		name    string
		system  string
		replies map[string]dockerReply
		block   map[string]any
		leak    string
		logs    []string
	}{
		{"freebsd-version fails", "", map[string]dockerReply{fbsdVersionHost: {err: smartctlExit(t, 1)}},
			map[string]any{}, "",
			[]string{"system state: freebsd-version -kru failed: exit status 1, reboot_required left out",
				"system state: freebsd-version -kru failed: exit status 1, " + updatesLeftOut}},
		{"freebsd-version unreadable in a jail", "jail", map[string]dockerReply{fbsdVersionJail: {out: "14.3 RELEASE\n"}},
			map[string]any{}, "14.3 RELEASE",
			[]string{"system state: unexpected output of freebsd-version -u, " + updatesLeftOut}},
		{"audit exits 1 without lines", "", map[string]dockerReply{fbsdVersionHost: {out: booted}, fbsdAudit: {err: smartctlExit(t, 1)}},
			map[string]any{"reboot_required": false}, "",
			[]string{auditFailed("pkg audit -q", "exit status 1")}},
		{"audit exits 1 with a blank line", "", map[string]dockerReply{fbsdVersionHost: {out: booted}, fbsdAudit: {out: "\n", err: smartctlExit(t, 1)}},
			map[string]any{"reboot_required": false}, "",
			[]string{auditFailed("pkg audit -q", "exit status 1")}},
		{"audit times out", "", map[string]dockerReply{fbsdVersionHost: {out: booted}, fbsdAudit: {err: context.DeadlineExceeded}},
			map[string]any{"reboot_required": false}, "",
			[]string{auditFailed("pkg audit -q", "timed out after 30s")}},
		{"audit exits 2 with lines", "", map[string]dockerReply{fbsdVersionHost: {out: booted}, fbsdAudit: {out: vulnLines, err: smartctlExit(t, 2)}},
			map[string]any{"reboot_required": false}, "curl",
			[]string{auditFailed("pkg audit -q", "exit status 2")}},
		{"audit does not start", "", map[string]dockerReply{
			fbsdVersionHost: {out: booted},
			fbsdAudit:       {err: &exec.Error{Name: "/usr/local/sbin/pkg", Err: exec.ErrNotFound}},
		}, map[string]any{"reboot_required": false}, "",
			[]string{auditFailed("pkg audit -q", "pkg did not start")}},
		{"audit output unreadable", "", map[string]dockerReply{fbsdVersionHost: {out: booted}, fbsdAudit: {out: "curl-8.11.0 is vulnerable:\n", err: smartctlExit(t, 1)}},
			map[string]any{"reboot_required": false}, "curl",
			[]string{"system state: unexpected output of pkg audit -q, " + updatesLeftOut}},
		{"base audit fails", "", map[string]dockerReply{
			fbsdVersionHost: {out: booted},
			fbsdAudit:       {out: vulnLines, err: smartctlExit(t, 1)},
			baseAudit:       {err: smartctlExit(t, 1)},
		}, map[string]any{"reboot_required": false}, "curl",
			[]string{auditFailed("pkg audit -q of the base system", "exit status 1")}},
		{"base audit unreadable", "", map[string]dockerReply{
			fbsdVersionHost: {out: booted},
			fbsdAudit:       {},
			baseAudit:       {out: "FreeBSD-15.0_3 is vulnerable:\n", err: smartctlExit(t, 1)},
		}, map[string]any{"reboot_required": false}, "FreeBSD-15.0_3",
			[]string{"system state: unexpected output of pkg audit -q of the base system, " + updatesLeftOut}},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			role := "guest"
			if c.system == "" {
				role = ""
			}
			stubVirtualization(t, c.system, role)
			calls := stubFreeBSDCalls(t, true, c.replies)
			logs := captureWarnings(t)
			block, next := freebsdSystemState(context.Background(), reportState{})
			if !reflect.DeepEqual(block, c.block) {
				t.Errorf("block = %v, want %v", block, c.block)
			}
			if next.Updates == nil || next.Updates.Security != nil || next.Updates.CheckedUnix != pkgAuditNow.Unix() {
				t.Errorf("state updates = %+v, want the attempt at %d without a number", next.Updates, pkgAuditNow.Unix())
			}
			assertFreeBSDLog(t, logs.String(), c.leak, c.logs...)

			before := len(*calls)
			updatesCalls.now = func() time.Time { return pkgAuditNow.Add(55 * time.Minute) }
			block, again := freebsdSystemState(context.Background(), next)
			if _, ok := block["security_updates"]; ok {
				t.Errorf("next report: block = %v, want no security_updates", block)
			}
			for _, call := range (*calls)[before:] {
				if !strings.HasPrefix(call.argv, "/bin/freebsd-version") {
					t.Errorf("next report called %q, want no count within the hour", call.argv)
				}
			}
			if again.Updates != next.Updates {
				t.Errorf("next report: state updates = %+v, want the attempt kept", again.Updates)
			}
		})
	}
}

func TestPkgSecurityUpdatesHourly(t *testing.T) {
	// A count younger than an hour is reported again without a call, also a failed one (no number);
	// an older one, one from the future (the clock was set back) and none at all are counted anew.
	// Without pkg nothing is counted, and a stale count is dropped rather than reported.
	three := 3
	versions := freebsdVersions{kernel: "15.0-STABLE", running: "15.0-STABLE", userland: "15.0-STABLE"}
	cases := []struct {
		name   string
		hasPkg bool
		saved  *updatesCheck
		call   bool
	}{
		{"none saved", true, nil, true},
		{"59 min old", true, &updatesCheck{CheckedUnix: pkgAuditNow.Add(-59 * time.Minute).Unix(), Security: &three}, false},
		{"failed 59 min ago", true, &updatesCheck{CheckedUnix: pkgAuditNow.Add(-59 * time.Minute).Unix()}, false},
		{"just now", true, &updatesCheck{CheckedUnix: pkgAuditNow.Unix(), Security: &three}, false},
		{"one hour old", true, &updatesCheck{CheckedUnix: pkgAuditNow.Add(-time.Hour).Unix(), Security: &three}, true},
		{"failed 61 min ago", true, &updatesCheck{CheckedUnix: pkgAuditNow.Add(-61 * time.Minute).Unix()}, true},
		{"from the future", true, &updatesCheck{CheckedUnix: pkgAuditNow.Add(5 * time.Minute).Unix(), Security: &three}, true},
		{"pkg removed, count still fresh", false, &updatesCheck{CheckedUnix: pkgAuditNow.Add(-10 * time.Minute).Unix(), Security: &three}, false},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			calls := stubFreeBSDCalls(t, c.hasPkg, map[string]dockerReply{fbsdAudit: {out: "curl-8.11.0\n", err: smartctlExit(t, 1)}})
			check := pkgSecurityUpdates(context.Background(), c.saved, versions, "")
			if !c.call {
				if check != c.saved || len(*calls) != 0 {
					t.Errorf("pkgSecurityUpdates = %+v after %d call(s), want the saved %+v without one",
						check, len(*calls), c.saved)
				}
				return
			}
			if len(*calls) != 1 || check == nil || check.Security == nil || *check.Security != 1 ||
				check.CheckedUnix != pkgAuditNow.Unix() {
				t.Errorf("pkgSecurityUpdates = %+v after %d call(s), want 1 counted now in one call", check, len(*calls))
			}
		})
	}
	t.Run("pkg removed, count stale", func(t *testing.T) {
		calls := stubFreeBSDCalls(t, false, nil)
		saved := &updatesCheck{CheckedUnix: pkgAuditNow.Add(-2 * time.Hour).Unix(), Security: &three}
		if check := pkgSecurityUpdates(context.Background(), saved, versions, ""); check != nil || len(*calls) != 0 {
			t.Errorf("pkgSecurityUpdates = %+v after %d call(s), want nil without a call", check, len(*calls))
		}
	})
}

func TestInContainerJail(t *testing.T) {
	// A jail shares the host's kernel, load and boot, as a container does; the VM a jail may run in
	// (freebsdVirtualization reports the jail) and a bare VM are no containers.
	cases := []struct {
		system, role string
		want         bool
	}{
		{"jail", "guest", true},
		{"bhyve", "guest", false},
		{"jail", "host", false},
		{"", "", false},
	}
	for _, c := range cases {
		stubVirtualization(t, c.system, c.role)
		if got := inContainer(); got != c.want {
			t.Errorf("inContainer() with %q/%q = %v, want %v", c.system, c.role, got, c.want)
		}
	}
}
