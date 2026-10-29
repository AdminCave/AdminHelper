// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build linux

package main

import (
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"slices"
	"strconv"
	"strings"
	"testing"
)

// On an upgrade rpm runs the %post of the new package before the %preun and %postun
// of the old one, and the %posttrans of the new one last (rpm-scriptlets(7)). These
// tests run the spec's scriptlets in that order with /bin/sh against a systemctl stub,
// so a scriptlet that stops what an earlier one started fails here, not only on a
// host after `dnf upgrade`.

const (
	timerUnit = "adminhelper-agent.timer"
	frpcUnit  = "frpc.service"
)

// releasedScriptlets are the scriptlets of the packages up to main@82e4a7b8. Their
// %preun stops the timer and frpc on an upgrade too, after the new %post started
// them; an upgrade from one of them still has to end with both running.
const releasedScriptlets = `%post
systemctl daemon-reload
# Alte Units aufraeumen
for unit in srm-frpc-sync.timer srm-frpc-sync.service srm-monitor-agent.timer srm-monitor-agent.service srm-agent.timer srm-agent.service; do
    if [ -f "/etc/systemd/system/${unit}" ]; then
        systemctl stop "${unit}" 2>/dev/null || true
        systemctl disable "${unit}" 2>/dev/null || true
        rm -f "/etc/systemd/system/${unit}"
    fi
done
systemctl daemon-reload
# Timer aktivieren: laeuft ohne Config harmlos (Sync/Push skippen still).
# $1 == 1: frische Installation, $1 == 2: Upgrade — beide sollen enablen.
systemctl enable --now adminhelper-agent.timer >/dev/null 2>&1 || true
# frpc.service nur reaktivieren, wenn bereits provisioniert.
if [ -f /etc/frp/frpc.toml ]; then
    systemctl enable --now frpc.service >/dev/null 2>&1 || true
fi
echo "adminhelper-agent installiert. Timer ist aktiv (laeuft alle 5 Minuten)."
echo "Einrichtung (Server + Monitor + FRP): sudo adminhelper-agent provision --url <ADMINHELPER_URL> --token-stdin --server-id <ID>  (Token danach einfuegen, Enter)"
echo "Nur Monitoring (alternativ):          sudo adminhelper-agent monitor init --url <MONITOR_URL> --api-key <KEY> --server-id <ID>"

%preun
# $1 == 0: Uninstall (stop + disable), $1 == 1: Upgrade (nur stop)
systemctl stop adminhelper-agent.timer 2>/dev/null || true
systemctl stop frpc.service 2>/dev/null || true
if [ "$1" -eq 0 ]; then
    systemctl disable adminhelper-agent.timer 2>/dev/null || true
    systemctl disable frpc.service 2>/dev/null || true
fi

%postun
systemctl daemon-reload
`

// systemctlStub keeps, per unit, whether it is enabled and active as files in
// $AH_SYSTEMCTL_STATE, and logs every call to calls and every unit it starts or
// restarts to starts. Starting a unit that is already active is no start.
const systemctlStub = `#!/bin/sh
s=$AH_SYSTEMCTL_STATE
echo "$*" >> "$s/calls"
start() {
    if [ "$2" = restart ] || [ ! -f "$s/$1.active" ]; then echo "$1" >> "$s/starts"; fi
    : > "$s/$1.active"
}
cmd=$1
shift
now=
for a in "$@"; do
    if [ "$a" = --now ]; then now=1; fi
done
for u in "$@"; do
    case "$u" in -*) continue ;; esac
    case "$cmd" in
        enable) : > "$s/$u.enabled"; if [ -n "$now" ]; then start "$u"; fi ;;
        disable) rm -f "$s/$u.enabled"; if [ -n "$now" ]; then rm -f "$s/$u.active"; fi ;;
        start) start "$u" ;;
        restart) start "$u" restart ;;
        stop) rm -f "$s/$u.active" ;;
    esac
done
exit 0
`

var (
	specSectionRE = regexp.MustCompile(`^%([a-z_]+)(\s.*)?$`)
	// The sections of a spec that hold no scriptlet. A line starting with any other
	// %word that is no scriptlet either (%dir, %global, %setup) belongs to the section
	// above it.
	specOtherSections = []string{"description", "package", "prep", "generate_buildrequires", "conf",
		"build", "install", "check", "clean", "files", "changelog"}
	// The scriptlets these tests run. The spec may have no other one: nothing here
	// would run it.
	simulatedScriptlets = []string{"post", "preun", "postun", "posttrans"}
)

func isScriptlet(name string) bool {
	return strings.Contains(name, "trigger") || slices.Contains([]string{"pretrans", "pre", "post", "preun",
		"postun", "posttrans", "preuntrans", "postuntrans", "verifyscript"}, name)
}

// scriptlets returns the body of each scriptlet in a spec by name ("post", …).
func scriptlets(t *testing.T, spec string) map[string]string {
	t.Helper()
	got := map[string]string{}
	cur := ""
	for _, line := range strings.Split(spec, "\n") {
		m := specSectionRE.FindStringSubmatch(line)
		switch {
		case m != nil && isScriptlet(m[1]):
			if !slices.Contains(simulatedScriptlets, m[1]) || strings.TrimSpace(m[2]) != "" {
				t.Fatalf("spec: %q is a scriptlet these tests cannot run", line)
			}
			cur = m[1]
		case m != nil && slices.Contains(specOtherSections, m[1]):
			cur = ""
		case cur != "":
			got[cur] += line + "\n"
		}
	}
	for name, body := range got {
		// rpm expands macros in a scriptlet, /bin/sh does not.
		if strings.Contains(body, "%") {
			t.Fatalf("spec: %%%s carries a %% that rpm would expand as a macro:\n%s", name, body)
		}
	}
	return got
}

func specScriptlets(t *testing.T) map[string]string {
	t.Helper()
	data, err := os.ReadFile("../../rpm/adminhelper-agent.spec")
	if err != nil {
		t.Fatalf("read spec: %v", err)
	}
	return scriptlets(t, string(data))
}

// scriptletStep is one scriptlet run with its argument $1; a missing scriptlet is
// empty.
type scriptletStep struct {
	name, body string
	arg        int
}

// upgradeSteps is the order of rpm-scriptlets(7) for an upgrade from one package to the next.
func upgradeSteps(from, to map[string]string) []scriptletStep {
	return []scriptletStep{
		{"new %post", to["post"], 2},
		{"old %preun", from["preun"], 1},
		{"old %postun", from["postun"], 1},
		{"new %posttrans", to["posttrans"], 0},
	}
}

// stepLog is what the systemctl stub saw during one step.
type stepLog struct {
	name          string
	calls, starts []string
}

type rpmHost struct {
	root, state, scripts, path string
}

// newRPMHost is a host with /etc/frp/frpc.toml if frpcConfig and the units in
// running enabled and active.
func newRPMHost(t *testing.T, frpcConfig bool, running ...string) *rpmHost {
	t.Helper()
	h := &rpmHost{root: t.TempDir(), state: t.TempDir(), scripts: t.TempDir()}
	bin := t.TempDir()
	if err := os.WriteFile(filepath.Join(bin, "systemctl"), []byte(systemctlStub), 0o755); err != nil {
		t.Fatal(err)
	}
	h.path = bin + string(os.PathListSeparator) + os.Getenv("PATH")
	if frpcConfig {
		if err := os.MkdirAll(filepath.Join(h.root, "etc/frp"), 0o700); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(filepath.Join(h.root, "etc/frp/frpc.toml"), nil, 0o600); err != nil {
			t.Fatal(err)
		}
	}
	for _, u := range running {
		for _, f := range []string{u + ".enabled", u + ".active"} {
			if err := os.WriteFile(filepath.Join(h.state, f), nil, 0o600); err != nil {
				t.Fatal(err)
			}
		}
	}
	return h
}

// run runs the steps in order with /bin/sh, the way rpm does, with /etc/ in the
// scriptlets pointing into the host's root. A failed test shows what systemctl saw.
func (h *rpmHost) run(t *testing.T, steps []scriptletStep) []stepLog {
	t.Helper()
	var logs []stepLog
	t.Cleanup(func() {
		if t.Failed() {
			t.Logf("systemctl calls per scriptlet:\n%s", renderSteps(logs))
		}
	})
	for i, s := range steps {
		for _, f := range []string{"calls", "starts"} {
			if err := os.Remove(filepath.Join(h.state, f)); err != nil && !os.IsNotExist(err) {
				t.Fatal(err)
			}
		}
		script := filepath.Join(h.scripts, strconv.Itoa(i)+".sh")
		body := strings.ReplaceAll(s.body, "/etc/", h.root+"/etc/")
		if err := os.WriteFile(script, []byte(body), 0o600); err != nil {
			t.Fatal(err)
		}
		cmd := exec.Command("/bin/sh", script, strconv.Itoa(s.arg))
		cmd.Env = append(os.Environ(), "PATH="+h.path, "AH_SYSTEMCTL_STATE="+h.state)
		if out, err := cmd.CombinedOutput(); err != nil {
			t.Fatalf("%s ($1=%d): %v\n%s", s.name, s.arg, err, out)
		}
		logs = append(logs, stepLog{s.name, h.lines(t, "calls"), h.lines(t, "starts")})
	}
	return logs
}

func (h *rpmHost) lines(t *testing.T, name string) []string {
	t.Helper()
	data, err := os.ReadFile(filepath.Join(h.state, name))
	if os.IsNotExist(err) {
		return nil
	}
	if err != nil {
		t.Fatal(err)
	}
	return strings.Split(strings.TrimSuffix(string(data), "\n"), "\n")
}

func (h *rpmHost) unit(name string) (enabled, active bool) {
	_, err := os.Stat(filepath.Join(h.state, name+".enabled"))
	enabled = err == nil
	_, err = os.Stat(filepath.Join(h.state, name+".active"))
	return enabled, err == nil
}

func renderSteps(logs []stepLog) string {
	var b strings.Builder
	for _, l := range logs {
		fmt.Fprintf(&b, "%s:\n", l.name)
		for _, c := range l.calls {
			fmt.Fprintf(&b, "  systemctl %s\n", c)
		}
		for _, u := range l.starts {
			fmt.Fprintf(&b, "  (started %s)\n", u)
		}
	}
	return b.String()
}

// startedAfter reports whether unit was started or restarted in a step after the
// step named after.
func startedAfter(logs []stepLog, after, unit string) bool {
	i := slices.IndexFunc(logs, func(l stepLog) bool { return l.name == after })
	if i < 0 {
		return false
	}
	return slices.ContainsFunc(logs[i+1:], func(l stepLog) bool { return slices.Contains(l.starts, unit) })
}

func TestRPMUpgradeLeavesTimerAndFrpcRunning(t *testing.T) {
	spec := specScriptlets(t)
	for _, tc := range []struct {
		name string
		old  map[string]string
	}{
		{"from the released package", scriptlets(t, releasedScriptlets)},
		{"to the same version", spec},
	} {
		t.Run(tc.name, func(t *testing.T) {
			h := newRPMHost(t, true, timerUnit, frpcUnit)
			logs := h.run(t, upgradeSteps(tc.old, spec))
			for _, u := range []string{timerUnit, frpcUnit} {
				if enabled, active := h.unit(u); !enabled || !active {
					t.Errorf("%s after the upgrade: enabled=%v active=%v, want both", u, enabled, active)
				}
			}
			// Only a start after the old package is gone runs frpc on the new binary.
			if !startedAfter(logs, "old %preun", frpcUnit) {
				t.Errorf("%s not started after the old %%preun", frpcUnit)
			}
		})
	}
}

// The harness has to be able to fail: the released package upgrading to itself
// leaves both units enabled but stopped, the bug the test above pins.
func TestRPMCheckCatchesTheReleasedUpgrade(t *testing.T) {
	released := scriptlets(t, releasedScriptlets)
	h := newRPMHost(t, true, timerUnit, frpcUnit)
	h.run(t, upgradeSteps(released, released))
	for _, u := range []string{timerUnit, frpcUnit} {
		if enabled, active := h.unit(u); !enabled || active {
			t.Errorf("%s: enabled=%v active=%v, want enabled and stopped", u, enabled, active)
		}
	}
}

func TestRPMInstallWithoutFrpcConfigStartsOnlyTheTimer(t *testing.T) {
	spec := specScriptlets(t)
	h := newRPMHost(t, false)
	logs := h.run(t, []scriptletStep{{"%post", spec["post"], 1}, {"%posttrans", spec["posttrans"], 0}})
	if enabled, active := h.unit(timerUnit); !enabled || !active {
		t.Errorf("%s: enabled=%v active=%v, want both", timerUnit, enabled, active)
	}
	for _, l := range logs {
		for _, c := range l.calls {
			if strings.Contains(c, frpcUnit) {
				t.Errorf("%s calls systemctl %s without frpc.toml", l.name, c)
			}
		}
	}
}

func TestRPMEraseStopsAndDisablesBoth(t *testing.T) {
	spec := specScriptlets(t)
	h := newRPMHost(t, true, timerUnit, frpcUnit)
	h.run(t, []scriptletStep{{"%preun", spec["preun"], 0}, {"%postun", spec["postun"], 0}})
	for _, u := range []string{timerUnit, frpcUnit} {
		if enabled, active := h.unit(u); enabled || active {
			t.Errorf("%s after the erase: enabled=%v active=%v, want neither", u, enabled, active)
		}
	}
}
