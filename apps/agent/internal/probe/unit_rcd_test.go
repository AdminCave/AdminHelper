// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package probe

import (
	"context"
	"errors"
	"os/exec"
	"slices"
	"strings"
	"testing"
)

// stubStarted puts in a processStarted that answers ms for every pid and records the pids it is asked.
func stubStarted(t *testing.T, ms int64, err error) *[]int32 {
	t.Helper()
	var asked []int32
	old := processStarted
	processStarted = func(_ context.Context, pid int32) (int64, error) {
		asked = append(asked, pid)
		return ms, err
	}
	t.Cleanup(func() { processStarted = old })
	return &asked
}

func TestRcStatusReadsThePidsOfTheService(t *testing.T) {
	cases := []struct {
		name string
		out  string
		exit int // the exit status of service(8), 0 for none
		want []int32
	}{
		{"one pid", "nginx is running as pid 1234.\n", 0, []int32{1234}},
		{"several pids", "php_fpm is running as pid 10 11 12.\n", 0, []int32{10, 11, 12}},
		{"a line before the status", "Cannot 'status' foo.\nnginx is running as pid 7.\n", 0, []int32{7}},
		{"not running", "nginx is not running.\n", 1, nil},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			var err error
			if c.exit != 0 {
				err = toolExit(t, c.exit, "")
			}
			calls := stubTools(t, answer{out: c.out, err: err})
			got, err := rcStatus(context.Background(), "nginx")
			if err != nil || !slices.Equal(got, c.want) {
				t.Errorf("rcStatus = %v, %v, want %v", got, err, c.want)
			}
			if want := []string{"/usr/sbin/service", "nginx", "onestatus"}; len(*calls) != 1 || !slices.Equal((*calls)[0], want) {
				t.Errorf("calls %q, want one %q", *calls, want)
			}
		})
	}
}

func TestRcStatusFailsOnAnAnswerOfAnotherForm(t *testing.T) {
	cases := []struct {
		name string
		a    func(t *testing.T) answer
		want string
	}{
		{"no such script", func(t *testing.T) answer {
			return answer{err: toolExit(t, 1, "nginx does not exist in /etc/rc.d or the local startup\n")}
		}, "does not exist on this host"},
		{"another status", func(*testing.T) answer { return answer{out: "nginx: up and serving\n"} }, "does not exist on this host"},
		{"pid 0", func(*testing.T) answer { return answer{out: "nginx is running as pid 0.\n"} }, `pid "0"`},
		{"a pid past 32 bits", func(*testing.T) answer { return answer{out: "nginx is running as pid 4294967296.\n"} }, "pid"},
		{"service(8) missing", func(*testing.T) answer { return answer{err: notInstalled(servicePath)} }, "onestatus"},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			stubTools(t, c.a(t))
			got, err := rcStatus(context.Background(), "nginx")
			if err == nil || !strings.Contains(err.Error(), c.want) {
				t.Errorf("rcStatus = %v, %v, want an error naming %q", got, err, c.want)
			}
		})
	}
	stubTools(t, answer{err: notInstalled(servicePath)})
	if _, err := rcStatus(context.Background(), "nginx"); !errors.Is(err, exec.ErrNotFound) {
		t.Errorf("rcStatus without service(8) = %v, want it to wrap exec.ErrNotFound", err)
	}
}

func TestRcOwnerAcceptsThePidsOfTheServiceAlone(t *testing.T) {
	stubTools(t, answer{out: "nginx is running as pid 10 11.\n"})
	owns, err := rcOwner(context.Background(), "nginx")
	if err != nil {
		t.Fatalf("rcOwner = %v", err)
	}
	for pid, want := range map[int32]bool{10: true, 11: true, 12: false, 0: false} {
		if owns(pid) != want {
			t.Errorf("owns(%d) = %v, want %v", pid, !want, want)
		}
	}

	stubTools(t, answer{out: "nginx is not running.\n", err: toolExit(t, 1, "")})
	if _, err := rcOwner(context.Background(), "nginx"); !errors.Is(err, errNotListening) {
		t.Errorf("rcOwner of a stopped service = %v, want errNotListening", err)
	}
}

func TestMeasureRCReadsTheStateOfTheService(t *testing.T) {
	ctx := context.Background()
	asked := stubStarted(t, 1_700_000_000_999, nil)
	stubTools(t, answer{out: "nginx is running as pid 42 43.\n"})
	got, err := measureRC(ctx, "nginx")
	want := map[string]any{"active_state": "active", "sub_state": "running", "active_since": int64(1_700_000_000)}
	if err != nil || len(got) != len(want) || got["active_state"] != want["active_state"] ||
		got["sub_state"] != want["sub_state"] || got["active_since"] != want["active_since"] {
		t.Errorf("measureRC = %v, %v, want %v", got, err, want)
	}
	if !slices.Equal(*asked, []int32{42}) {
		t.Errorf("processStarted asked for %v, want the first pid 42", *asked)
	}

	stubStarted(t, 0, errors.New("gone"))
	stubTools(t, answer{out: "nginx is running as pid 42.\n"})
	if got, err := measureRC(ctx, "nginx"); err != nil || got["active_state"] != "active" || got["active_since"] != nil {
		t.Errorf("measureRC of a process that cannot be read = %v, %v, want active without active_since", got, err)
	}

	stubTools(t, answer{out: "nginx is not running.\n", err: toolExit(t, 1, "")})
	if got, err := measureRC(ctx, "nginx"); err != nil || len(got) != 2 || got["active_state"] != "inactive" || got["sub_state"] != "stopped" {
		t.Errorf("measureRC of a stopped service = %v, %v, want inactive/stopped", got, err)
	}

	stubTools(t, answer{out: ""})
	if _, err := measureRC(ctx, "nginx"); err == nil {
		t.Error("measureRC of a script without status = nil, want an error")
	}
}

func TestRcNamePatternTakesTheNamesOfScriptsAlone(t *testing.T) {
	for _, name := range []string{"nginx", "php_fpm", "os-adminhelper", "configd", "a.b", "_x", strings.Repeat("a", 255)} {
		if !rcNamePattern.MatchString(name) {
			t.Errorf("rcNamePattern refuses %q", name)
		}
	}
	for _, name := range []string{"", ".", "..", "../sshd", "a/b", "-x", ".hidden", "a b", "a\nb", strings.Repeat("a", 256)} {
		if rcNamePattern.MatchString(name) {
			t.Errorf("rcNamePattern takes %q", name)
		}
	}
}
