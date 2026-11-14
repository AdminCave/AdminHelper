// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package probe

import (
	"context"
	"errors"
	"os/exec"
	"reflect"
	"slices"
	"testing"
)

// lpstatOut is `LC_ALL=C lpstat -p` with one idle, one printing and one disabled queue, the second
// line of the disabled one being its reason.
const lpstatOut = `printer office is idle.  enabled since Sat 14 Nov 2026 09:12:03 AM CET
printer label now printing label-17.  enabled since Sat 14 Nov 2026 10:01:44 AM CET
printer basement disabled since Fri 13 Nov 2026 06:30:00 PM CET -
	Paused
`

func TestCupsQueuesCountsTheDisabledQueues(t *testing.T) {
	calls := stubToolsEnv(t, answer{out: lpstatOut})
	got, err := cupsQueues(context.Background(), Target{Kind: kindUnit, Name: "cups.service"})
	if err != nil {
		t.Fatal(err)
	}
	if want := map[string]any{"queues": 3, "queues_disabled": 1}; !reflect.DeepEqual(got, want) {
		t.Fatalf("got %v, want %v", got, want)
	}
	if c := (*calls)[0]; !slices.Equal(c.args, []string{"lpstat", "-p"}) || !slices.Equal(c.env, []string{"LC_ALL=C"}) {
		t.Fatalf("call %q env %q", c.args, c.env)
	}
}

func TestCupsQueuesWithoutQueuesIsZero(t *testing.T) {
	stubToolsEnv(t, answer{err: repoExit(t, 1, "lpstat: No destinations added.\n")})
	got, err := cupsQueues(context.Background(), Target{Kind: kindUnit, Name: "cups.service"})
	if err != nil {
		t.Fatal(err)
	}
	if want := map[string]any{"queues": 0, "queues_disabled": 0}; !reflect.DeepEqual(got, want) {
		t.Fatalf("got %v, want %v", got, want)
	}
}

func TestCupsQueuesReportsAFailedCall(t *testing.T) {
	stubToolsEnv(t, answer{err: repoExit(t, 1, "lpstat: Scheduler is not running.\n")})
	if _, err := cupsQueues(context.Background(), Target{Kind: kindUnit, Name: "cups.service"}); err == nil {
		t.Fatal("a scheduler that does not run reads as zero queues")
	}
	stubToolsEnv(t, answer{err: exec.ErrNotFound})
	if _, err := cupsQueues(context.Background(), Target{Kind: kindUnit, Name: "cups.service"}); !errors.Is(err, ErrUnsupported) {
		t.Fatalf("no lpstat = %v, want unsupported", err)
	}
}
